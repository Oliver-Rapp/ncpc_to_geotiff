import argparse
import yaml
import os
import sys
import numpy as np
import xarray as xr
import rasterio
from rasterio.transform import from_origin
from rasterio.crs import CRS
from pathlib import Path
from urllib.parse import urlparse

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

def is_opendap_url(path):
    return path.startswith(("http://", "https://"))

def process_point_cloud(config, input_path, output_path):
    if is_opendap_url(input_path):
        print(f"Connecting to OPeNDAP server: {input_path}")
        print("Metadata will be read remotely; data is fetched in chunks during processing.")
    else:
        print(f"Opening {input_path}...")

    # Lazy load the dataset with chunking
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
    
    # Accumulators
    # Float64 used during accumulation for precision, converted to Float32 at write time
    grid_sums = np.zeros((num_bands, height, width), dtype=np.float64)
    grid_counts = np.zeros((num_bands, height, width), dtype=np.uint32)
    
    # Initialize min/max grids
    grid_mins = np.full((num_bands, height, width), np.inf, dtype=np.float64)
    grid_maxs = np.full((num_bands, height, width), -np.inf, dtype=np.float64)

    # 3. Process Chunks
    total_points = ds.sizes['point']
    chunk_size = config['processing']['chunk_size']
    
    if is_opendap_url(input_path):
        print(f"Fetching and rasterizing {total_points} points in chunks (data downloaded per chunk)...")
    else:
        print(f"Rasterizing {total_points} points in chunks...")

    for i in range(0, total_points, chunk_size):
        subset = ds.isel(point=slice(i, i + chunk_size))
        
        # Load spatial coordinates
        xs = subset['X'].values
        ys = subset['Y'].values
        
        # Calculate pixel indices
        cols = ((xs - min_x) / res).astype(np.int32)
        rows = ((max_y - ys) / res).astype(np.int32)
        
        # Boundary filter
        valid_mask = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
        
        if not np.any(valid_mask):
            continue

        rows = rows[valid_mask]
        cols = cols[valid_mask]
        flat_indices = rows * width + cols
        
        for band_idx, band_cfg in enumerate(bands_config):
            var_name = band_cfg['variable']
            method = band_cfg['method']
            
            if var_name not in subset:
                print(f"Skipping missing variable: {var_name}")
                continue
            
            # --- UNIVERSAL DATA HANDLING ---
            # Get the variable (lazy load)
            data_var = subset[var_name]

            # 1. Handle Hyperspectral Band Selection
            if 'band_selection' in band_cfg:
                target = band_cfg['band_selection']
                try:
                    # 'method=nearest' ensures we find the closest wavelength if exact match fails
                    data_var = data_var.sel(band=target, method='nearest')
                except Exception as e:
                    print(f"Error selecting band {target} for {var_name}: {e}")
                    continue
            
            # 2. Dimensionality Check
            # By this point, the data MUST be 1D (only dependent on 'point').
            # If it still has 2 dimensions (e.g. point, band), the config is missing 'band_selection'.
            if len(data_var.dims) > 1:
                print(f"Error: Variable '{var_name}' is multi-dimensional {data_var.dims}. "
                      f"Please add 'band_selection' to config. Skipping.")
                continue

            # 3. Load values for this chunk
            values = data_var.values[valid_mask]
            
            # 4. Aggregate
            if method == 'mean':
                np.add.at(grid_sums[band_idx].ravel(), flat_indices, values)
                np.add.at(grid_counts[band_idx].ravel(), flat_indices, 1)
            elif method == 'count':
                np.add.at(grid_sums[band_idx].ravel(), flat_indices, 1)
            elif method == 'max':
                np.maximum.at(grid_maxs[band_idx].ravel(), flat_indices, values)
                np.add.at(grid_counts[band_idx].ravel(), flat_indices, 1) 
            elif method == 'min':
                np.minimum.at(grid_mins[band_idx].ravel(), flat_indices, values)
                np.add.at(grid_counts[band_idx].ravel(), flat_indices, 1) 
        
        sys.stdout.write(f"\rProcessed {min(i + chunk_size, total_points)} / {total_points}")
        sys.stdout.flush()
    
    print("\nFinalizing grid...")

    # 4. Finalize Aggregation
    final_raster = np.zeros((num_bands, height, width), dtype=np.float32)
    
    for band_idx, band_cfg in enumerate(bands_config):
        method = band_cfg['method']
        nodata = band_cfg.get('nodata_val', 0)
        
        counts = grid_counts[band_idx]
        has_data_mask = counts > 0
        
        if method == 'mean':
            final_raster[band_idx][has_data_mask] = (
                grid_sums[band_idx][has_data_mask] / counts[has_data_mask]
            )
        elif method == 'count':
            final_raster[band_idx] = grid_sums[band_idx]
        elif method == 'max':
            final_raster[band_idx][has_data_mask] = grid_maxs[band_idx][has_data_mask]
        elif method == 'min':
            final_raster[band_idx][has_data_mask] = grid_mins[band_idx][has_data_mask]

        # Apply transparency (No Interpolation)
        final_raster[band_idx][~has_data_mask] = nodata

    # 5. Write GeoTIFF
    crs = get_crs_from_netcdf(ds)
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
            
            # Metadata Description
            var_name = bands_config[i]['variable']
            desc = f"{var_name}"
            
            if 'band_selection' in bands_config[i]:
                desc += f" ({bands_config[i]['band_selection']}nm)"
                
            dst.set_band_description(i + 1, desc)

    print(f"Done. Saved to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert CF-NetCDF Point Cloud to GeoTIFF")
    
    # Input is now mandatory
    parser.add_argument("-i", "--input", required=True, help="Input NetCDF file path")
    
    parser.add_argument("-c", "--config", help="Path to config.yaml", default="config.yaml")
    parser.add_argument("-o", "--output", help="Override output GeoTIFF file path")
    
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"Error: Config file not found: {args.config}")
        sys.exit(1)

    if is_opendap_url(args.input) and args.input.endswith('.html'):
        args.input = args.input[:-5]
        print(f"Note: Stripped .html suffix from URL: {args.input}")

    if not is_opendap_url(args.input) and not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    # Load Config
    config = load_config(args.config)

    # Determine Output Path Priority:
    # 1. CLI Argument
    # 2. Config File 'output_file'
    # 3. Input Filename + .tiff (in current directory for remote URLs)
    if args.output:
        output_file = args.output
    elif config.get('output_file'):
        output_file = config.get('output_file')
    elif is_opendap_url(args.input):
        # Extract filename from the URL path and write to current directory
        url_stem = Path(urlparse(args.input).path).stem
        output_file = url_stem + '.tiff'
    else:
        output_file = str(Path(args.input).with_suffix('.tiff'))

    process_point_cloud(config, args.input, output_file)