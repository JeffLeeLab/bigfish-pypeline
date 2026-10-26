#!/usr/bin/env bash
set -euo pipefail

DISPLAY_NUM="${DISPLAY_NUM:-21}"
DISPLAY_MIN="${DISPLAY_MIN:-21}"
DISPLAY_MAX="${DISPLAY_MAX:-29}"
ALLOW_DISPLAY_FALLBACK="${ALLOW_DISPLAY_FALLBACK:-1}"
NOVNC_PORT="${NOVNC_PORT:-16080}"
GEOMETRY="${GEOMETRY:-1920x1080}"
NOVNC_WEB_ROOT="${NOVNC_WEB_ROOT:-/usr/share/novnc}"
WEBSOCKIFY_HEARTBEAT="${WEBSOCKIFY_HEARTBEAT:-30}"
WEBSOCKIFY_IDLE_TIMEOUT="${WEBSOCKIFY_IDLE_TIMEOUT:-0}"

need_cmd() {
    local cmd="$1"
    if ! command -v "${cmd}" >/dev/null 2>&1; then
        echo "Missing required command: ${cmd}" >&2
        return 1
    fi
}

ensure_xstartup() {
    mkdir -p "${HOME}/.vnc"
    cat >"${HOME}/.vnc/xstartup" <<'EOF'
#!/usr/bin/env bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
session_mode="${PREFERRED_SESSION:-minimal}"
auto_start_napari="${AUTO_START_NAPARI:-1}"
napari_launcher="${NAPARI_LAUNCHER:-$HOME/Github/bigfish-pypeline/omero/napari_vm/launch-napari.sh}"

# Start Napari automatically in the VNC session unless explicitly disabled.
if [[ "${auto_start_napari}" == "1" ]] && [[ -x "${napari_launcher}" ]]; then
    "${napari_launcher}" >/tmp/napari-autostart.log 2>&1 &
fi

if [[ "${session_mode}" == "xfce" ]] && command -v startxfce4 >/dev/null 2>&1; then
    exec startxfce4
fi

if [[ "${session_mode}" == "gnome" ]] && command -v gnome-session >/dev/null 2>&1; then
    exec gnome-session
fi

if [[ "${session_mode}" != "minimal" ]] && command -v startxfce4 >/dev/null 2>&1; then
    exec startxfce4
fi

if [[ "${session_mode}" != "minimal" ]] && command -v gnome-session >/dev/null 2>&1; then
    exec gnome-session
fi

exec xterm -fa Monospace -fs 11 -geometry 150x40+20+20
EOF
    chmod +x "${HOME}/.vnc/xstartup"
}

display_is_busy() {
    local num="$1"
    if [[ -S "/tmp/.X11-unix/X${num}" ]]; then
        return 0
    fi
    if vncserver -list 2>/dev/null | awk '/^:[0-9]+/ {print $1}' | grep -qx ":${num}"; then
        return 0
    fi
    return 1
}

choose_display() {
    local candidate="$1"
    if ! display_is_busy "${candidate}"; then
        echo "${candidate}"
        return 0
    fi
    if [[ "${ALLOW_DISPLAY_FALLBACK}" != "1" ]]; then
        echo "Requested display :${candidate} is busy and fallback is disabled." >&2
        return 1
    fi
    local i
    for i in $(seq "${DISPLAY_MIN}" "${DISPLAY_MAX}"); do
        if ! display_is_busy "${i}"; then
            echo "${i}"
            return 0
        fi
    done
    echo "No free VNC display found in range ${DISPLAY_MIN}-${DISPLAY_MAX}." >&2
    return 1
}

cleanup() {
    vncserver -kill "${DISPLAY}" >/dev/null 2>&1 || true
}

need_cmd vncserver
need_cmd websockify
ensure_xstartup

DISPLAY_NUM="$(choose_display "${DISPLAY_NUM}")"
DISPLAY=":${DISPLAY_NUM}"
VNC_PORT="$((5900 + DISPLAY_NUM))"

if [[ ! -d "${NOVNC_WEB_ROOT}" ]]; then
    echo "noVNC web root not found at ${NOVNC_WEB_ROOT}." >&2
    echo "Set NOVNC_WEB_ROOT to your noVNC static files path." >&2
    exit 1
fi

trap cleanup EXIT INT TERM

echo "Starting VNC ${DISPLAY} on 127.0.0.1:${VNC_PORT}"
vncserver "${DISPLAY}" -localhost yes -geometry "${GEOMETRY}" -SecurityTypes None

echo "Starting noVNC on 127.0.0.1:${NOVNC_PORT}"
ws_args=(--web="${NOVNC_WEB_ROOT}")

if [[ "${WEBSOCKIFY_HEARTBEAT}" != "0" ]]; then
    ws_args+=(--heartbeat="${WEBSOCKIFY_HEARTBEAT}")
fi

if [[ "${WEBSOCKIFY_IDLE_TIMEOUT}" != "0" ]]; then
    ws_args+=(--idle-timeout="${WEBSOCKIFY_IDLE_TIMEOUT}")
fi

exec websockify "${ws_args[@]}" "127.0.0.1:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}"
