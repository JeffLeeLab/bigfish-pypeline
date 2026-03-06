# Feature Spec: Browser-Hosted Napari + OMERO Image-ID Loading + napari-bigfish

## Goal
Deliver a proof-of-concept (POC) where users open a browser, launch napari on a VM, load an OMERO image by ID, and run napari-bigfish spot detection without local installs.

## Scope
Included:
- Lightweight VM desktop + VNC + noVNC/websockify.
- HTTPS route `https://<vm-host>/napari/` via existing nginx.
- Isolated Python 3.11 environment `napari-omero-bigfish` managed by micromamba (fallback mamba/conda).
- Installed stack: `napari`, `napari-omero`, `napari-bigfish`, `omero-py`, `zeroc-ice`, Qt backend.
- OMERO image loading by ID (`Image:<ID>`) from launcher and plugin flow.
- Per-user interactive authentication only (no stored credentials).
- Desktop shortcuts for plain napari and OMERO ID prompt launcher.
- SOP document for workflow: open -> load -> scale check -> detect -> export.

Excluded:
- Multi-user concurrency beyond single active session.
- Production-grade hardening, quotas, autoscaling, HA.
- Installing or administering an OMERO server on this VM.
- New napari plugin development.
- CI/CD automation.

## Fixed Requirements
- Napari launches inside noVNC at `https://<vm-host>/napari/`.
- OMERO host default is fixed to `10.34.168.89:4064`.
- User is prompted for username/password at load time.
- Credentials are never written to persistent disk.
- Valid `Image:<ID>` loads as a napari layer.
- Invalid `Image:<ID>` produces clear non-crashing feedback.
- `napari-bigfish` runs on loaded OMERO layer and creates a `Points` layer.
- Scale must be verified/set before running analysis.
- VNC listens on localhost only; external access only through nginx over HTTPS and campus/VPN controls.

## Architecture
Browser -> nginx `/napari/` -> noVNC/websockify (`127.0.0.1:16080`) -> VNC (`127.0.0.1:5921`, display `:21`) -> lightweight X session -> napari in conda env.

OMERO is remote and client-only from the VM:
- OMERO server: `10.34.168.89:4064`.
- Client libraries in env: `omero-py` + ICE runtime.
- No local OMERO server components installed.

## Deliverables (Implementation Artifacts)
- `omero/napari_vm/env-setup.sh`
  - Creates/updates env `napari-omero-bigfish`.
  - Installs pinned package set and records `napari --info`.
- `omero/napari_vm/launch-napari.sh`
  - Launches plain napari in the target env.
- `omero/napari_vm/launch-napari-omero.sh`
  - Prompts for image ID, forces OMERO host/port defaults, launches `omero napari view Image:<ID>`.
  - Uses ephemeral OMERO config dir to avoid credential persistence.
- `omero/napari_vm/napari-vnc.service`
  - Starts VNC and noVNC stack bound to localhost.
- `omero/napari_vm/NGINX_SNIPPET.md`
  - Site-specific `/napari/` reverse proxy snippet and notes.
- `omero/napari_vm/SOP.md`
  - User-facing workflow and troubleshooting.

## Implementation Details

### 1) Provision desktop + VNC/noVNC
Reference package set (adjust to distro):

```bash
sudo apt-get update
sudo apt-get install -y xfce4 xfce4-terminal tigervnc-standalone-server novnc websockify nginx
```

VNC requirements:
- Display `:1`.
- Bind localhost only.
- Disable external direct VNC access.

Example VNC command contract:

```bash
vncserver :1 -localhost yes -geometry 1920x1080 -SecurityTypes None
```

noVNC/websockify contract:

```bash
websockify --web=/usr/share/novnc/ 127.0.0.1:16080 127.0.0.1:5921
```

### 2) nginx reverse proxy (`/napari/`)
Required behavior:
- HTTP upgrade for WebSocket.
- Proxy target `http://127.0.0.1:16080/`.
- Preserve host headers.
- Restrict to university network/VPN policy already used on VM.

Reference location block:

```nginx
location /napari/ {
  proxy_pass http://127.0.0.1:16080/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;
}
```

### 3) Python environment (`env-setup.sh`)
Script responsibilities:
- Detect manager priority: `micromamba` -> `mamba` -> `conda`.
- Create env with Python 3.11.
- Install dependencies from conda-forge when available.
- Install plugins via pip if needed.
- Run smoke checks and emit diagnostics.

Package contract:
- Base: `python=3.11`, `napari`, `pyqt`, `omero-py`, `zeroc-ice`, `python-dotenv`, `pip`.
- Plugin layer: `napari-omero`, `napari-bigfish`.
- Optional: `jupyter`, `matplotlib`.

Required smoke checks in script:

```bash
micromamba run -n napari-omero-bigfish python -c "import napari, omero"
micromamba run -n napari-omero-bigfish napari --info
micromamba run -n napari-omero-bigfish python -m pip check
```

### 4) Launcher behavior
`launch-napari.sh`:
- Activates env and runs `napari`.
- Exports defaults:
  - `OMERO_HOST=10.34.168.89`
  - `OMERO_PORT=4064`

