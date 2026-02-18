# NetCDF Point Cloud to GeoTIFF Converter

A memory-efficient Python utility designed to transform CF-compliant NetCDF point clouds into georeferenced GeoTIFF rasters. This tool is optimized for large datasets and features a flexible configuration system to generate Orthophotos, Digital Surface Models (DSM), or Hyperspectral composites.

## 🚀 Features

- **Memory Efficient:** Uses a chunk-based "accumulator" approach to process massive point clouds without loading the entire dataset into RAM.
- **Universal Variable Support:** Handles 1D variables (e.g., `red`, `Z`) and 2D hyperspectral variables (e.g., `intensity` with specific band selection).
- **Georeferencing** Automatically extracts CRS (Coordinate Reference System) metadata from NetCDF attributes.
- **YAML Configuration:** Easily switch between RGB, DSM, and Hyperspectral profiles without touching the code.

## 💻 Usage

The script requires an input file via the CLI. Output and config paths are optional.

```bash
# Minimal usage (saves to {input_filename}.tif)
python nc_to_geotiff.py -i flight_data.nc

# Full control
python nc_to_geotiff.py -i flight_data.nc -c my_config.yaml -o result.tif
```

## 🌈 Configuration Examples

Edit your `config.yaml` to switch between these visualization styles.

### 1. Standard RGB Orthophoto
Uses the dedicated `red`, `green`, and `blue` variables from the sensor.
```yaml
output_bands:
  - {variable: "red", method: "mean", nodata_val: -9999}
  - {variable: "green", method: "mean", nodata_val: -9999}
  - {variable: "blue", method: "mean", nodata_val: -9999}
```

### 2. Hyperspectral False Color
Uses the `intensity` variable. This specific example creates a false color image by mapping NIR to Red and Mid-Infrared to Green.
```yaml
output_bands:
  - {variable: "intensity", band_selection: 994.3, method: "mean", nodata_val: -9999}
  - {variable: "intensity", band_selection: 850.9, method: "mean", nodata_val: -9999}
  - {variable: "intensity", band_selection: 551.3, method: "mean", nodata_val: -9999}
```

### 3. Digital Surface Model (DSM)
Uses the `Z` variable. The `max` method is used to ensure the "highest" point (e.g., top of a rock or building) defines the pixel value.
```yaml
output_bands:
  - {variable: "Z", method: "max", nodata_val: -9999}
```

## 📖 Global Settings

| Option | Description |
| :--- | :--- |
| `grid.resolution` | Pixel size in CRS units (e.g., `0.5` for 50cm pixels). |
| `grid.bounds_strategy` | `rounded` to snap to integer coordinates, or `exact`. |
| `processing.chunk_size` | Number of points to process per iteration (Default: `500000`). |

