# Brief: Streamlit Application for BigFISH Parameter Optimisation

> **Revised**: 2026-03-06 — strengthened from original brief with implementation details, edge-case handling, port allocation, code reuse strategy, and OMERO metadata extraction.
> Original brief preserved at `streamlit_minimal_brief_original.md`.

> **Review comment:** I could not find `docs/streamlit_vm/streamlit_minimal_brief_original.md` in the current workspace, so this reference may need updating or restoring.

## Summary

- Create a **Streamlit** web application to help end-users (biologists with limited coding experience) find suitable parameters for BigFISH smFISH spot-detection analysis.
- The application replicates the interactive workflow in `omero/smFISH-quantification_optimise-parameters.ipynb`, but entirely within the browser — no local software, no ImageJ, no Jupyter required.
- Application name: **`bigfish-optimise`**. Hosted at `https://<vm-host>/bigfish-optimise/`.
- Source code location: `{project_root}/streamlit/bigfish-optimise/`.
- User selects a single image (one at a time), iterates through detection parameters, visually validates results, and downloads a YAML configuration file for batch processing on a cluster.

## Implementation Plan

### 1. Environment Setup

- **Environment manager**: micromamba (preferred) on the Oracle VM, consistent with the existing napari VM pattern (see `docs/napari_vm/env-setup.sh`).
- **Base dependencies**: Derived from `pixi.toml` lock (Python 3.9.x, bigfish 0.6.2, numpy, scipy, scikit-image, omero-py, zeroc-ice).
- **Additional dependency**: `streamlit>=1.32` (and its transitive dependencies — includes Plotly).
- **No cellpose** in this environment — too heavy for the VM. Placeholder only.
- Environment name: `bigfish-optimise` (separate from `napari-omero-bigfish`).
- An `env-setup.sh` script will be provided to create/update the environment reproducibly.

> **Review comment:** I would tighten this section before implementation. In this repo the conda package name is `big-fish`, not `bigfish`, and the plan later imports `plotly` directly, so I would keep Plotly as an explicit dependency rather than rely on Streamlit to bring it in transitively. It is also worth making the setup script explicitly idempotent if it is described as "create/update".

### 2. Architecture of the Streamlit Application

#### 2.1. Project Structure

```
streamlit/
└── bigfish-optimise/
    ├── app.py                    # Streamlit entrypoint
    ├── pages/                    # (reserved for future multi-page expansion)
    ├── bigfish_processing.py     # Core bigfish pipeline functions
    ├── omero_client.py           # OMERO connection wrapper (thin adapter around src/bigfish_pypeline/omero_tools.py)
    ├── config_export.py          # YAML config generation for batch scripts
    ├── env-setup.sh              # micromamba environment setup script
    ├── bigfish-optimise.service  # systemd user service file
    ├── requirements.txt          # pip fallback dependency list
    └── README.md                 # App-specific documentation
```

> **Review comment:** The service-file description here conflicts with the later deployment section, which correctly describes a system-level service. I would keep those consistent so the deployment target is unambiguous.

#### 2.2. Sidebar (Parameter Panel)

The sidebar groups parameters into collapsible sections using `st.sidebar.expander`:

**A. OMERO Connection**
- OMERO host (default: `10.34.168.89`), port (default: `4064`)
- Username (text input), password (password input)
- Connect / Disconnect button
- Connection status indicator (green/red)
- Image ID input (text, accepting `4717` or `Image:4717` formats)
- "Load Image" button

**B. Image Upload (placeholder — not yet implemented)**
- Disabled file uploader with explanatory note: *"Local upload not yet available — images can be very large. Use OMERO."*

**C. Image Acquisition Parameters**
- `voxel_size_yx` (nm) — pre-populated from OMERO metadata if available
- `voxel_size_z` (nm) — pre-populated from OMERO metadata if available
- `ex` (excitation wavelength, nm)
- `em` (emission wavelength, nm)
- `NA` (numerical aperture)
- `RI` (refractive index)
- `microscope` — selectbox: `confocal`, `widefield`, `nipkow`