`launch-napari-omero.sh`:
- Prompts for numeric image ID.
- Performs fast connectivity check to `10.34.168.89:4064` with timeout.
- Creates ephemeral runtime directory (example `OMERODIR=$(mktemp -d)`), trap-cleaned on exit.
- Runs `omero -s "$OMERO_HOST" -p "$OMERO_PORT" napari view "Image:${ID}"`.
- If launch fails (invalid ID/network/auth), prints clear error and re-prompts.
- Prints mandatory scale reminder before analysis.

Credential handling contract:
- No username/password in script args.
- No credential files in repo.
- No persistent OMERO session cache after launcher exits.

### 5) Service contract (`napari-vnc.service`)
Service responsibilities:
- Start VNC on a reserved high display (default `:21`) bound to localhost.
- Start noVNC bridge on localhost `16080`.
- Restart on failure.

Implementation options:
- Single service calling a helper script that starts both processes.
- Or split into two units (`napari-vnc.service`, `napari-novnc.service`) with dependency.

Minimum unit properties:
- `After=network.target`
- `Restart=on-failure`
- `User=<vm-user>`
- No privileged network bind required.
- Reduced contention settings for shared VM (`Nice`, `CPUQuota`, lightweight session default).

### 6) Desktop launchers
Create two `.desktop` entries (or equivalent shortcuts):
- `Napari` -> `launch-napari.sh`
- `Napari + OMERO ID prompt` -> `launch-napari-omero.sh`

Both must run inside the `napari-omero-bigfish` env.

### 7) SOP workflow (`SOP.md`)
Required SOP steps:
1. Open `https://<vm-host>/napari/`.
2. Launch `Napari + OMERO ID prompt`.
3. Enter `Image:<ID>` value when prompted.
4. Enter OMERO username/password when prompted.
5. Verify scale (nm/px) in layer metadata before analysis.
6. Open napari-bigfish widget and run spot detection.
7. Review generated `Points` layer.
8. Export result layer and/or screenshot.

Required troubleshooting sections:
- Invalid image ID.
- Authentication failures.
- OMERO server unreachable.
- Missing scale metadata.
- Large-image memory pressure and ROI-first strategy.

### 8) Performance baseline
Record in SOP appendix:
- Reference image ID.
- Load time.
- Basic detection runtime.
- Peak memory estimate (`/usr/bin/time -v` or `ps`).
- Notes on acceptable POC threshold.

## Edge Case Handling
- Invalid `Image:<ID>`:
  - Launcher loop catches non-zero exit and re-prompts.
- OMERO unavailable/firewalled:
  - Connectivity precheck with timeout and explicit error message.
- Browser closed mid-session:
  - VNC session remains; document cleanup command.
- Large image OOM risk:
  - SOP requires channel selection/ROI-first before full analysis.
- Missing scale metadata:
  - Launcher and SOP include mandatory warning prior to bigfish run.
- Plugin compatibility drift:
  - Pin versions in setup script and verify using `napari --info`.

## Validation Plan

### Automated/command checks
- Environment smoke test:

```bash
micromamba run -n napari-omero-bigfish napari --info
```

- OMERO login prompt behavior:

```bash
micromamba run -n napari-omero-bigfish omero login -s 10.34.168.89 -p 4064
```

- Dependency integrity:

```bash
micromamba run -n napari-omero-bigfish python -m pip check
```

- Shell lint:

```bash
shellcheck omero/napari_vm/*.sh
```

### Manual checks
- Browser access test on university network/VPN:
  - Open `https://<vm-host>/napari/` and verify responsive desktop.
- VNC exposure test:
  - Confirm `5921` and `16080` are localhost-only.
- Functional flow test:
  - Valid ID loads layer, invalid ID fails clearly, bigfish generates `Points` layer.
- Scale compliance test:
  - Analyst confirms and records scale before running spot detection.

## Acceptance Criteria
- [ ] Napari launches in noVNC at `https://<vm-host>/napari/` without crash.
- [ ] OMERO server defaults to `10.34.168.89:4064` without user typing host/port.
- [ ] User is interactively prompted for OMERO credentials and valid login succeeds.
- [ ] Valid `Image:<ID>` loads as napari image layer.
- [ ] Invalid `Image:<ID>` returns clear, non-crashing message.
- [ ] napari-bigfish spot detection runs and creates a `Points` layer.
- [ ] Scale can be inspected/set before analysis, with explicit workflow check.
- [ ] VNC is localhost-only; external access is HTTPS nginx path with network restrictions.
- [ ] No OMERO credentials persist to disk after session end.
- [ ] Medium reference image completes load + basic detection within agreed POC budget.
- [ ] SOP exists and covers full workflow plus troubleshooting.

## Traceability Matrix
- AC1, AC8 -> Sections 1, 2, 5, Validation manual checks.
- AC2, AC3, AC4, AC5 -> Sections 4, 7, Validation OMERO tests.
- AC6, AC7 -> Sections 7, Edge cases, functional manual checks.
- AC9 -> Section 4 credential handling contract.
- AC10 -> Section 8 performance baseline.
- AC11 -> Section 7 SOP deliverable.
