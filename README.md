# NetCDF Point Cloud to GeoTIFF Converter

A memory-efficient Python utility designed to transform CF-compliant NetCDF point clouds (including high-density hyperspectral data) into georeferenced GeoTIFF rasters. This tool is optimized for large datasets and features a flexible configuration system to generate Orthophotos, Digital Surface Models (DSM), or False Color composites.

## 🚀 Features

- **Memory Efficient:** Uses a chunk-based "accumulator" approach to process massive point clouds without loading the entire dataset into RAM.
- **Strict No-Interpolation:** Points are binned into pixels. Empty pixels are kept transparent (`NODATA`), ensuring raw data integrity for visualization.
- **Universal Variable Support:** Handles both 1D variables (e.g., `red`, `Z`) and 2D hyperspectral variables (e.g., `intensity` across multiple bands).
- **CF-Compliant:** Automatically extracts CRS (Coordinate Reference System) metadata from NetCDF global and variable attributes.
- **YAML Configuration:** Define resolution, aggregation methods (`mean`, `min`, `max`, `count`), and spectral band selection in a clean config file.
- **NixOS Ready:** Includes a `shell.nix` for instant, reproducible environment setup on NixOS or any system with Nix.

## 🛠 Installation (NixOS)

On NixOS, dependencies like GDAL and NetCDF are handled via the provided `shell.nix` to avoid library-linkage issues common with `pip`.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/nc-pointcloud-to-geotiff.git
   cd nc-pointcloud-to-geotiff
   ```

2. **Enter the Nix Shell:**
   ```bash
   nix-shell
   ```
   *This will automatically create a `.venv` with access to system-level GDAL/NetCDF bindings and Python packages.*

3. **Open VSCodium (Optional):**
   ```bash
   codium .
   ```
   *Select the interpreter located at `./.venv/bin/python`.*

## 📖 Configuration (`config.yaml`)

The tool is driven by `config.yaml`. You can define multiple output profiles here.

| Option | Description |
| :--- | :--- |
| `grid.resolution` | Pixel size in CRS units (e.g., `0.5` for 50cm pixels in UTM). |
| `grid.bounds_strategy` | `rounded` to align pixels to whole coordinates, or `exact`. |
| `processing.chunk_size` | Number of points to process per iteration (adjust based on RAM). |
| `output_bands` | A list defining the Red, Green, and Blue channels of the GeoTIFF. |
| `band_selection` | (Optional) The specific wavelength (nm) to extract from 2D hyperspectral arrays. |
| `method` | Aggregation logic: `mean`, `min`, `max`, or `count`. |
| `nodata_val` | Value for empty pixels (Default: `-9999`). |

## 💻 Usage

The script requires an input file via the CLI. Output and config paths are optional.

### Basic Usage
```bash
python nc_to_geotiff.py -i input_cloud.nc
```
*Uses default `config.yaml` and saves to `input_cloud.tif`.*

### Advanced Usage
Specify a custom output name and a specific configuration file (e.g., for Snow Grain analysis):
```bash
python nc_to_geotiff.py -i flight_data.nc -c configs/snow_profile.yaml -o snow_map.tif
```

## 🌈 Visualization Examples

### 1. False Color Infrared (CIR)
Mapping NIR to Red, Red to Green, and Green to Blue. Perfect for detecting vegetation.
```yaml
output_bands:
  - {variable: "intensity", band_selection: 850.9, method: "mean"}
  - {variable: "intensity", band_selection: 650.1, method: "mean"}
  - {variable: "intensity", band_selection: 551.3, method: "mean"}
```

### 2. Snow Grain / Ice Texture
Designed for rocky/snowy surfaces to highlight grain size and ice density.
```yaml
output_bands:
  - {variable: "intensity", band_selection: 994.3, method: "mean"}
  - {variable: "intensity", band_selection: 850.9, method: "mean"}
  - {variable: "intensity", band_selection: 551.3, method: "mean"}
```

### 3. Digital Surface Model (DSM)
```yaml
output_bands:
  - {variable: "Z", method: "max", nodata_val: -9999}
```

