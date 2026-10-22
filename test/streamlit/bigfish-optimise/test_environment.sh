#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${ENV_NAME:-bigfish-optimise}"

cd "$(dirname "$0")/../../.."

if ! command -v conda &>/dev/null; then
    echo "ERROR: conda not found. Install Miniforge: https://conda-forge.org/download/" >&2
    exit 1
fi

echo "=== Environment smoke test ==="
conda run --no-capture-output -n "${ENV_NAME}" python - <<'PY'
import bigfish
import bigfish.detection
import bigfish.plot
import bigfish.stack
import numpy
import omero.gateway
import plotly
import scipy
import streamlit
import yaml

print("All imports OK")
print(f"streamlit {streamlit.__version__}")
print(f"bigfish   {bigfish.__version__}")
print(f"numpy     {numpy.__version__}")
print(f"scipy     {scipy.__version__}")
PY

conda run -n "${ENV_NAME}" python -m pytest test/streamlit/bigfish-optimise/tests -q

echo "=== PASS ==="