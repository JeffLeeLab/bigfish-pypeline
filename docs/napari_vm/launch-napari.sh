#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${ENV_NAME:-napari-omero-bigfish}"
OMERO_HOST="${OMERO_HOST:-10.34.168.89}"
OMERO_PORT="${OMERO_PORT:-4064}"

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

if ! "${MANAGER}" run -n "${ENV_NAME}" python -V >/dev/null 2>&1; then
    echo "Environment ${ENV_NAME} not found. Run omero/napari_vm/env-setup.sh first." >&2
    exit 1
fi

export OMERO_HOST
export OMERO_PORT

OMERODIR_RUNTIME="$(mktemp -d)"
cleanup() {
    rm -rf "${OMERODIR_RUNTIME}"
}
trap cleanup EXIT INT TERM
export OMERODIR="${OMERODIR_RUNTIME}"

echo "Launching napari from environment ${ENV_NAME}."
echo "OMERO defaults: ${OMERO_HOST}:${OMERO_PORT}"
"${MANAGER}" run -n "${ENV_NAME}" napari "$@"
