# Feature Spec: Browser-Hosted Napari + OMERO Image-ID Loading + napari-bigfish

## Goal
Deliver a proof-of-concept (POC) that lets users open a browser, load an OMERO image by ID in napari, and run napari-bigfish spot detection — all without installing anything locally. The VM streams a napari desktop session via noVNC so any lab member with browser access and OMERO credentials can perform basic smFISH spot analysis.

## Scope
Included:
- VM-side lightweight desktop environment with VNC server and noVNC/websockify.
- HTTPS reverse-proxy route (`/napari/`) via existing nginx.
- Isolated Python 3.11 environment (`napari-omero-bigfish`) managed by micromamba/conda/mamba.
- `napari`, `napari-omero`, `napari-bigfish`, `omero-py`, and ICE client dependencies installed in the environment.
- OMERO image loading by ID (`Image:<ID>` URL or CLI).
- Per-user OMERO authentication (no shared/stored credentials).
- Desktop launcher shortcuts for napari (plain) and napari + OMERO ID prompt.
- POC user SOP documentation covering load → scale check → spot detection → result export.

Excluded:
- Multi-user concurrent session support (single session only for POC).
- Production hardening, session management, or user-quota enforcement.
- Installing or administering an OMERO server on the VM (client-only).
- Custom napari plugin development beyond using existing `napari-bigfish` widgets.
- Large/tiled image streaming optimisation.
- Automated CI/CD pipeline for the VM environment.

## Requirements
- Napari must launch inside a noVNC-streamed desktop visible at `https://<vm-host>/napari/`.
- Users must be able to load an OMERO image by specifying `Image:<ID>` (via CLI wrapper or plugin dialog).
- `napari-bigfish` spot-detection widget must be functional on a loaded OMERO image layer.
- Image scale (nm) must be verifiable/settable before analysis runs.
- OMERO credentials must never be persisted in config files; authentication is per-user, per-session.
- OMERO server host is fixed at `10.34.168.89:4064`; this value must be pre-configured as the default in the launcher/environment so users never need to enter it manually.
- When loading an image, the user must be prompted to enter their OMERO username and password; credentials are not pre-filled or stored.
- VM must have network connectivity to `10.34.168.89` on port 4064 (OMERO blitz).
- Access to the noVNC endpoint must be restricted to university network / VPN and existing VM auth controls.

## Constraints
- Stack: Linux VM, Xfce/LXDE (or similar lightweight DE), TigerVNC/x11vnc, noVNC + websockify, nginx reverse proxy.
- Libraries allowed: `napari`, `napari-omero`, `napari-bigfish`, `omero-py`, `zeroc-ice`, Qt backend (`qt-main` or `pyqt5`), `python-dotenv` (runtime config). Optional: `jupyter`, `matplotlib`.
- Environment manager: micromamba preferred; fallback to mamba → conda.
- Python version: 3.11 (compatibility overlap for napari-bigfish + napari-omero as of March 2026).
- Performance/security constraints:
  - One active analysis session at a time (POC).
  - OMERO server address (`10.34.168.89:4064`) is set in config/env; username and password are entered interactively at image-load time and never written to disk.
  - VNC server bound to localhost only; external access exclusively through HTTPS reverse proxy.
  - Start with moderate image sizes and single-channel data; add ROI/crop-first workflow if performance is poor.
- Coding conventions: Shell scripts for environment setup (`env-setup.sh`); reuse helpers from `src/bigfish_pypeline/omero_tools.py` and patterns from `omero/smFISH-quantification_optimise-parameters.ipynb` where applicable.

## Interfaces
- API:
  - OMERO blitz client connection (ICE) to `10.34.168.89:4064` — consumed, not exposed.
  - No new REST/HTTP APIs; noVNC is the only browser-facing endpoint.
- Components:
  1. **VNC server** — headless X session on display `:1`.
  2. **noVNC/websockify** — WebSocket-to-VNC bridge on localhost port (e.g., 6080).
  3. **nginx location block** — `/napari/` reverse-proxying to websockify.
  4. **Python environment** — `napari-omero-bigfish` (micromamba env, Python 3.11).
  5. **Desktop launchers** — `Napari` and `Napari + OMERO ID prompt` (.desktop files or shell wrappers).
- Data model:
  - No persistent data store. Analysis results are ephemeral per-session (screenshot / layer export by user).
  - OMERO images remain on the remote OMERO server; only pixel data fetched into memory for the session.
