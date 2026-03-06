#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${ENV_NAME:-napari-omero-bigfish}"
OMERO_HOST="${OMERO_HOST:-10.34.168.89}"
OMERO_PORT="${OMERO_PORT:-4064}"
CONNECT_TIMEOUT_SECONDS="${CONNECT_TIMEOUT_SECONDS:-5}"

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

check_connectivity() {
    timeout "${CONNECT_TIMEOUT_SECONDS}" bash -c "</dev/tcp/${OMERO_HOST}/${OMERO_PORT}" >/dev/null 2>&1
}

normalize_id() {
    local raw="$1"
    if [[ "${raw}" =~ ^Image:([0-9]+)$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi
    if [[ "${raw}" =~ ^[0-9]+$ ]]; then
        echo "${raw}"
        return 0
    fi
    return 1
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

echo "OMERO endpoint default: ${OMERO_HOST}:${OMERO_PORT}"

if ! check_connectivity; then
    echo "Cannot reach ${OMERO_HOST}:${OMERO_PORT}. Check VPN/network/firewall and retry." >&2
    exit 1
fi

requested_id="${1:-}"

while true; do
    if [[ -z "${requested_id}" ]]; then
        read -r -p "Enter OMERO image ID (e.g. 12345 or Image:12345, q to quit): " requested_id
    fi

    if [[ "${requested_id}" == "q" || "${requested_id}" == "Q" ]]; then
        echo "Exiting."
        exit 0
    fi

    if ! image_id="$(normalize_id "${requested_id}")"; then
        echo "Invalid format. Enter a numeric ID or Image:<ID>."
        requested_id=""
        continue
    fi

    echo "Launching napari with Image:${image_id}."
    echo "You will be prompted for OMERO username and password if needed."
    echo "Before running napari-bigfish, verify image scale (nm/px)."

    if "${MANAGER}" run -n "${ENV_NAME}" omero -s "${OMERO_HOST}" -p "${OMERO_PORT}" napari view "Image:${image_id}"; then
        exit 0
    fi

    echo "Failed to open Image:${image_id}. This can be invalid ID, auth failure, or connectivity issue."
    requested_id=""
done
