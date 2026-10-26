# Implementation Plan: `bigfish-optimise` Streamlit Application

> **Created**: 2026-03-06
> **Brief**: `test/streamlit/docs/streamlit_minimal_brief.md`
> **Target directory**: `test/streamlit/bigfish-optimise/`

---

## Table of Contents

1. [Phase 0 — Pre-implementation decisions](#phase-0--pre-implementation-decisions)
2. [Phase 1 — Environment & project scaffold](#phase-1--environment--project-scaffold)
3. [Phase 2 — Core processing module](#phase-2--core-processing-module)
4. [Phase 3 — OMERO client adapter](#phase-3--omero-client-adapter)
5. [Phase 4 — Streamlit UI — sidebar & layout](#phase-4--streamlit-ui--sidebar--layout)
6. [Phase 5 — Streamlit UI — pipeline execution & visualisation](#phase-5--streamlit-ui--pipeline-execution--visualisation)
7. [Phase 6 — YAML config export](#phase-6--yaml-config-export)
8. [Pre-deployment checkpoint — Local laptop functional test](#pre-deployment-checkpoint--local-laptop-functional-test)
9. [Phase 7 — Deployment (VM, nginx, systemd)](#phase-7--deployment-vm-nginx-systemd)
10. [Phase 8 — Testing & validation](#phase-8--testing--validation)
11. [Appendix — File-by-file specification](#appendix--file-by-file-specification)

---

## Phase 0 — Pre-implementation decisions

All questions from the brief have been resolved:

| # | Question | Decision |
|---|----------|----------|
| 1 | Port | **8502** (confirmed) |
| 2 | Multi-channel | Switch via dropdown; re-runs pipeline for selected channel |
| 3 | YAML export format | General smFISH format only |
| 4 | VM resources | **16 GB RAM, 4 CPUs** (Oracle Linux 9.6, Intel Xeon Silver 4310) |
| 5 | Refactor utilities | **Done** — `calculate_psf()` and `subtract_background()` moved to `src/bigfish_pypeline/image_utils.py` |
| 6 | `subpixel_fitting_mode` | **Done** — added to general batch config and script (default: False) |
| 7 | Streamlit version | `>=1.32` |
| 8 | OMERO auth scope | Per page-refresh — credentials cleared on browser refresh |

---

## Phase 1 — Environment & project scaffold

### Step 1.1 — Create directory structure

```bash
mkdir -p test/streamlit/bigfish-optimise/pages
```

Files to create:
```
test/streamlit/bigfish-optimise/
├── app.py
├── bigfish_processing.py
├── omero_client.py
├── config_export.py
├── environment.yml
├── bigfish-optimise.service
├── README.md
└── pages/
    └── .gitkeep
```

### Step 1.2 — `environment.yml`

The conda environment spec is `test/streamlit/bigfish-optimise/environment.yml`, created with:

```bash
conda env create -f test/streamlit/bigfish-optimise/environment.yml
```

> **Review comment:** The environment section is one of the riskier parts of the plan as written. In this repo the conda package is `big-fish` in `environment.yml`, so `bigfish=0.6.2` looks likely to fail. Also, the script says "create/update" but currently always uses `micromamba create`, which is not idempotent once the env already exists. I would also treat the pip fallback as unvalidated until it is tested end-to-end, especially for `zeroc-ice` / `omero-py`.

---

## Phase 2 — Core processing module

### Step 2.1 — `bigfish_processing.py`

This module contains the pure computation functions, with no Streamlit dependency. It can be unit-tested independently.
It imports shared utilities from `src/bigfish_pypeline/image_utils.py` rather than duplicating them.

```python
"""
bigfish_processing.py
Core image-processing pipeline for BigFISH parameter optimisation.
No Streamlit dependency — pure numpy/bigfish functions.
Imports shared utilities from the bigfish_pypeline package.
"""

import sys
import os
import numpy as np
import bigfish.stack as stack
import bigfish.detection as detection

# Ensure src/ is importable
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, os.path.join(_project_root, "src"))

from bigfish_pypeline.image_utils import calculate_psf, subtract_background


def get_spot_radius_px(voxel_size_z, voxel_size_yx, psf_z, psf_yx):
    """Convert PSF sizes to pixel units via bigfish."""
    return detection.get_object_radius_pixel(
        voxel_size_nm=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        object_radius_nm=(psf_z, psf_yx, psf_yx),
        ndim=3,
    )


def extract_channel(image_zcyx, channel_index):
    """
    Extract a single channel from a ZCYX image.
    Returns 3D array (Z, Y, X).
    """
    return image_zcyx[:, channel_index, :, :]


def background_subtract_stack(rna_zyx, bg_radius=5):
    """Apply background subtraction to each z-slice."""
    return np.array([subtract_background(z, bg_radius) for z in rna_zyx])


def log_filter_and_mip(rna_zyx, spot_radius_px):
    """
    Apply LoG filter and compute max-intensity projection of the result.
    Returns (rna_log_3d, rna_log_mip_2d).
    """
    rna_log = stack.log_filter(rna_zyx, sigma=spot_radius_px)
    rna_log_mip = np.max(rna_log, axis=0)
    return rna_log, rna_log_mip


def detect_spots_auto(rna_zyx, rna_log, spot_radius_px, voxel_size_z,
                      voxel_size_yx, psf_z, psf_yx):
    """
    Auto-threshold spot detection.
    Returns (spots, threshold, mask).
    """
    mask = detection.local_maximum_detection(rna_log, min_distance=spot_radius_px)
    threshold = detection.automated_threshold_setting(rna_log, mask)
    spots, _ = detection.spots_thresholding(rna_log, mask, threshold)
    return spots, threshold, mask


def detect_spots_manual(rna_log, spot_radius_px, threshold):
    """
    Manual-threshold spot detection.
    Returns (spots, mask).
    """
    mask = detection.local_maximum_detection(rna_log, min_distance=spot_radius_px)
    spots, _ = detection.spots_thresholding(rna_log, mask, threshold)
    return spots, mask


def build_reference_spot(rna_zyx, spots, voxel_size_z, voxel_size_yx,
                         psf_z, psf_yx, alpha=0.5):
    """
    Build reference spot from denoised image for dense-region decomposition.
    Returns (reference_spot, rna_denoised).
    """
    kernel_size = detection.get_object_radius_pixel(
        voxel_size_nm=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        object_radius_nm=(psf_z, psf_yx, psf_yx),
        ndim=3,
    )
    large_kernel_size = tuple(k * 5 for k in kernel_size)
    rna_denoised = stack.remove_background_gaussian(rna_zyx, sigma=large_kernel_size)
    ref_spot = detection.build_reference_spot(
        image=rna_denoised,
        spots=spots,
        voxel_size=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        spot_radius=(psf_z, psf_yx, psf_yx),
        alpha=alpha,
    )
    return ref_spot, rna_denoised


def decompose_dense_regions(rna_denoised, spots, reference_spot,
                            voxel_size_z, voxel_size_yx,
                            psf_z, psf_yx, beta=1):
    """
    Decompose dense regions using gaussian mixture modelling.
    Returns spots_post_decomposition (N, 3) array.
    """
    voxel = (voxel_size_z, voxel_size_yx, voxel_size_yx)
    spot_r = (psf_z, psf_yx, psf_yx)

    sigma_z, sigma_yx, amplitude, background = detection.modelize_spot(
        reference_spot=reference_spot,
        voxel_size=voxel,
        spot_radius=spot_r,
    )

    regions_to_decompose, spots_out_regions, region_size = detection.get_dense_region(
        image=rna_denoised,
        spots=spots,
        voxel_size=voxel,
        spot_radius=spot_r,
        beta=beta,
    )

    max_grid = max(200, region_size + 1)
    precomputed_gaussian = detection.precompute_erf(
        ndim=3,
        voxel_size=voxel,
        sigma=(sigma_z, sigma_yx, sigma_yx),
        max_grid=max_grid,
    )

    spots_in_regions, _ = detection.simulate_gaussian_mixture(
        image=rna_denoised,
        candidate_regions=regions_to_decompose,
        voxel_size=voxel,
        sigma=(sigma_z, sigma_yx, sigma_yx),
        amplitude=amplitude,
        background=background,
        precomputed_gaussian=precomputed_gaussian,
    )

    if len(spots_in_regions) > 0:
        spots_post = np.concatenate(
            (spots_out_regions, spots_in_regions[:, :3]), axis=0
        )
    else:
        spots_post = spots_out_regions

    return spots_post


def fit_subpixel(rna_zyx, spots, voxel_size_z, voxel_size_yx,
                 psf_z, psf_yx):
    """Optional subpixel fitting."""
    return detection.fit_subpixel(
        image=rna_zyx,
        spots=spots,
        voxel_size=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        spot_radius=(psf_z, psf_yx, psf_yx),
    )


def detect_clusters(spots, voxel_size_z, voxel_size_yx, radius=600,
                    nb_min_spots=12):
    """
    Cluster post-decomposition spots.
    Returns (spots_post_clustering, clusters).
    """
    return detection.detect_clusters(
        spots=spots,
        voxel_size=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        radius=radius,
        nb_min_spots=nb_min_spots,
    )
```

> **Review comment:** Repeating `sys.path.insert(...)` inside app modules will work, but it is a brittle packaging pattern for a deployed service. I would prefer one import strategy at the process boundary instead, for example an installed package, a fixed `PYTHONPATH`, or a working directory convention, so the modules themselves stay import-clean and easier to test.

---

## Phase 3 — OMERO client adapter

### Step 3.1 — `omero_client.py`

Thin wrapper around `src/bigfish_pypeline/omero_tools.py` that adapts it for Streamlit's session-state model.

```python
"""
omero_client.py
OMERO connection management for Streamlit.
Wraps src/bigfish_pypeline/omero_tools to manage connection in st.session_state.
"""

import sys
import os

# Ensure src/ is importable
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, os.path.join(_project_root, "src"))

from bigfish_pypeline.omero_tools import connect_to_omero, get_omero_image


def omero_connect(username, password, host="10.34.168.89", port=4064):
    """
    Establish OMERO connection. Returns BlitzGateway or raises.
    Intended to be called once and stored in st.session_state["omero_conn"].
    """
    conn = connect_to_omero(
        username=username,
        host=host,
        port=port,
        password=password,
        secure=True,
    )
    return conn


def omero_load_image(conn, image_id, order="ZCYX"):
    """
    Fetch image from OMERO. Returns (numpy_array, image_name).
    Also extracts voxel metadata if available.
    """
    image_id_clean = str(image_id).replace("Image:", "").strip()
    img_obj = conn.getObject("Image", image_id_clean)
    if img_obj is None:
        raise ValueError(f"Image ID '{image_id}' not found on OMERO server.")

    arr, name = get_omero_image(conn, image_id_clean, order=order)

    # Extract voxel metadata
    metadata = {}
    pixels = img_obj.getPrimaryPixels()

    psize_x = pixels.getPhysicalSizeX()
    if psize_x is not None:
        val = psize_x.getValue()
        unit = str(psize_x.getUnit())
        # Convert to nanometres if stored in micrometres
        if "MICRO" in unit.upper():
            val *= 1000.0
        metadata["voxel_size_yx"] = round(val, 2)

    psize_z = pixels.getPhysicalSizeZ()
    if psize_z is not None:
        val = psize_z.getValue()
        unit = str(psize_z.getUnit())
        if "MICRO" in unit.upper():
            val *= 1000.0
        metadata["voxel_size_z"] = round(val, 2)

    # Channel names
    channels = [ch.getName() for ch in img_obj.getChannels()]
    metadata["channel_names"] = channels
    metadata["size_z"] = int(img_obj.getSizeZ())
    metadata["size_c"] = int(img_obj.getSizeC())
    metadata["size_y"] = int(img_obj.getSizeY())
    metadata["size_x"] = int(img_obj.getSizeX())

    return arr, name, metadata


def omero_disconnect(conn):
    """Gracefully close OMERO connection."""
    try:
        conn.close()
    except Exception:
        pass
```

> **Review comment:** This adapter still loads the full `ZCYX` array before the user picks a working channel. On a 16 GB VM, that is likely the dominant memory risk, especially if more than one user session is active. I would explicitly decide whether the app fetches metadata first and then only the selected channel, or whether the deployment is intentionally single-user / low-concurrency.

---

## Phase 4 — Streamlit UI — sidebar & layout

### Step 4.1 — `app.py` skeleton

```python
"""
app.py — BigFISH Parameter Optimisation
Streamlit entrypoint.
"""

import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go

from omero_client import omero_connect, omero_load_image, omero_disconnect
from bigfish_processing import (
    calculate_psf,
    get_spot_radius_px,
    extract_channel,
    background_subtract_stack,
    log_filter_and_mip,
    detect_spots_auto,
    detect_spots_manual,
    build_reference_spot,
    decompose_dense_regions,
    fit_subpixel,
    detect_clusters,
)
from config_export import generate_yaml
import bigfish.stack as stack
import bigfish.plot as plot

# ──────────────────────────────────────────
# Page configuration
# ──────────────────────────────────────────
st.set_page_config(
    page_title="BigFISH Optimise",
    page_icon="🐟",
    layout="wide",
)

st.title("BigFISH Parameter Optimisation")
st.caption("Interactive smFISH spot-detection parameter tuning")

# ──────────────────────────────────────────
# Session state initialisation
# ──────────────────────────────────────────
DEFAULTS = {
    "omero_conn": None,
    "omero_connected": False,
    "image_arr": None,
    "image_name": None,
    "image_metadata": None,
    "rna": None,
    "rna_mip": None,
    "rna_log": None,
    "rna_log_mip": None,
    "spots": None,
    "threshold_used": None,
    "reference_spot": None,
    "rna_denoised": None,
    "spots_post_decomposition": None,
    "spots_subpixel": None,
    "spots_post_clustering": None,
    "clusters": None,
}
for key, default in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ──────────────────────────────────────────
# Helper: invalidate downstream results
# ──────────────────────────────────────────
def invalidate_from(stage):
    """Clear session state from a given pipeline stage onward."""
    stages_order = [
        "rna", "rna_mip", "rna_log", "rna_log_mip",
        "spots", "threshold_used",
        "reference_spot", "rna_denoised",
        "spots_post_decomposition",
        "spots_subpixel",
        "spots_post_clustering", "clusters",
    ]
    if stage in stages_order:
        idx = stages_order.index(stage)
        for s in stages_order[idx:]:
            st.session_state[s] = None


# ──────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────
with st.sidebar:
    # --- A. OMERO Connection ---
    st.header("OMERO Connection")
    omero_host = st.text_input("Host", value="10.34.168.89")
    omero_port = st.number_input("Port", value=4064, step=1)
    omero_user = st.text_input("Username")
    omero_pass = st.text_input("Password", type="password")

    col_conn, col_disconn = st.columns(2)
    with col_conn:
        if st.button("Connect", disabled=st.session_state.omero_connected):
            try:
                conn = omero_connect(omero_user, omero_pass, omero_host, int(omero_port))
                st.session_state.omero_conn = conn
                st.session_state.omero_connected = True
                st.success("Connected")
            except Exception as e:
                st.error(f"Connection failed: {e}")
    with col_disconn:
        if st.button("Disconnect", disabled=not st.session_state.omero_connected):
            omero_disconnect(st.session_state.omero_conn)
            st.session_state.omero_conn = None
            st.session_state.omero_connected = False
            st.info("Disconnected")

    if st.session_state.omero_connected:
        st.success("🟢 Connected to OMERO")
    else:
        st.warning("🔴 Not connected")

    st.divider()

    # --- Image ID ---
    image_id = st.text_input("Image ID", placeholder="e.g. 4717")
    if st.button("Load Image", disabled=not st.session_state.omero_connected):
        if not image_id.strip():
            st.error("Enter an image ID.")
        else:
            try:
                with st.spinner("Fetching image from OMERO..."):
                    arr, name, meta = omero_load_image(
                        st.session_state.omero_conn, image_id
                    )
                    # OOM guard (VM has 16 GB RAM)
                    size_bytes = arr.nbytes
                    if size_bytes > 8 * 1024**3:
                        st.warning(
                            f"Image is {size_bytes / 1024**3:.1f} GB. "
                            "This may cause memory issues on the VM (16 GB RAM)."
                        )
                    st.session_state.image_arr = arr
                    st.session_state.image_name = name
                    st.session_state.image_metadata = meta
                    invalidate_from("rna")
                    st.success(f"Loaded: {name}")
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Failed to load image: {e}")

    # --- B. Image upload placeholder ---
    st.divider()
    with st.expander("📁 Upload image (not implemented)", expanded=False):
        st.info(
            "Local upload not yet available — images can be very large "
            "and browser-based transfer could be unstable. Use OMERO."
        )

    st.divider()

    # --- C. Image Acquisition Parameters ---
    st.header("Acquisition Parameters")
    meta = st.session_state.image_metadata or {}

    voxel_size_yx = st.number_input(
        "voxel_size_yx (nm)", value=meta.get("voxel_size_yx", 65),
        min_value=1, step=1
    )
    voxel_size_z = st.number_input(
        "voxel_size_z (nm)", value=meta.get("voxel_size_z", 200),
        min_value=1, step=1
    )
    if "voxel_size_yx" in meta or "voxel_size_z" in meta:
        st.caption("ℹ️ Voxel sizes read from OMERO metadata")

    ex = st.number_input("Excitation λ (nm)", value=570, min_value=1, step=1)
    em = st.number_input("Emission λ (nm)", value=610, min_value=1, step=1)
    na = st.number_input("NA", value=1.45, min_value=0.01, step=0.01, format="%.2f")
    ri = st.number_input("RI", value=1.45, min_value=0.01, step=0.01, format="%.2f")
    microscope = st.selectbox("Microscope", ["confocal", "widefield", "nipkow"])

    st.divider()

    # --- D. Channel ---
    st.header("Channel Selection")
    max_ch = meta.get("size_c", 4)
    ch_names = meta.get("channel_names", [])
    ch_options = [f"{i}: {ch_names[i]}" if i < len(ch_names) else str(i) for i in range(max_ch)]
    channel_selection = st.selectbox("Channel (0-based)", ch_options, index=min(3, max_ch - 1))
    channel = int(channel_selection.split(":")[0])

    st.divider()

    # --- E. Pre-processing ---
    st.header("Pre-processing")
    bg_radius = st.number_input("bg_radius (px)", value=5, min_value=1, step=1)

    st.divider()

    # --- F. Thresholding ---
    st.header("Spot Detection")
    auto_threshold = st.toggle("Auto-threshold", value=True)
    manual_threshold = None
    if not auto_threshold:
        manual_threshold = st.number_input(
            "Manual threshold", value=8, min_value=0, step=1
        )

    st.divider()

    # --- G. Dense Region Decomposition ---
    st.header("Dense Region Decomposition")
    alpha = st.number_input("alpha", value=0.5, min_value=0.0, step=0.1, format="%.1f")
    beta = st.number_input("beta", value=1, min_value=0, step=1)

    st.divider()

    # --- H. Subpixel Fitting ---
    st.header("Subpixel Fitting")
    subpixel_fitting_mode = st.toggle("Enable subpixel fitting", value=False)

    st.divider()

    # --- I. Clustering ---
    st.header("Clustering")
    bf_radius = st.number_input("bf_radius (nm)", value=600, min_value=1, step=10)
    nb_min_spots = st.number_input("nb_min_spots", value=12, min_value=1, step=1)

    st.divider()

    # --- J. Batch export fields ---
    with st.expander("Batch config (YAML export)", expanded=False):
        num_workers = st.number_input("number_of_workers", value=2, min_value=1, step=1)
        input_pattern = st.text_input("input_pattern", placeholder="/path/to/*.tif")
        output_dir = st.text_input("output_dir", placeholder="/path/to/bf_output")
        output_qc_dir = st.text_input("output_qc_dir", placeholder="/path/to/bf_output_qc")

    st.divider()

    # --- Run button ---
    run_ready = st.session_state.image_arr is not None and voxel_size_yx > 0 and voxel_size_z > 0
    run_analysis = st.button(
        "▶ Run Analysis",
        disabled=not run_ready,
        type="primary",
        use_container_width=True,
    )

# ──────────────────────────────────────────
# MAIN PANEL — continued in Phase 5
# ──────────────────────────────────────────
# ... (see Phase 5 below)
```

> **Note on the sidebar layout**: All parameter groups are visible linearly in the sidebar. `st.expander` is used sparingly (batch config, upload placeholder) because collapsing critical parameters can confuse first-time users. The sidebar auto-scrolls on narrow viewports.

> **Review comment:** This code path silently falls back to `65` / `200` nm when OMERO voxel metadata is missing, which conflicts with the safer behaviour described in the brief. For scientific parameters like scale, implicit defaults are risky because users can run a plausible-looking but wrong analysis without noticing.

---

## Phase 5 — Streamlit UI — pipeline execution & visualisation

### Step 5.1 — Main panel sections (continued in `app.py`)

Add the following after the sidebar block:

```python
# ──────────────────────────────────────────
# MAIN PANEL
# ──────────────────────────────────────────

# Section 1 — Image Info
st.header("1. Image Information")
if st.session_state.image_arr is not None:
    meta = st.session_state.image_metadata or {}
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Image", st.session_state.image_name)
        st.text(f"Shape (ZCYX): {st.session_state.image_arr.shape}")
        st.text(f"dtype: {st.session_state.image_arr.dtype}")
    with col2:
        st.text(f"Z: {meta.get('size_z', '?')}")
        st.text(f"C: {meta.get('size_c', '?')}")
        st.text(f"Y: {meta.get('size_y', '?')}")
        st.text(f"X: {meta.get('size_x', '?')}")
        if meta.get("channel_names"):
            st.text(f"Channels: {', '.join(meta['channel_names'])}")
else:
    st.info("Load an image from OMERO to begin.")

# ----- Pipeline execution (triggered by Run Analysis) -----
if run_analysis and st.session_state.image_arr is not None:
    img = st.session_state.image_arr

    # PSF calculation
    psf_z, psf_yx = calculate_psf(voxel_size_z, voxel_size_yx, ex, em, na, ri, microscope)
    spot_radius_px = get_spot_radius_px(voxel_size_z, voxel_size_yx, psf_z, psf_yx)

    st.caption(
        f"PSF: z={psf_z:.1f} nm, yx={psf_yx:.1f} nm | "
        f"Spot radius (px): z={spot_radius_px[0]:.3f}, yx={spot_radius_px[-1]:.3f}"
    )

    # Extract channel
    rna = extract_channel(img, channel)
    rna_mip = stack.maximum_projection(rna)
    st.session_state.rna = rna
    st.session_state.rna_mip = rna_mip

    # Background subtraction
    with st.spinner("Background subtraction..."):
        rna = background_subtract_stack(rna, bg_radius)

    # LoG filter
    with st.spinner("LoG filtering..."):
        rna_log, rna_log_mip = log_filter_and_mip(rna, spot_radius_px)
        st.session_state.rna_log = rna_log
        st.session_state.rna_log_mip = rna_log_mip

    # Section 2 — RNA MIP
    st.header("2. RNA Maximum Intensity Projection")
    fig_mip, ax_mip = plt.subplots(figsize=(6, 6))
    ax_mip.imshow(rna_mip, cmap="gray")
    ax_mip.set_title(f"RNA MIP — Channel {channel}")
    ax_mip.axis("off")
    st.pyplot(fig_mip)
    plt.close(fig_mip)

    # Section 3 — LoG inspection
    st.header("3. LoG-Filtered Image Inspection")
    st.subheader("Interactive LoG MIP (hover for intensity)")

    fig_log = px.imshow(
        rna_log_mip,
        color_continuous_scale="viridis",
        labels={"color": "Intensity"},
        title="LoG-filtered MIP — hover to inspect intensity",
    )
    fig_log.update_traces(
        hovertemplate="x: %{x}<br>y: %{y}<br>intensity: %{z:.2f}<extra></extra>"
    )
    st.plotly_chart(fig_log, use_container_width=True)

    # Histogram with threshold line
    st.subheader("Intensity distribution")
    fig_hist, ax_hist = plt.subplots(figsize=(8, 3))
    values = rna_log_mip.ravel()
    ax_hist.hist(values, bins=200, color="steelblue", edgecolor="none")
    ax_hist.set_xlabel("LoG intensity")
    ax_hist.set_ylabel("Pixel count")
    ax_hist.set_title("LoG-filtered MIP intensity histogram")

    # Section 4 — Thresholding
    st.header("4. Spot Detection — Thresholding")
    with st.spinner("Detecting spots..."):
        if auto_threshold:
            spots, threshold_val, mask = detect_spots_auto(
                rna, rna_log, spot_radius_px, voxel_size_z, voxel_size_yx, psf_z, psf_yx
            )
            st.info(f"Auto-threshold value: **{threshold_val}**")
            # Show elbow plot
            st.subheader("Elbow plot")
            fig_elbow, ax_elbow = plt.subplots()
            plot.plot_elbow(
                rna,
                voxel_size=(voxel_size_z, voxel_size_yx, voxel_size_yx),
                spot_radius=(psf_z, psf_yx, psf_yx),
                show=False,
            )
            st.pyplot(plt.gcf())
            plt.close("all")
        else:
            threshold_val = manual_threshold
            spots, mask = detect_spots_manual(rna_log, spot_radius_px, threshold_val)

    # Draw threshold line on histogram
    ax_hist.axvline(threshold_val, color="red", linestyle="--", label=f"threshold = {threshold_val}")
    ax_hist.legend()
    st.pyplot(fig_hist)
    plt.close(fig_hist)

    st.session_state.spots = spots
    st.session_state.threshold_used = threshold_val

    st.metric("Spots detected (pre-decomposition)", len(spots))

    # Plot spots on MIP
    fig_det, ax_det = plt.subplots(figsize=(10, 8))
    plot.plot_detection(rna_mip, spots, radius=3, framesize=(10, 8), contrast=True, show=False)
    st.pyplot(plt.gcf())
    plt.close("all")

    if len(spots) == 0:
        st.warning("No spots detected. Try adjusting the threshold.")
        st.stop()

    # Section 5 — Dense Region Decomposition
    st.header("5. Dense Region Decomposition")
    with st.spinner("Building reference spot..."):
        ref_spot, rna_den = build_reference_spot(
            rna, spots, voxel_size_z, voxel_size_yx, psf_z, psf_yx, alpha
        )
        st.session_state.reference_spot = ref_spot
        st.session_state.rna_denoised = rna_den

    st.subheader("Reference spot")
    plot.plot_reference_spot(ref_spot, rescale=True, show=False)
    st.pyplot(plt.gcf())
    plt.close("all")

    with st.spinner("Decomposing dense regions..."):
        spots_post = decompose_dense_regions(
            rna_den, spots, ref_spot, voxel_size_z, voxel_size_yx, psf_z, psf_yx, beta
        )
        st.session_state.spots_post_decomposition = spots_post

    col_before, col_after = st.columns(2)
    col_before.metric("Spots before decomposition", len(spots))
    col_after.metric("Spots after decomposition", len(spots_post))

    plot.plot_detection(rna_mip, spots_post, framesize=(10, 8), contrast=True, show=False)
    st.pyplot(plt.gcf())
    plt.close("all")

    # Section 6 — Subpixel Fitting
    st.header("6. Subpixel Fitting")
    if subpixel_fitting_mode:
        with st.spinner("Subpixel fitting..."):
            spots_sub = fit_subpixel(rna, spots_post, voxel_size_z, voxel_size_yx, psf_z, psf_yx)
            st.session_state.spots_subpixel = spots_sub
        st.metric("Spots (subpixel fitted)", len(spots_sub))

        plot.plot_detection(
            rna_mip,
            spots=[spots_post, spots_sub],
            radius=3,
            color=["red", "blue"],
            title="Red = pixel | Blue = subpixel",
            linewidth=1, contrast=True, framesize=(10, 8), show=False,
        )
        st.pyplot(plt.gcf())
        plt.close("all")
        final_spots = spots_sub
    else:
        st.info("Subpixel fitting disabled. Using pixel-fitted spots.")
        final_spots = spots_post
        st.session_state.spots_subpixel = None

    # Section 7 — Clustering
    st.header("7. Clustering")
    with st.spinner("Detecting clusters..."):
        spots_clust, clusters = detect_clusters(
            final_spots, voxel_size_z, voxel_size_yx, bf_radius, nb_min_spots
        )
        st.session_state.spots_post_clustering = spots_clust
        st.session_state.clusters = clusters

    col_s, col_c = st.columns(2)
    col_s.metric("Total spots", len(spots_clust))
    col_c.metric("Clusters", len(clusters))

    plot.plot_detection(
        rna_mip,
        spots=[final_spots, clusters[:, :3]],
        shape=["circle", "polygon"],
        radius=[spot_radius_px[-1], bf_radius / voxel_size_yx],
        color=["orange", "cyan"],
        linewidth=[1, 2],
        fill=[False, True],
        framesize=(10, 8),
        contrast=True, show=False,
    )
    st.pyplot(plt.gcf())
    plt.close("all")

    # Section 8 — Summary & Export
    st.header("8. Summary & YAML Export")
    st.subheader("Parameter summary")
    summary = {
        "image_name": st.session_state.image_name,
        "channel": channel,
        "voxel_size_yx": voxel_size_yx,
        "voxel_size_z": voxel_size_z,
        "ex": ex, "em": em, "NA": na, "RI": ri,
        "microscope": microscope,
        "bg_radius": bg_radius,
        "auto_threshold": auto_threshold,
        "threshold_used": threshold_val,
        "alpha": alpha, "beta": beta,
        "subpixel_fitting_mode": subpixel_fitting_mode,
        "bf_radius": bf_radius,
        "nb_min_spots": nb_min_spots,
        "total_spots": len(spots_clust),
        "total_clusters": len(clusters),
    }
    st.dataframe(summary, use_container_width=True)

    yaml_content = generate_yaml(
        voxel_size_yx=voxel_size_yx, voxel_size_z=voxel_size_z,
        ex=ex, em=em, na=na, ri=ri, microscope=microscope,
        bg_radius=bg_radius, channels=[channel],
        auto_threshold=auto_threshold,
        manual_thresholds={channel: threshold_val} if not auto_threshold else {},
        alpha=alpha, beta=beta,
        subpixel_fitting_mode=subpixel_fitting_mode,
        bf_radius=bf_radius, nb_min_spots=nb_min_spots,
        number_of_workers=num_workers,
        input_pattern=input_pattern,
        output_dir=output_dir,
        output_qc_dir=output_qc_dir,
    )

    st.download_button(
        label="📥 Download Configuration YAML",
        data=yaml_content,
        file_name="smFISH_analysis_config.yaml",
        mime="text/yaml",
        type="primary",
        use_container_width=True,
    )

    # Preview
    with st.expander("Preview YAML"):
        st.code(yaml_content, language="yaml")

    # Section 9 — Cellpose placeholder
    st.header("9. Cell Segmentation")
    st.info(
        "⚠️ Cellpose segmentation is not available on this VM. "
        "Run segmentation as part of the batch pipeline on a more powerful machine."
    )
```

> **Review comment:** The current implementation does not yet deliver the caching story described earlier. Everything still runs inside one `if run_analysis` block, and the results are only rendered on the run that produced them, so `st.session_state` is not actually buying downstream re-use yet. If that behaviour matters, the plan needs a clearer stage model or cached functions keyed by validated parameters.

### Step 5.2 — Notes on matplotlib figure handling

Every `st.pyplot()` call must be followed by `plt.close()` to prevent memory leaks. The bigfish `plot.*` functions use the global matplotlib state, so `plt.gcf()` captures the figure and `plt.close("all")` cleans up.

For the Plotly LoG image (`px.imshow`), no cleanup is needed — Plotly figures are serialised to JSON and garbage-collected normally.

---

## Phase 6 — YAML config export

### Step 6.1 — `config_export.py`

```python
"""
config_export.py
Generate a YAML configuration file matching smFISH_analysis_config.yaml schema.
"""

import yaml


def generate_yaml(
    voxel_size_yx, voxel_size_z, ex, em, na, ri, microscope,
    bg_radius, channels, auto_threshold, manual_thresholds,
    alpha, beta, subpixel_fitting_mode, bf_radius, nb_min_spots,
    number_of_workers=2, input_pattern="", output_dir="", output_qc_dir="",
):
    """
    Build a YAML string matching the batch processing config schema.

    Args:
        channels: list of int, e.g. [3] or [2, 3].
        manual_thresholds: dict mapping channel index -> threshold value.
        All other args: scalar parameters.

    Returns:
        str: YAML content ready for download.
    """
    config = {
        "number_of_workers": int(number_of_workers),
        "input_pattern": input_pattern or "/path/to/images/*.tif",
        "output_dir": output_dir or "/path/to/bf_output",
        "output_qc_dir": output_qc_dir or "/path/to/bf_output_qc",
        "voxel_size_yx": int(voxel_size_yx),
        "voxel_size_z": int(voxel_size_z),
        "ex": int(ex),
        "em": int(em),
        "NA": float(na),
        "RI": float(ri),
        "microscope": microscope,
        "bg_radius": int(bg_radius),
        "channels": [int(c) for c in channels],
        "auto_threshold": bool(auto_threshold),
    }

    # Manual threshold fields (always include for schema compatibility)
    if len(channels) >= 1:
        config["smFISH_ch1"] = int(channels[0])
        config["smFISH_ch1_thresh"] = manual_thresholds.get(channels[0], 50)
    if len(channels) >= 2:
        config["smFISH_ch2"] = int(channels[1])
        config["smFISH_ch2_thresh"] = manual_thresholds.get(channels[1], 30)

    config["alpha"] = float(alpha)
    config["beta"] = int(beta)
    config["subpixel_fitting_mode"] = bool(subpixel_fitting_mode)
    config["bf_radius"] = int(bf_radius)
    config["nb_min_spots"] = int(nb_min_spots)

    # Build YAML with header comments
    header = (
        "# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #\n"
        "# YAML configuration for Bigfish batch processing\n"
        "# Generated by bigfish-optimise Streamlit app\n"
        "# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #\n\n"
    )

    return header + yaml.dump(config, default_flow_style=False, sort_keys=False)
```

> **Review comment:** There is still a requirements mismatch around channels. The brief says users can switch channels and export whichever channel(s) they have optimised, but the current app flow only exports the currently selected channel and the batch schema only has `smFISH_ch1` / `smFISH_ch2`. I would make that limitation explicit or add a small per-channel state model so tuned thresholds are not lost when switching channels.

---

## Pre-deployment checkpoint — Local laptop functional test

Before touching the VM-specific deployment steps, run a minimal end-to-end check on the laptop to validate that the app starts and the core workflow behaves correctly.

### Step 6.2 — Run the app locally on the laptop

From the repository root:

```bash
conda run --live-stream -n bigfish-optimise streamlit run test/streamlit/bigfish-optimise/app.py
```

This local checkpoint is intentionally limited to application functionality and should **not** go through VM-hosting steps such as nginx, systemd, SELinux, reverse-proxy configuration, or `baseUrlPath` setup.

### Step 6.3 — Minimal local functional check

On the laptop, verify only the following:

1. The Streamlit UI loads without import/runtime errors.
2. Sidebar widgets render and parameter changes trigger reruns cleanly.
3. If OMERO is reachable from the laptop network/VPN, connect and load a known image ID.
4. Run one full analysis for a single channel and confirm the main result sections render.
5. Toggle auto/manual threshold and confirm spot counts update.
6. Download YAML and confirm the file is generated with the expected fields.

If OMERO is not reachable from the laptop, still complete the UI startup check locally and defer OMERO connectivity verification to the VM validation phase below.

---

## Phase 7 — Deployment (VM, nginx, systemd)

> **Pattern reference**: matches the probedesign app deployment on the same VM.
> All services are system-level (`/etc/systemd/system/`), nginx uses upstream
> definitions in `streamlit_apps.conf`, and location blocks live inside IT's
> HTTPS `server` block in `shiny.conf`.

### Step 7.1 — SELinux prerequisites

Oracle Linux 9.6 runs SELinux in enforcing mode. Two one-time steps are
required (skip if already done for probedesign):

```bash
# Allow nginx to proxy to backend ports
sudo setsebool -P httpd_can_network_connect on

# Label micromamba binaries so systemd can execute them
sudo semanage fcontext -a -t bin_t "/home/jeff/micromamba(/.*)?"
sudo restorecon -Rv /home/jeff/micromamba/
```

### Step 7.2 — Systemd service file (system-level)

Create `/etc/systemd/system/bigfish-optimise.service`:

```ini
[Unit]
Description=BigFISH Optimise Streamlit Web App
After=network.target

[Service]
Type=simple
User=jeff
Group=jeff
ExecStart=/home/jeff/micromamba/envs/bigfish-optimise/bin/streamlit run \
    /home/jeff/Github/bigfish-pypeline/test/streamlit/bigfish-optimise/app.py \
    --server.port 8502 --server.address 127.0.0.1 \
    --server.baseUrlPath /bigfish-optimise --server.headless true
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Step 7.3 — Install & enable service

```bash
# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable bigfish-optimise.service
sudo systemctl start bigfish-optimise.service

# Verify
sudo systemctl status bigfish-optimise.service
journalctl -u bigfish-optimise.service -f   # tail logs
```

### Step 7.4 — Nginx configuration

**a) Upstream definition** — append to `/etc/nginx/conf.d/streamlit_apps.conf`
(alongside the existing `probedesign` upstream):

```nginx
upstream bigfish_optimise {
    server 127.0.0.1:8502;
}
```

**b) Location block** — add inside the IT-managed HTTPS `server` block in
`shiny.conf` (same pattern as the probedesign location):

```nginx
location /bigfish-optimise/ {
    proxy_pass http://bigfish_optimise;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400;
}
```

Then validate and reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### Step 7.5 — Streamlit config file (optional)

Create `test/streamlit/bigfish-optimise/.streamlit/config.toml`:

```toml
[server]
port = 8502
address = "127.0.0.1"
baseUrlPath = "bigfish-optimise"
headless = true

[browser]
gatherUsageStats = false
```

This provides defaults that the systemd `ExecStart` flags also set, ensuring
the app works correctly when run manually during development.

### Step 7.6 — Co-existence verification

```bash
# Verify no port conflicts
sudo ss -tlnp | grep -E '850[0-9]'
# Expected: 8501 (probedesign) and 8502 (bigfish-optimise)

# Verify both Streamlit apps respond
curl -s -o /dev/null -w "%{http_code}" https://<vm-host>/bigfish-optimise/
curl -s -o /dev/null -w "%{http_code}" https://<vm-host>/probedesign/
# Both should return 200
```

---

## Phase 8 — Testing & validation

### Step 8.1 — Environment smoke test

```bash
#!/usr/bin/env bash
# test_environment.sh
set -euo pipefail

echo "=== Environment smoke test ==="
conda run -n bigfish-optimise python -c "
import streamlit
import bigfish
import bigfish.detection
import bigfish.stack
import bigfish.plot
import omero.gateway
import numpy
import scipy
import yaml
import plotly

print('All imports OK')
print(f'  streamlit {streamlit.__version__}')
print(f'  bigfish   {bigfish.__version__}')
print(f'  numpy     {numpy.__version__}')
print(f'  scipy     {scipy.__version__}')
"
echo "=== PASS ==="
```

> **Review comment:** For automation, `micromamba activate` inside a script is usually more brittle than `micromamba run -n ...` because it depends on shell initialisation. The napari VM setup in this repo already uses `micromamba run`, which feels like the safer pattern to copy here. If unit tests are part of acceptance, `pytest` also needs to be included somewhere in the environment plan.

### Step 8.2 — Unit test for `bigfish_processing.py`

```python
# test_bigfish_processing.py
import numpy as np
from bigfish_processing import (
    calculate_psf,
    subtract_background,
    get_spot_radius_px,
    extract_channel,
    background_subtract_stack,
)


def test_calculate_psf_confocal():
    psf_z, psf_yx = calculate_psf(200, 65, 570, 610, 1.45, 1.45, "confocal")
    assert psf_z > 0
    assert psf_yx > 0
    assert psf_z > psf_yx  # z resolution is always worse


def test_calculate_psf_widefield():
    psf_z, psf_yx = calculate_psf(200, 65, 570, 610, 1.45, 1.45, "widefield")
    assert psf_z > 0
    assert psf_yx > 0


def test_calculate_psf_invalid():
    import pytest
    with pytest.raises(ValueError):
        calculate_psf(200, 65, 570, 610, 1.45, 1.45, "invalid")


def test_subtract_background():
    img = np.random.randint(0, 255, (64, 64), dtype=np.uint16)
    result = subtract_background(img, radius=5)
    assert result.shape == img.shape


def test_extract_channel():
    img = np.zeros((10, 4, 64, 64), dtype=np.uint16)  # ZCYX
    ch = extract_channel(img, 2)
    assert ch.shape == (10, 64, 64)


def test_background_subtract_stack():
    rna = np.random.randint(0, 255, (5, 64, 64), dtype=np.uint16)
    result = background_subtract_stack(rna, bg_radius=3)
    assert result.shape == rna.shape
```

### Step 8.3 — Unit test for `config_export.py`

```python
# test_config_export.py
import yaml
from config_export import generate_yaml


def test_generate_yaml_schema():
    content = generate_yaml(
        voxel_size_yx=65, voxel_size_z=200,
        ex=570, em=610, na=1.45, ri=1.45, microscope="confocal",
        bg_radius=5, channels=[3],
        auto_threshold=True, manual_thresholds={},
        alpha=0.5, beta=1, subpixel_fitting_mode=False,
        bf_radius=600, nb_min_spots=12,
    )

    # Strip header comments and parse
    lines = [l for l in content.splitlines() if not l.startswith("#")]
    cfg = yaml.safe_load("\n".join(lines))

    assert cfg["voxel_size_yx"] == 65
    assert cfg["voxel_size_z"] == 200
    assert cfg["channels"] == [3]
    assert cfg["auto_threshold"] is True
    assert cfg["microscope"] == "confocal"
    assert cfg["subpixel_fitting_mode"] is False
    assert cfg["bf_radius"] == 600
    assert cfg["nb_min_spots"] == 12


def test_yaml_manual_threshold():
    content = generate_yaml(
        voxel_size_yx=65, voxel_size_z=200,
        ex=570, em=610, na=1.45, ri=1.45, microscope="confocal",
        bg_radius=5, channels=[2, 3],
        auto_threshold=False,
        manual_thresholds={2: 50, 3: 30},
        alpha=0.5, beta=1, subpixel_fitting_mode=True,
        bf_radius=400, nb_min_spots=5,
    )

    lines = [l for l in content.splitlines() if not l.startswith("#")]
    cfg = yaml.safe_load("\n".join(lines))

    assert cfg["smFISH_ch1"] == 2
    assert cfg["smFISH_ch1_thresh"] == 50
    assert cfg["smFISH_ch2"] == 3
    assert cfg["smFISH_ch2_thresh"] == 30
    assert cfg["subpixel_fitting_mode"] is True
```

### Step 8.4 — Functional acceptance test (manual checklist)

After deployment, walk through:

1. Browse to `https://<vm-host>/bigfish-optimise/`
2. Enter OMERO credentials → confirm green connection status
3. Load a known image (e.g., ID `4717`) → confirm dimensions shown
4. Verify voxel sizes auto-populated (if metadata exists)
5. Click "Run Analysis" → confirm all 7 sections populate
6. Toggle auto/manual threshold → confirm spot count changes
7. Enable subpixel fitting → confirm red/blue overlay appears
8. Download YAML → open and verify it parses as valid YAML with expected keys
9. Close browser tab → confirm app stays up (`sudo systemctl status bigfish-optimise`)
10. Reboot VM → confirm app auto-starts (`sudo systemctl status bigfish-optimise`)

---

## Appendix — File-by-file specification

| File | Purpose | Dependencies |
|------|---------|-------------|
| `app.py` | Streamlit entrypoint; UI layout and pipeline orchestration | `streamlit`, `bigfish_processing`, `omero_client`, `config_export`, `bigfish.plot`, `bigfish.stack`, `plotly`, `matplotlib` |
| `bigfish_processing.py` | Pure computation functions; PSF, background subtraction, LoG, detection, decomposition, clustering | `numpy`, `bigfish`, `scikit-image` |
| `omero_client.py` | OMERO connection & image fetching; wraps `src/bigfish_pypeline/omero_tools.py` | `bigfish_pypeline.omero_tools` |
| `config_export.py` | Generate YAML matching batch script schema | `pyyaml` |
| `environment.yml` | Conda environment spec | conda |
| `bigfish-optimise.service` | systemd system-level service (`/etc/systemd/system/`) | systemd |
| `.streamlit/config.toml` | Streamlit server defaults | — |
| `README.md` | App documentation | — |
| `pages/.gitkeep` | Reserve multi-page structure | — |

### Dependency graph

```
app.py
  ├── omero_client.py
  │     └── src/bigfish_pypeline/omero_tools.py
  ├── bigfish_processing.py
  │     ├── bigfish.detection
  │     ├── bigfish.stack
  │     └── skimage.morphology
  ├── config_export.py
  │     └── pyyaml
  ├── bigfish.plot (for matplotlib-based QC figures)
  └── plotly (for interactive LoG inspection)
```

### Session state keys

| Key | Type | Set by | Used by |
|-----|------|--------|---------|
| `omero_conn` | `BlitzGateway \| None` | sidebar connect | image loading |
| `omero_connected` | `bool` | sidebar connect/disconnect | UI gating |
| `image_arr` | `np.ndarray (ZCYX) \| None` | image load | pipeline |
| `image_name` | `str \| None` | image load | display |
| `image_metadata` | `dict \| None` | image load | sidebar defaults |
| `rna` | `np.ndarray (ZYX) \| None` | extraction | pipeline |
| `rna_mip` | `np.ndarray (YX) \| None` | extraction | plotting |
| `rna_log` | `np.ndarray (ZYX) \| None` | LoG filter | detection |
| `rna_log_mip` | `np.ndarray (YX) \| None` | LoG filter | plotting |
| `spots` | `np.ndarray (N,3) \| None` | detection | decomposition |
| `threshold_used` | `float \| None` | detection | display, export |
| `reference_spot` | `np.ndarray \| None` | ref spot | display |
| `rna_denoised` | `np.ndarray (ZYX) \| None` | denoising | decomposition |
| `spots_post_decomposition` | `np.ndarray (N,3) \| None` | decomposition | subpixel/clustering |
| `spots_subpixel` | `np.ndarray (N,3) \| None` | subpixel | clustering |
| `spots_post_clustering` | `np.ndarray (N,4) \| None` | clustering | export |
| `clusters` | `np.ndarray (M,5) \| None` | clustering | export |
