{ pkgs ? import <nixpkgs> {} }:

let
  pythonPackages = pkgs.python3Packages;
in pkgs.mkShell {
  name = "nc-pointcloud-env";

  buildInputs = [
    # System libraries (often needed for rasterio/netcdf under the hood)
    pkgs.gdal
    pkgs.netcdf
    
    # Python environment
    (pythonPackages.python.withPackages (ps: with ps; [
      numpy
      xarray
      netcdf4
      rasterio
      pyyaml
      dask
    ]))
  ];

  shellHook = ''
    echo "Environment loaded for NetCDF to GeoTIFF conversion."
    echo "Python version: $(python --version)"
    echo "GDAL version: $(gdal-config --version)"
  '';
}
