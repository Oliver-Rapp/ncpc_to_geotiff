{ pkgs ? import <nixpkgs> {} }:

let
  # Define the python version
  python = pkgs.python3;

  # We let Nix handle the heavy lifting for packages that require C-compilation
  # This prevents "library not found" errors common with pip on NixOS
  pythonPackages = python.withPackages (ps: with ps; [
    # Core logic dependencies
    numpy
    xarray
    netcdf4
    rasterio
    pyyaml
    dask
    
    # Tooling for VSCodium
    black     # Formatter
    pylint    # Linter
    ipykernel # If you want to use Interactive Windows/Notebooks
  ]);

in pkgs.mkShell {
  name = "nc-geotiff-env";

  buildInputs = [
    pythonPackages
    # System libraries required for runtime linking
    pkgs.gdal
    pkgs.netcdf
    pkgs.proj
  ];

  # Environment variables to help GDAL/Rasterio find map projections
  GDAL_DATA = "${pkgs.gdal}/share/gdal";
  PROJ_LIB = "${pkgs.proj}/share/proj";

  shellHook = ''
    echo "------------------------------------------------"
    echo "❄️  Initializing NixOS Python Environment      ❄️"
    echo "------------------------------------------------"

    # 1. Create venv if it doesn't exist
    if [ ! -d ".venv" ]; then
      echo "Creating virtual environment in .venv..."
      # --system-site-packages is CRITICAL: 
      # It allows this venv to use the rasterio/netcdf4 installed by Nix above.
      python -m venv .venv --system-site-packages
      
      echo "Upgrading pip..."
      ./.venv/bin/pip install --upgrade pip
    fi

    # 2. Activate the environment
    source .venv/bin/activate

    echo "Environment active."
    echo "Interpreter path: $(which python)"
    echo "GDAL Version: $(gdal-config --version)"
    echo "------------------------------------------------"
  '';
}