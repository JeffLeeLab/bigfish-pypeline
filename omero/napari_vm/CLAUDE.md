# napari + OMERO + bigfish environment configuration
# Initialized: March 6, 2026

# Environment manager hierarchy
environment_manager:
  primary: micromamba
  fallback:
    - mamba
    - conda
  reason: "micromamba is lightweight, fast, and ideal for isolated scientific environments"

# Python environment specification
python_environment:
  name: napari-omero-bigfish
  python_version: "3.11"
  description: "Browser-hosted napari with OMERO image-ID loading and napari-bigfish analysis plugins"

# Core dependencies
packages:
  core:
    - napari
    - napari-omero
    - napari-bigfish
    - omero-py
    - zeroc-ice
  
  runtime:
    - qt-main
    - python-dotenv
  
  optional:
    - jupyter
    - matplotlib

# Environment activation context
activation:
  scope: local
  directory: omero/napari_vm
  use_file: env-setup.sh

# OMERO client configuration (populated at runtime)
omero:
  client_only: true
  requires_credentials: true
  supports: "Image:<ID> loading via napari-omero plugin"

# Napari GUI runtime
napari:
  delivery_method: "noVNC browser streaming"
  display: ":1 (VNC server)"
  port: 6080
  endpoint: "https://<vm-host>/napari/"

# Metadata and version constraints
metadata:
  scope: proof_of_concept
  target_date: "2026-03-05"
  max_concurrent_sessions: 1
  tested_os: macos
  deployment_target: linux_vm
