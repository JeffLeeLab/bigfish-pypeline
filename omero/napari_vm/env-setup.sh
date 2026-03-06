#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${ENV_NAME:-napari-omero-bigfish}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
INSTALL_OPTIONAL_PACKAGES="${INSTALL_OPTIONAL_PACKAGES:-0}"
NAPARI_OMERO_SPEC="${NAPARI_OMERO_SPEC:-napari-omero}"
NAPARI_BIGFISH_SPEC="${NAPARI_BIGFISH_SPEC:-napari-bigfish}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"

detect_manager() {
    if command -v micromamba >/dev/null 2>&1; then
        echo "micromamba"
        return 0
    fi
    if [[ -x "${HOME}/.local/bin/micromamba" ]]; then
        echo "${HOME}/.local/bin/micromamba"
        return 0
    fi
    if [[ -x "${HOME}/micromamba/bin/micromamba" ]]; then
        echo "${HOME}/micromamba/bin/micromamba"
        return 0
    fi
    if command -v mamba >/dev/null 2>&1; then
        echo "mamba"
        return 0
    fi
    if command -v conda >/dev/null 2>&1; then
        echo "conda"
        return 0
    fi
    echo "No supported environment manager found (micromamba/mamba/conda)." >&2
    exit 1
}

MANAGER="$(detect_manager)"
BASE_PACKAGES=("python=${PYTHON_VERSION}" napari pyqt omero-py zeroc-ice python-dotenv pip)
OPTIONAL_PACKAGES=(jupyter matplotlib)

echo "Using environment manager: ${MANAGER}"
echo "Target environment: ${ENV_NAME}"

if "${MANAGER}" run -n "${ENV_NAME}" python -c 'import sys; print(sys.version)' >/dev/null 2>&1; then
    echo "Environment ${ENV_NAME} already exists. Updating base packages."
    "${MANAGER}" install -y -n "${ENV_NAME}" -c conda-forge "${BASE_PACKAGES[@]}"
else
    echo "Creating environment ${ENV_NAME}."
    "${MANAGER}" create -y -n "${ENV_NAME}" -c conda-forge "${BASE_PACKAGES[@]}"
fi

if [[ "${INSTALL_OPTIONAL_PACKAGES}" == "1" ]]; then
    echo "Installing optional packages."
    "${MANAGER}" install -y -n "${ENV_NAME}" -c conda-forge "${OPTIONAL_PACKAGES[@]}"
fi

echo "Installing napari plugins via pip."
"${MANAGER}" run -n "${ENV_NAME}" python -m pip install --upgrade pip
"${MANAGER}" run -n "${ENV_NAME}" python -m pip install "${NAPARI_OMERO_SPEC}" "${NAPARI_BIGFISH_SPEC}"

echo "Running smoke checks."
"${MANAGER}" run -n "${ENV_NAME}" python -c "import napari, omero"
"${MANAGER}" run -n "${ENV_NAME}" env QT_QPA_PLATFORM=offscreen napari --info | tee "${LOG_DIR}/napari-info.txt"
"${MANAGER}" run -n "${ENV_NAME}" python -m pip check | tee "${LOG_DIR}/pip-check.txt"
"${MANAGER}" run -n "${ENV_NAME}" python -m pip freeze | tee "${LOG_DIR}/pip-freeze.txt"

echo "Environment setup complete."
echo "napari --info saved to ${LOG_DIR}/napari-info.txt"