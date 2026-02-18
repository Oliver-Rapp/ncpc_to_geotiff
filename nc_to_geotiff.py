import argparse
import yaml
import os
import sys
import numpy as np
import xarray as xr
import rasterio
from rasterio.transform import from_origin
from rasterio.crs import CRS

def load_config(config_path):
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

def get_crs_from_netcdf(ds):
    """
    Attempts to extract the CRS WKT from the NetCDF CF-compliant 'crs' variable.
    """
    try:
        if 'crs' in ds.variables:
            wkt = ds['crs'].attrs.get('crs_wkt', None)
            if wkt:
                return CRS.from_wkt(wkt)
            
            epsg = ds['crs'].attrs.get('epsg_code', None)
            if epsg:
                return CRS.from_epsg(epsg)
    except Exception as e:
        print(f"Warning: Could not extract CRS from NetCDF. Error: {e}")
    
    print("Warning: No CRS found. GeoTIFF will not be projected.")
    return None

def process_point_cloud(config, input_path, output_path):
    print(f"Opening {input_path}...")
    
    ds = xr.open_dataset(input_path, chunks={'point': config['processing']['chunk_size']})
    
    # 1. Determine Grid Bounds
    print("Calculating spatial extents...")
    min_x = ds['X'].min().values
    max_x = ds['X'].max().values
    min_y = ds['Y'].min().values
    max_y = ds['Y'].max().values

    res = config['grid']['resolution']
    
    # Align bounds to resolution if requested
    if config['grid']['bounds_strategy'] == 'rounded':
        min_x = np.floor(min_x / res) * res
        max_y = np.ceil(max_y / res) * res

    # Calculate grid dimensions
    width = int(np.ceil((max_x - min_x) / res))
    height = int(np.ceil((max_y - min_y) / res))
    
    print(f"Grid Size: {width} x {height} pixels")

    # Define Affine Transform (Top-Left convention)
    transform = from_origin(min_x, max_y, res, res)

    # 2. Initialize Accumulators
    bands_config = config['output_bands']
    num_bands = len(bands_config)
    
    # Accumulators for aggregating values
    # We use Float64 for precision during accumulation
    grid_sums = np.zeros((num_bands, height, width), dtype=np.float64)
    grid_counts = np.zeros((num_bands, height, width), dtype=np.uint32)
    
    # Initialize min/max grids with appropriate infinity values
    grid_mins = np.full((num_bands, height, width), np.inf, dtype=np.float64)
    grid_maxs = np.full((num_bands, height, width), -np.inf, dtype=np.float64)

    # 3. Process Chunks
    total_points = ds.sizes['point']
    chunk_size = config['processing']['chunk_size']
    
    print(f"Rasterizing {total_points} points...")

    # Manual chunk iteration to control memory
    for i in range(0, total_points, chunk_size):
        subset = ds.isel(point=slice(i, i + chunk_size))
        
        # Load coordinates
        xs = subset['X'].values
        ys = subset['Y'].values
        
        # Calculate pixel indices
        cols = ((xs - min_x) / res).astype(np.int32)
        rows = ((max_y - ys) / res).astype(np.int32)
        
        # Boundary check
        valid_mask = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
        
        if not np.any(valid_mask):
            continue

        rows = rows[valid_mask]
        cols = cols[valid_mask]
        
        # Flat indices for fast numpy aggregation
        flat_indices = rows * width + cols
        
        for band_idx, band_cfg in enumerate(bands_config):
            var_name = band_cfg['variable']
            method = band_cfg['method']
            
            if var_name not in subset:
                continue
                
            values = subset[var_name].values[valid_mask]
            
            if method == 'mean':
                np.add.at(grid_sums[band_idx].ravel(), flat_indices, values)
                np.add.at(grid_counts[band_idx].ravel(), flat_indices, 1)
            elif method == 'count':
                np.add.at(grid_sums[band_idx].ravel(), flat_indices, 1)
            elif method == 'max':
                np.maximum.at(grid_maxs[band_idx].ravel(), flat_indices, values)
                np.add.at(grid_counts[band_idx].ravel(), flat_indices, 1) # Mark presence
            elif method == 'min':
                np.minimum.at(grid_mins[band_idx].ravel(), flat_indices, values)
                np.add.at(grid_counts[band_idx].ravel(), flat_indices, 1) # Mark presence
        
        sys.stdout.write(f"\rProcessed {min(i + chunk_size, total_points)} / {total_points}")
        sys.stdout.flush()
    
    print("\nFinalizing grid...")

    # 4. Finalize Aggregation
    # Default to Float32 for GeoTIFF output to handle most data types cleanly
    final_raster = np.zeros((num_bands, height, width), dtype=np.float32)
    
    for band_idx, band_cfg in enumerate(bands_config):
        method = band_cfg['method']
        nodata = band_cfg.get('nodata_val', 0)
        
        counts = grid_counts[band_idx]
        has_data_mask = counts > 0
        
        if method == 'mean':
            # Perform division only where data exists
            final_raster[band_idx][has_data_mask] = (
                grid_sums[band_idx][has_data_mask] / counts[has_data_mask]
            )
        elif method == 'count':
            final_raster[band_idx] = grid_sums[band_idx]
            # For count, 0 is usually valid (no data), but we can still respect mask if needed
        elif method == 'max':
            final_raster[band_idx][has_data_mask] = grid_maxs[band_idx][has_data_mask]
        elif method == 'min':
            final_raster[band_idx][has_data_mask] = grid_mins[band_idx][has_data_mask]

        # STRICT NO-INTERPOLATION:
        # Apply Nodata value to any pixel that had 0 accumulated points
        final_raster[band_idx][~has_data_mask] = nodata

    # 5. Write GeoTIFF
    crs = get_crs_from_netcdf(ds)
    
    # Get global nodata value from first band configuration
    global_nodata = bands_config[0].get('nodata_val', 0)

    print(f"Writing to {output_path}...")
    
    meta = {
        'driver': 'GTiff',
        'height': height,
        'width': width,
        'count': num_bands,
        'dtype': 'float32',
        'crs': crs,
        'transform': transform,
        'compress': 'lzw',
        'nodata': global_nodata
    }

    with rasterio.open(output_path, 'w', **meta) as dst:
        for i in range(num_bands):
            dst.write(final_raster[i], i + 1)
            var_name = bands_config[i]['variable']
            # Try to get a clean description from NetCDF attributes
            desc = ds[var_name].attrs.get('long_name', var_name)
            dst.set_band_description(i + 1, desc)

    print("Done.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert NetCDF Point Cloud to GeoTIFF (No Interpolation)")
    parser.add_argument("-c", "--config", help="Path to config.yaml", default="config.yaml")
    parser.add_argument("-i", "--input", help="Override input NetCDF file path")
    parser.add_argument("-o", "--output", help="Override output GeoTIFF file path")
    
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"Config file not found: {args.config}")
        sys.exit(1)

    config = load_config(args.config)
    
    input_file = args.input if args.input else config.get('input_file')
    output_file = args.output if args.output else config.get('output_file')

    if not input_file or not os.path.exists(input_file):
        print(f"Input file not found: {input_file}")
        sys.exit(1)

    process_point_cloud(config, input_file, output_file)