- File changes expected:
  - `omero/napari_vm/env-setup.sh` — environment creation and package installation script.
  - `omero/napari_vm/launch-napari.sh` — napari launch wrapper (plain).
  - `omero/napari_vm/launch-napari-omero.sh` — napari + OMERO ID prompt wrapper.
  - `omero/napari_vm/napari-vnc.service` (or equivalent) — systemd unit / supervisord config for VNC + noVNC.
  - Nginx config snippet for `/napari/` location block (site-specific, documented but not committed).

## Edge Cases
- Invalid OMERO image ID → napari-omero must surface a clear error; wrapper script should catch and re-prompt.
- OMERO server unreachable (network/firewall) → connection attempt must time out with an informative message, not hang.
- User closes browser mid-session → VNC session persists on VM; document manual cleanup or idle-timeout policy.
- Large image loaded without ROI → potential OOM; document guardrail (start small, crop first) and consider adding a memory-limit reminder in the launcher script.
- Missing or incorrect image scale metadata → napari-bigfish results will be unreliable; SOP must mandate scale verification step before analysis.
- Plugin version incompatibility between napari-omero and napari-bigfish → pin compatible versions in environment spec and validate with `napari --info`.

## Acceptance Criteria
- [ ] `napari` launches without crash in a noVNC browser session at `https://<vm-host>/napari/`.
- [ ] OMERO host is pre-set to `10.34.168.89:4064`; users are not required to type the server address.
- [ ] When loading an image, the user is prompted to enter their OMERO username and password; login succeeds with valid credentials.
- [ ] Loading a valid `Image:<ID>` displays the image as a napari layer.
- [ ] Loading an invalid `Image:<ID>` returns a clear, non-crashing error message.
- [ ] `napari-bigfish` spot-detection widget runs on a loaded OMERO image and produces a Points layer of detected spots.
- [ ] Image scale can be inspected and set before analysis; missing scale triggers a visible warning or mandatory check.
- [ ] VNC server is bound to localhost only; browser access is restricted through HTTPS nginx proxy and university network/VPN.
- [ ] No OMERO credentials are persisted to disk after the session ends.
- [ ] A known medium-sized image completes load + basic spot detection within an agreed time budget (define during POC testing).
- [ ] POC SOP document exists covering the full user workflow (browser → napari → OMERO load → scale check → spot detection → export).

## Task Breakdown
1. **Provision desktop + VNC**: Install lightweight DE, TigerVNC server, bind to localhost display `:1`.
2. **Deploy noVNC/websockify**: Install noVNC, configure websockify to bridge VNC, set up as a service.
3. **Configure nginx reverse proxy**: Add `/napari/` location block proxying WebSocket traffic to websockify.
4. **Create Python environment**: Write `env-setup.sh` — create `napari-omero-bigfish` env with micromamba, install all packages, pin versions.
5. **Validate OMERO client connectivity**: Confirm ICE client ↔ `10.34.168.89:4064` communication; pre-configure host in launcher env; test `omero login` (username + password prompt) from env.
6. **Verify plugin registration**: Run `napari --info`, confirm `napari-omero` and `napari-bigfish` are listed.
7. **Build launcher scripts**: Create `launch-napari.sh` and `launch-napari-omero.sh` (ID prompt wrapper), add desktop shortcuts.
8. **End-to-end smoke test**: Browser → noVNC → napari → OMERO login → load image → spot detection → export result.
9. **Write POC SOP**: Document the user workflow, known limits, and troubleshooting steps.
10. **Performance baseline**: Record load + analysis time for a reference image; note memory usage.

## Validation
- Tests:
  - Environment smoke test — napari launches in VNC session (`napari --info` exits 0, GUI renders).
  - OMERO connectivity test — `omero login -s 10.34.168.89 -p 4064` prompts for username/password, succeeds with valid credentials, fails gracefully with invalid ones.
  - Image-ID loading test — valid ID loads a layer; invalid ID returns an error without crash.
  - Analysis test — `napari-bigfish` spot detection produces a non-empty Points layer on a test image.
  - Scale/metadata test — missing scale triggers warning or mandatory check.
- Lint/type-check:
  - Shell scripts pass `shellcheck`.
  - Python environment resolves without dependency conflicts (`micromamba install --dry-run`).
- Manual checks:
  - Open `https://<vm-host>/napari/` from a browser on university network — napari desktop is visible and responsive.
  - Confirm VNC port is not externally accessible (port scan from outside localhost).
  - Walk through full SOP end-to-end with a lab member unfamiliar with the setup.