**D. Channel Selection**
- Channel dropdown selector (0-based, constrained to image's actual channel count)
- User can switch channel via dropdown and re-run the pipeline without reloading the image
- The YAML export includes whichever channel(s) the user has optimised

**E. Pre-processing**
- `bg_radius` (background subtraction disk radius, pixels, default: 5)

**F. Spot Detection — Thresholding**
- Toggle: `auto_threshold` (True/False)
- If manual: numeric input for threshold value
- Elbow plot display is triggered automatically when auto-threshold is selected

**G. Dense Region Decomposition**
- `alpha` (reference spot parameter, default: 0.5)
- `beta` (dense region detection parameter, default: 1)

**H. Subpixel Fitting**
- Toggle: `subpixel_fitting_mode` (True/False, default: False)
- *This parameter has been added to `general/batch_script/smFISH_analysis_config.yaml` and the general batch script now respects it (toggled off by default).*

**I. Clustering**
- `bf_radius` (clustering radius, nm, default: 600)
- `nb_min_spots` (minimum spots per cluster, default: 12)

**J. Batch Configuration (for YAML export only)**
- `number_of_workers` (default: 2, for YAML export)
- `input_pattern` (text, user fills in their cluster path)
- `output_dir` (text)
- `output_qc_dir` (text)

#### 2.3. Main Panel (Results & Visualisation)

The main panel uses sequential `st.header` / `st.subheader` sections. Each section is populated progressively as the pipeline runs. Long-running steps display a `st.spinner` with descriptive text.

**Section 1 — Image Info**
- Image name, OMERO ID, dimensions (Z, C, Y, X), dtype
- Channel names (if available from OMERO metadata)

**Section 2 — RNA MIP (Maximum Intensity Projection)**
- 2D MIP of the selected RNA channel, displayed with `st.image` or `st.pyplot`
- Contrast-stretched for display

**Section 3 — LoG-Filtered Image Inspection**
- The 2D max-projection of the LoG-filtered image (`rna_log_max`), replacing the ImageJ step
- **Hover intensity display**: Use Plotly `imshow` with `hovertemplate` to show pixel intensity under the cursor. Plotly is a transitive dependency of Streamlit — no extra install needed.
- **Intensity histogram**: A histogram of `rna_log_max` intensity values, with the current threshold (manual or auto) marked as a vertical line. Helps users pick manual threshold values without needing ImageJ.

**Section 4 — Pre-detection / Thresholding Results**
- Number of spots detected
- Threshold value used (auto or manual)
- Elbow plot (if auto-threshold) via `st.pyplot`
- Spots overlaid on RNA MIP via `st.pyplot` (replicating `plot.plot_detection`)

**Section 5 — Dense Region Decomposition**
- Reference spot image (via `plot.plot_reference_spot`)
- Spot count before vs. after decomposition
- Decomposed spots overlaid on RNA MIP

**Section 6 — Subpixel Fitting (optional)**
- If enabled: overlay of pixel-fitted (red) vs. subpixel-fitted (blue) spots on RNA MIP
- Spot count confirmation

**Section 7 — Clustering**
- Spots + cluster outlines overlaid on RNA MIP
- Total spot count, cluster count, spots-in-clusters count

**Section 8 — Summary & Export**
- Summary table: total spots, clusters, threshold used, all parameter values
- **Download YAML** button — generates a YAML matching `general/batch_script/smFISH_analysis_config.yaml` schema
- The exported YAML includes all parameters the user tuned, plus placeholder fields for `input_pattern`, `output_dir`, `output_qc_dir` that the user fills in before running the batch script

**Section 9 — Cell Segmentation (placeholder)**
- Greyed-out / disabled section with note: *"Cellpose segmentation is not available on this VM. Run segmentation as part of the batch pipeline on a more powerful machine."*

#### 2.4. Pipeline Execution Strategy

- Each pipeline stage is triggered by a **"Run" button** or runs when upstream parameters change and the user clicks "Run Analysis".
- Intermediate results are stored in **`st.session_state`** so the user can re-run downstream steps without re-computing upstream ones (e.g., changing threshold doesn't re-run LoG filtering).
- **Cache keys**: session state entries are keyed by `(image_id, channel, parameter_hash)` to invalidate correctly when parameters change.

> **Review comment:** This is a good goal, but it needs a more explicit implementation strategy. As written, it is easy to end up with a single `Run Analysis` block that still recomputes everything and only shows results for the run that just happened. If downstream reuse matters, I would define the stage boundaries and invalidation rules a bit more concretely here.

#### 2.5. OMERO Metadata Extraction

OMERO stores pixel sizes in its `Pixels` object:
```python
pixels = img.getPrimaryPixels()
psize = pixels.getPhysicalSizeX()  # returns omero.model.LengthI or None
if psize is not None:
    voxel_size_yx = psize.getValue()  # in the unit stored (usually µm)
    unit = str(psize.getUnit())       # e.g. "MICROMETER"
    # convert to nm if needed
psize_z = pixels.getPhysicalSizeZ()
```
- If metadata is present, pre-populate sidebar fields and show a note: *"Voxel sizes read from OMERO metadata."*
- If absent, fields default to empty and must be filled manually before running analysis.

### 3. Code Reuse

- **`src/bigfish_pypeline/omero_tools.py`** already provides `connect_to_omero()` and `get_omero_image()`. The Streamlit app should import and reuse these directly rather than duplicating the logic. The app's `omero_client.py` will be a thin wrapper adapting the session-state / Streamlit UI around these functions.
- **`calculate_psf()`** and **`subtract_background()`** have been refactored into `src/bigfish_pypeline/image_utils.py` as shared utilities. All batch scripts and the Streamlit app import from there. No more duplication.

### 4. Outputs & User Takeaway

- The user iterates parameters, cross-referencing visual outputs in the main panel.
- When satisfied, they click **"Download Configuration YAML"** which produces a file matching the `smFISH_analysis_config.yaml` schema.
- The downloaded YAML is placed alongside the batch script (`smFISH_data_analysis_multiprocess.py`) on the analysis cluster.
- The YAML export **includes `subpixel_fitting_mode`** — the general batch script now supports this field (toggled off by default), consistent with the HCRv3 batch script.

> **Review comment:** There is still a channel-scope ambiguity. The brief says users can switch channels and the export should contain whichever channel(s) they optimised, but the current batch schema is still shaped around `smFISH_ch1` / `smFISH_ch2`. I would make the supported channel model explicit so the UI and export behaviour do not drift apart.

### 5. Image Fetching

1. **OMERO (default)**: Connect via ICE (omero-py + zeroc-ice) to `10.34.168.89:4064`.
   - User enters credentials in the sidebar.
   - Connection status displayed prominently.
   - `omero_tools.connect_to_omero()` handles keepalive threading and cleanup.
   - Image loaded via `omero_tools.get_omero_image()` into `st.session_state`.
2. **Local upload (placeholder)**: Disabled with explanatory text. Do not implement yet.

> **Review comment:** Pulling the full OMERO image into `st.session_state` is probably the biggest operational risk in the brief. For large `ZCYX` datasets on a 16 GB VM, memory pressure will come from loading all channels up front and from multiple concurrent user sessions. A metadata-first or single-channel fetch path would be safer if that is feasible.

### 6. Hosting on University VM

#### 6.1. Port Allocation

- The existing `/probedesign/` Streamlit app already occupies port **8501**.
- **`bigfish-optimise` uses port **8502** (confirmed).
- Bind to `127.0.0.1:8502` (localhost only, nginx handles external access).

#### 6.2. Nginx Configuration

Following the probedesign deployment pattern, add to `/etc/nginx/conf.d/streamlit_apps.conf` (upstream definition):

```nginx
# In the upstream block (http context, not inside a server block)
upstream bigfish_optimise {
    server 127.0.0.1:8502;
}
```

Then add location blocks inside IT's existing HTTPS server block in `shiny.conf`, **before** the `location /` catch-all:

```nginx
# ── BigFISH Optimise Streamlit ────────────────────────────
location = /bigfish-optimise {
    return 301 /bigfish-optimise/;
}

location /bigfish-optimise/ {
    proxy_pass         http://bigfish_optimise;
    proxy_http_version 1.1;
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection "upgrade";
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;
}
```

SELinux must allow nginx to proxy:
```bash
sudo setsebool -P httpd_can_network_connect on
```

**Streamlit must be started with `--server.baseUrlPath=/bigfish-optimise`** to ensure correct routing of static assets and websocket connections behind the reverse proxy.

#### 6.3. Systemd System Service

Following the probedesign deployment pattern (system-level service, not user service):

```ini
[Unit]
Description=BigFISH Optimise Streamlit Web App
After=network.target

[Service]
Type=simple
User=jeff
Group=jeff

ExecStart=/home/jeff/micromamba/envs/bigfish-optimise/bin/streamlit run \
    /home/jeff/Github/bigfish-pypeline/streamlit/bigfish-optimise/app.py \
    --server.port 8502 \
    --server.address 127.0.0.1 \
    --server.baseUrlPath /bigfish-optimise \
    --server.headless true \
    --browser.gatherUsageStats false

Restart=on-failure
RestartSec=5

Environment="PATH=/home/jeff/micromamba/envs/bigfish-optimise/bin:/usr/local/bin:/usr/bin:/bin"
Environment="HOME=/home/jeff"

LimitNOFILE=65536

StandardOutput=journal
StandardError=journal
SyslogIdentifier=bigfish-optimise

[Install]
WantedBy=multi-user.target
```

SELinux label for micromamba binaries (required on Oracle Linux 9):
```bash
sudo semanage fcontext -a -t bin_t "/home/jeff/micromamba(/.*)?" 
sudo restorecon -Rv /home/jeff/micromamba/
```

Enable with:
```bash
sudo systemctl daemon-reload
sudo systemctl enable bigfish-optimise
sudo systemctl start bigfish-optimise
```

#### 6.4. Co-existence Checklist

- [ ] Port 8502 is not in use by any other service on the VM
- [ ] nginx config does not conflict with `/probedesign/`, `/napari/`, or Shiny (`/`)
- [ ] `httpd_can_network_connect` SELinux boolean is on
- [ ] micromamba binaries labelled `bin_t` for SELinux
- [ ] Firewall allows internal network access to the VM on port 443 (nginx HTTPS)

### 7. Edge Cases & Error Handling

| Scenario | Handling |
|---|---|
| Invalid image ID | Catch `omero.gateway` returning `None`, show `st.error("Image ID not found.")` |
| OMERO server unreachable | Catch `ConnectionError` from `connect_to_omero()`, show `st.error` with retry guidance |
| OMERO credentials wrong | Catch connection failure, show `st.error("Authentication failed.")` |
| Browser closed mid-session | Streamlit server continues; session state is garbage-collected after timeout. OMERO connection is cleaned up by the `atexit` handler and keepalive thread timeout. Credentials are per page-refresh (cleared on refresh). |
| Large image OOM risk | VM has 16 GB RAM / 4 CPUs. Display image dimensions immediately after load. Warn if total array size exceeds ~8 GB (half of available RAM). Consider `st.warning` and optional downsampling in future. |
| Zero spots detected | Show `st.warning("No spots detected. Try lowering the threshold.")` and skip downstream steps gracefully. |
| Decomposition returns empty | Handle `np.concatenate` on empty arrays; show warning. |
| Missing voxel metadata in OMERO | Fields left blank; user must fill them; "Run Analysis" button disabled until populated. |

> **Review comment:** I would be careful about treating `atexit` as the browser-session cleanup mechanism. A browser refresh clears the Streamlit session, but it does not guarantee the underlying OMERO connection is closed immediately. This is worth calling out explicitly if repeated refreshes or stale connections are a concern.

### 8. Validation Plan & Acceptance Criteria

#### Environment Validation
- [ ] `micromamba activate bigfish-optimise` succeeds
- [ ] `python -c "import streamlit; import bigfish; import omero"` exits 0
- [ ] `streamlit run app.py --server.headless=true` starts without errors

> **Review comment:** For scripted validation I would use `micromamba run -n bigfish-optimise ...` rather than `micromamba activate ...`, since activation depends on shell initialisation and is easier to get wrong in automation.

#### Functional Acceptance Criteria
- [ ] User can connect to OMERO and see connection status
- [ ] User can load an image by ID and see its metadata
- [ ] Voxel sizes are auto-populated from OMERO metadata when available
- [ ] RNA MIP is displayed correctly for selected channel
- [ ] LoG image shows hover-intensity with Plotly and intensity histogram
- [ ] Auto-threshold produces elbow plot and correct spot count
- [ ] Manual threshold produces correct spot count
- [ ] Reference spot image is displayed
- [ ] Decomposition runs and shows before/after spot counts
- [ ] Subpixel fitting toggle works and shows overlay when enabled
- [ ] Clustering produces correct cluster count and overlay
- [ ] Downloaded YAML is valid and parseable by `smFISH_data_analysis_multiprocess.py`
- [ ] App is accessible at `https://<vm-host>/bigfish-optimise/`
- [ ] App auto-starts after VM reboot
- [ ] App does not interfere with `/probedesign/`, `/napari/`, or Shiny apps

#### Performance Acceptance
- [ ] A typical image (e.g., 30 z-slices × 4 channels × 2048 × 2048 uint16) loads in <30 seconds
- [ ] LoG filtering completes in <60 seconds
- [ ] Full pipeline (load → cluster) completes in <5 minutes for a typical image

## General Instructions

### Coding Practice

- Suggest workflow improvements (e.g., order of operations) and ask before changing.
- Code must be reproducible, maintainable, and production-ready.
- Identify and flag redundant, inefficient, or ambiguous scripts for discussion.
- Implement the validation plan and acceptance criteria above.
- Handle edge cases listed in Section 7.
- Use `st.session_state` idiomatically to avoid unnecessary recomputation.
- All matplotlib figures rendered to Streamlit must use `plt.close()` after `st.pyplot()` to prevent memory leaks.

## Resolved Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Port | **8502** |
| 2 | Multi-channel | Switch via dropdown; re-runs pipeline for selected channel |
| 3 | YAML export format | General smFISH format only |
| 4 | VM resources | 16 GB RAM, 4 CPUs (Oracle Linux 9.6) |
| 5 | Probedesign reference | System-level systemd service at `/etc/systemd/system/probedesign.service`; nginx upstream in `streamlit_apps.conf`; location blocks in IT's `shiny.conf` |
| 6 | Utility refactor | Done — `calculate_psf()` and `subtract_background()` moved to `src/bigfish_pypeline/image_utils.py` |
| 7 | `subpixel_fitting_mode` | Added to general batch config and script (default: False) |
| 8 | Streamlit version | `>=1.32` |
| 9 | Auth scope | Per page-refresh — credentials cleared on browser refresh |
