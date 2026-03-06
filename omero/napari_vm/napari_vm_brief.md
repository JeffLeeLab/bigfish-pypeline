# POC Plan: Browser-Hosted Napari + OMERO Image-ID Loading + napari-bigfish

## Summary
- `napari` is a Python desktop image viewer: it renders N-dimensional data as layers and extends behavior through plugins.
- Yes, users can load an OMERO image by image ID in napari, but this is done via `napari-omero` (not `napari-bigfish`).
- Chosen architecture: run napari on the VM and expose it in browser via noVNC (desktop streaming), then run `napari-bigfish` inside that session.

## Direct answers
### How napari works
- Desktop Qt app (`python -m napari`) with a layer model (`Image`, `Labels`, `Points`, etc.) and plugin extension points.

### Can a user specify OMERO image ID and do simple analysis
- Yes. Supported forms include `omero://Image:<ID>` and CLI `omero napari view Image:<ID>`.
- Then run `napari-bigfish` widgets for spot detection/counting on the loaded layer.
- Inference: `napari-bigfish` focuses on analysis UI and expects image scale metadata; OMERO connectivity is provided by `napari-omero`.

## Public interfaces and operational contracts
- Browser endpoint: `https://<vm-host>/napari/` (noVNC session).
- Runtime environment name: `napari-omero-bigfish` (Python 3.11).
- Environment manager policy: create isolated Python environments with `micromamba`, `conda`, or `mamba` (preferred over system Python).
- OMERO load interfaces:
  - CLI: `omero napari view Image:<ID>`
  - URL: `omero://Image:<ID>` (and webclient URL forms)
- User auth model: per-user OMERO credentials entered in napari plugin dialog.
- Analysis contract: users set or verify image scale in napari before `napari-bigfish` spot analysis.

## Implementation plan
### 1) Provision VM GUI streaming stack (POC, single concurrent session)
- Install and configure a lightweight desktop session on the VM.
- Run VNC server bound to localhost display `:1`.
- Run noVNC/websockify bound to localhost port (example `6080`) and reverse-proxy via existing HTTPS nginx at `/napari/`.
- Restrict access to university network/VPN and existing VM auth controls.

### 2) Create isolated Python environment for compatibility
- Pin to Python `3.11` (compatible overlap for `napari-bigfish` + `napari-omero` in this POC).
- Use `micromamba`/`conda`/`mamba` to create and manage the isolated environment.
- Install core packages in env: `napari`, Qt backend, `napari-omero`, `napari-bigfish`.
- Validate plugin registration and startup with `napari --info` and one GUI launch in VNC session.

### 2.1) OMERO dependency inspection (no local OMERO server install)
- Verify target architecture where the VM is only a client:
  - `napari` does not natively read OMERO by ID.
  - OMERO reading in napari requires the `napari-omero` plugin.
  - Client libraries are required in the env (`omero-py` and `zeroc-ice`/ICE runtime via dependencies).
- Clarify server requirement:
  - OMERO server does not need to be installed on the VM for this workflow.
  - VM must have network reachability to the existing OMERO server endpoint(s) and valid user credentials.
- Connectivity checks:
  - Confirm OMERO host and port(s) used by your deployment (commonly `4064` for OMERO.blitz).
  - Confirm any required OMERO web links/URLs used for plugin-based loading in your setup.
  - Validate firewall/VPN rules allow ICE client-server communication from VM to OMERO server.

### 3) Configure OMERO connectivity defaults
- Set OMERO host/server in plugin settings or startup profile.
- Keep authentication per-user (no shared credentials in config files).
- Add two launcher shortcuts in VM desktop:
  - `Napari`
  - `Napari + OMERO ID prompt` (wrapper script calling `omero napari view Image:<ID>`)

### 4) Define user workflow for simple analysis (POC SOP)
1. Open browser and navigate to `/napari/`.
2. Launch napari in the streamed desktop session.
3. Load OMERO image via ID (`Image:<ID>` URL/CLI path).
4. Verify layer and set scale (nm) as required by `napari-bigfish`.
5. Run spot detection widget with default parameters.
6. Review detected points and save screenshot/result layer export.

### 5) Document limits and guardrails
- For large OMERO images, plugin operations may force full array realization and become slow or memory-heavy.
- POC guardrail: start with moderate image size and single channel first.
- If performance is poor, add ROI/cropping-first workflow before analysis.

## Test cases and scenarios
### Environment smoke test
- Napari launches in noVNC browser session without crash.

### OMERO connectivity test
- Per-user login succeeds with expected permissions.
- Confirm workflow succeeds when OMERO server is remote (no local OMERO server installed on VM).
- Confirm required plugin/client stack is present (`napari-omero`, `omero-py`, ICE dependencies).

### Image-ID loading test
- Valid ID loads (`Image:<known_id>`).
- Invalid ID returns clear error.

### Analysis test
- `napari-bigfish` spot detection runs on loaded OMERO image and creates expected result layer.

### Metadata and scale test
- Missing/incorrect scale triggers a detectable warning or mandatory workflow check before analysis.

### Performance test (POC threshold)
- Known medium image completes load plus basic spot detection within agreed time budget.

## Assumptions and defaults
- Scope is Proof of Concept (not production multi-user hardening).
- Browser delivery uses noVNC desktop streaming, not native web napari.
- OMERO server is reachable from VM network and users have OMERO accounts.
- OMERO server runs remotely; VM acts as client-only runtime.
- One active analysis session at a time is acceptable for POC.
- Default version anchor date: March 5, 2026.

## Existing local assets to reuse
- OMERO helper functions: `src/bigfish_pypeline/omero_tools.py`
- Existing OMERO image-ID loading pattern: `omero/smFISH-quantification_optimise-parameters.ipynb`

## References
- napari homepage: https://napari.org/
- napari plugins overview: https://napari.org/stable/plugins/index.html
- napari-omero README: https://github.com/tlambert03/napari-omero
- napari hub: napari-omero compatibility metadata: https://napari-hub.org/plugins/napari-omero
- napari-bigfish repository: https://github.com/MontpellierRessourcesImagerie/napari-bigfish/
- napari-bigfish docs: https://montpellierressourcesimagerie.github.io/napari-bigfish/
- napari hub: napari-bigfish compatibility metadata: https://napari-hub.org/plugins/napari-bigfish.html
- noVNC project: https://novnc.com/info.html
