"""Streamlit entrypoint for BigFISH parameter optimisation."""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import bigfish.plot as bf_plot
import bigfish.stack as bf_stack
import matplotlib.pyplot as plt
import numpy as np
import plotly.express as px
import streamlit as st

APP_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bigfish_processing import (  # noqa: E402
    background_subtract_stack,
    build_reference_spot,
    calculate_psf,
    count_spots_in_clusters,
    decompose_dense_regions,
    detect_clusters,
    detect_spots_auto,
    detect_spots_manual,
    fit_subpixel,
    get_spot_radius_px,
    log_filter_and_mip,
)
from config_export import generate_yaml  # noqa: E402
from omero_client import (  # noqa: E402
    normalize_image_id,
    omero_connect,
    omero_disconnect,
    omero_load_channel_stack,
    omero_load_image_metadata,
)

APP_TITLE = "BigFISH Optimise"
MAX_STAGE_CACHE_ENTRIES = 6
MAX_CHANNEL_CACHE_ENTRIES = 4


def new_analysis_cache():
    return {
        "preprocess": {},
        "detection": {},
        "decomposition": {},
        "subpixel": {},
        "clustering": {},
    }


DEFAULTS = {
    "omero_conn": None,
    "omero_connected": False,
    "image_id": None,
    "image_name": None,
    "image_metadata": None,
    "channel_stack_cache": {},
    "analysis_cache": new_analysis_cache(),
    "last_run_results": None,
    "param_voxel_size_yx": "",
    "param_voxel_size_z": "",
    "param_ex": 570.0,
    "param_em": 610.0,
    "param_na": 1.45,
    "param_ri": 1.45,
    "param_microscope": "confocal",
    "param_bg_radius": 5,
    "param_auto_threshold": True,
    "param_manual_threshold": 8.0,
    "param_alpha": 0.5,
    "param_beta": 1,
    "param_subpixel_fitting_mode": False,
    "param_bf_radius": 600,
    "param_nb_min_spots": 12,
    "export_number_of_workers": 2,
    "export_input_pattern": "",
    "export_output_dir": "",
    "export_output_qc_dir": "",
    "saved_channels": {},
}

for state_key, default_value in DEFAULTS.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = default_value


def format_optional_number(value):
    if value is None:
        return ""
    formatted = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return formatted


def parse_positive_float(raw_value, label):
    text_value = str(raw_value).strip()
    if not text_value:
        return None, f"{label} is required."
    try:
        numeric_value = float(text_value)
    except ValueError:
        return None, f"{label} must be a number."
    if numeric_value <= 0:
        return None, f"{label} must be greater than zero."
    return numeric_value, None


def hash_payload(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def trim_cache(cache, max_entries):
    while len(cache) > max_entries:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key)


def reset_analysis_state(clear_saved_channels=True):
    st.session_state["channel_stack_cache"] = {}
    st.session_state["analysis_cache"] = new_analysis_cache()
    st.session_state["last_run_results"] = None
    if clear_saved_channels:
        st.session_state["saved_channels"] = {}


def clear_connection_state():
    reset_analysis_state(clear_saved_channels=True)
    st.session_state["image_id"] = None
    st.session_state["image_name"] = None
    st.session_state["image_metadata"] = None
    st.session_state["param_voxel_size_yx"] = ""
    st.session_state["param_voxel_size_z"] = ""


def get_cached_stage_result(stage_name, cache_key, spinner_label, compute_func):
    stage_cache = st.session_state["analysis_cache"][stage_name]
    if cache_key in stage_cache:
        return stage_cache[cache_key]

    with st.spinner(spinner_label):
        stage_result = compute_func()

    stage_cache[cache_key] = stage_result
    trim_cache(stage_cache, MAX_STAGE_CACHE_ENTRIES)
    return stage_result


def get_channel_stack(image_id, channel_index):
    cache_key = f"{image_id}:{channel_index}"
    channel_cache = st.session_state["channel_stack_cache"]
    if cache_key in channel_cache:
        return channel_cache[cache_key]

    with st.spinner("Loading the selected channel from OMERO..."):
        channel_stack, _ = omero_load_channel_stack(
            st.session_state["omero_conn"],
            image_id,
            channel_index,
        )

    channel_cache[cache_key] = channel_stack
    trim_cache(channel_cache, MAX_CHANNEL_CACHE_ENTRIES)
    return channel_stack


def image_size_text(estimated_bytes):
    if estimated_bytes is None:
        return "Unknown"
    gibibytes = estimated_bytes / (1024 ** 3)
    return f"{gibibytes:.2f} GiB"


def stretch_for_display(image_2d):
    if image_2d.size == 0:
        return image_2d
    low, high = np.percentile(image_2d, [1, 99])
    if high <= low:
        return image_2d
    return np.clip((image_2d - low) / (high - low), 0, 1)


def show_matplotlib_figure(figure):
    st.pyplot(figure, use_container_width=True)
    plt.close(figure)


def render_bigfish_plot(plotter, *args, **kwargs):
    plotter(*args, **kwargs, show=False)
    figure = plt.gcf()
    show_matplotlib_figure(figure)


def build_channel_options(image_metadata):
    channel_names = image_metadata.get("channel_names", [])
    options = []
    for channel_index in range(image_metadata.get("size_c", 0)):
        label = channel_names[channel_index] if channel_index < len(channel_names) else f"Channel {channel_index}"
        options.append(f"{channel_index}: {label}")
    return options or ["0: Channel 0"]


def extract_channel_index(channel_option):
    return int(str(channel_option).split(":", 1)[0])


def build_export_settings(context):
    return {
        "voxel_size_yx": context["voxel_size_yx"],
        "voxel_size_z": context["voxel_size_z"],
        "ex": context["ex"],
        "em": context["em"],
        "na": context["na"],
        "ri": context["ri"],
        "microscope": context["microscope"],
        "bg_radius": context["bg_radius"],
        "auto_threshold": context["auto_threshold"],
        "alpha": context["alpha"],
        "beta": context["beta"],
        "subpixel_fitting_mode": context["subpixel_fitting_mode"],
        "bf_radius": context["bf_radius"],
        "nb_min_spots": context["nb_min_spots"],
    }


def build_analysis_context(channel_index):
    voxel_size_yx, voxel_yx_error = parse_positive_float(st.session_state["param_voxel_size_yx"], "voxel_size_yx")
    voxel_size_z, voxel_z_error = parse_positive_float(st.session_state["param_voxel_size_z"], "voxel_size_z")

    errors = [error for error in (voxel_yx_error, voxel_z_error) if error]
    if not st.session_state["param_auto_threshold"] and st.session_state["param_manual_threshold"] < 0:
        errors.append("Manual threshold must be zero or greater.")

    context = {
        "image_id": st.session_state["image_id"],
        "image_name": st.session_state["image_name"],
        "channel": int(channel_index),
        "voxel_size_yx": voxel_size_yx,
        "voxel_size_z": voxel_size_z,
        "ex": float(st.session_state["param_ex"]),
        "em": float(st.session_state["param_em"]),
        "na": float(st.session_state["param_na"]),
        "ri": float(st.session_state["param_ri"]),
        "microscope": st.session_state["param_microscope"],
        "bg_radius": int(st.session_state["param_bg_radius"]),
        "auto_threshold": bool(st.session_state["param_auto_threshold"]),
        "manual_threshold": float(st.session_state["param_manual_threshold"]),
        "alpha": float(st.session_state["param_alpha"]),
        "beta": int(st.session_state["param_beta"]),
        "subpixel_fitting_mode": bool(st.session_state["param_subpixel_fitting_mode"]),
        "bf_radius": float(st.session_state["param_bf_radius"]),
        "nb_min_spots": int(st.session_state["param_nb_min_spots"]),
    }
    analysis_signature_payload = {
        key: value
        for key, value in context.items()
        if key not in {"image_name"}
    }
    context["analysis_signature"] = hash_payload(analysis_signature_payload)
    context["export_settings"] = build_export_settings(context)
    context["export_settings_signature"] = hash_payload(context["export_settings"])
    return context, errors


def run_analysis(context):
    channel_stack = get_channel_stack(context["image_id"], context["channel"])

    preprocess_key = hash_payload(
        {
            "image_id": context["image_id"],
            "channel": context["channel"],
            "bg_radius": context["bg_radius"],
            "voxel_size_yx": context["voxel_size_yx"],
            "voxel_size_z": context["voxel_size_z"],
            "ex": context["ex"],
            "em": context["em"],
            "na": context["na"],
            "ri": context["ri"],
            "microscope": context["microscope"],
        }
    )
    preprocess = get_cached_stage_result(
        "preprocess",
        preprocess_key,
        "Running pre-processing and LoG filtering...",
        lambda: compute_preprocess(channel_stack, context),
    )

    detection_key = hash_payload(
        {
            "preprocess_key": preprocess_key,
            "auto_threshold": context["auto_threshold"],
            "manual_threshold": None if context["auto_threshold"] else context["manual_threshold"],
        }
    )
    detection_result = get_cached_stage_result(
        "detection",
        detection_key,
        "Detecting spots...",
        lambda: compute_detection(preprocess, context),
    )

    results = {
        "context": context,
        "preprocess": preprocess,
        "detection": detection_result,
        "decomposition": None,
        "subpixel": None,
        "clustering": None,
        "complete": False,
        "zero_spots": len(detection_result["spots"]) == 0,
    }
    if results["zero_spots"]:
        return results

    decomposition_key = hash_payload(
        {
            "detection_key": detection_key,
            "alpha": context["alpha"],
            "beta": context["beta"],
        }
    )
    decomposition_result = get_cached_stage_result(
        "decomposition",
        decomposition_key,
        "Running dense-region decomposition...",
        lambda: compute_decomposition(preprocess, detection_result, context),
    )
    results["decomposition"] = decomposition_result

    final_spots = decomposition_result["spots_post_decomposition"]
    if context["subpixel_fitting_mode"]:
        subpixel_key = hash_payload({"decomposition_key": decomposition_key, "subpixel": True})
        subpixel_result = get_cached_stage_result(
            "subpixel",
            subpixel_key,
            "Refining spot coordinates with subpixel fitting...",
            lambda: compute_subpixel(preprocess, decomposition_result, context),
        )
        results["subpixel"] = subpixel_result
        final_spots = subpixel_result["spots_subpixel"]

    clustering_key = hash_payload(
        {
            "decomposition_key": decomposition_key,
            "subpixel": bool(context["subpixel_fitting_mode"]),
            "bf_radius": context["bf_radius"],
            "nb_min_spots": context["nb_min_spots"],
        }
    )
    clustering_result = get_cached_stage_result(
        "clustering",
        clustering_key,
        "Detecting clusters...",
        lambda: compute_clustering(final_spots, context),
    )
    results["clustering"] = clustering_result
    results["complete"] = True
    return results


def compute_preprocess(channel_stack, context):
    raw_mip = bf_stack.maximum_projection(channel_stack)
    psf_z, psf_yx = calculate_psf(
        context["voxel_size_z"],
        context["voxel_size_yx"],
        context["ex"],
        context["em"],
        context["na"],
        context["ri"],
        context["microscope"],
    )
    spot_radius_px = get_spot_radius_px(
        context["voxel_size_z"],
        context["voxel_size_yx"],
        psf_z,
        psf_yx,
    )
    processed_stack = background_subtract_stack(channel_stack, context["bg_radius"])
    processed_mip = bf_stack.maximum_projection(processed_stack)
    rna_log, rna_log_mip = log_filter_and_mip(processed_stack, spot_radius_px)
    return {
        "channel_stack": channel_stack,
        "raw_mip": raw_mip,
        "processed_stack": processed_stack,
        "processed_mip": processed_mip,
        "rna_log": rna_log,
        "rna_log_mip": rna_log_mip,
        "psf_z": psf_z,
        "psf_yx": psf_yx,
        "spot_radius_px": spot_radius_px,
    }


def compute_detection(preprocess, context):
    if context["auto_threshold"]:
        spots, threshold_used, mask = detect_spots_auto(
            preprocess["rna_log"],
            preprocess["spot_radius_px"],
        )
    else:
        threshold_used = context["manual_threshold"]
        spots, mask = detect_spots_manual(
            preprocess["rna_log"],
            preprocess["spot_radius_px"],
            threshold_used,
        )
    return {
        "spots": spots,
        "mask": mask,
        "threshold_used": threshold_used,
    }


def compute_decomposition(preprocess, detection_result, context):
    reference_spot, reference_spot_display, rna_denoised = build_reference_spot(
        preprocess["processed_stack"],
        detection_result["spots"],
        context["voxel_size_z"],
        context["voxel_size_yx"],
        preprocess["psf_z"],
        preprocess["psf_yx"],
        context["alpha"],
    )
    spots_post_decomposition = decompose_dense_regions(
        rna_denoised,
        detection_result["spots"],
        reference_spot,
        context["voxel_size_z"],
        context["voxel_size_yx"],
        preprocess["psf_z"],
        preprocess["psf_yx"],
        context["beta"],
    )
    return {
        "reference_spot": reference_spot,
        "reference_spot_display": reference_spot_display,
        "rna_denoised": rna_denoised,
        "spots_post_decomposition": spots_post_decomposition,
    }


def compute_subpixel(preprocess, decomposition_result, context):
    spots_subpixel = fit_subpixel(
        preprocess["processed_stack"],
        decomposition_result["spots_post_decomposition"],
        context["voxel_size_z"],
        context["voxel_size_yx"],
        preprocess["psf_z"],
        preprocess["psf_yx"],
    )
    return {"spots_subpixel": spots_subpixel}


def compute_clustering(final_spots, context):
    clustered_spots, clusters = detect_clusters(
        final_spots,
        context["voxel_size_z"],
        context["voxel_size_yx"],
        context["bf_radius"],
        context["nb_min_spots"],
    )
    return {
        "clustered_spots": clustered_spots,
        "clusters": clusters,
        "spots_in_clusters": count_spots_in_clusters(clustered_spots),
    }


def build_summary_rows(results):
    context = results["context"]
    clustering = results["clustering"]
    rows = [
        {"parameter": "image_name", "value": context["image_name"]},
        {"parameter": "image_id", "value": context["image_id"]},
        {"parameter": "channel", "value": context["channel"]},
        {"parameter": "voxel_size_yx", "value": context["voxel_size_yx"]},
        {"parameter": "voxel_size_z", "value": context["voxel_size_z"]},
        {"parameter": "ex", "value": context["ex"]},
        {"parameter": "em", "value": context["em"]},
        {"parameter": "NA", "value": context["na"]},
        {"parameter": "RI", "value": context["ri"]},
        {"parameter": "microscope", "value": context["microscope"]},
        {"parameter": "bg_radius", "value": context["bg_radius"]},
        {"parameter": "auto_threshold", "value": context["auto_threshold"]},
        {"parameter": "threshold_used", "value": results["detection"]["threshold_used"]},
        {"parameter": "alpha", "value": context["alpha"]},
        {"parameter": "beta", "value": context["beta"]},
        {"parameter": "subpixel_fitting_mode", "value": context["subpixel_fitting_mode"]},
        {"parameter": "bf_radius", "value": context["bf_radius"]},
        {"parameter": "nb_min_spots", "value": context["nb_min_spots"]},
        {"parameter": "total_spots", "value": len(clustering["clustered_spots"]) if clustering else 0},
        {"parameter": "total_clusters", "value": len(clustering["clusters"]) if clustering else 0},
    ]
    return rows


def save_last_run_channel(results):
    channel = results["context"]["channel"]
    saved_channels = st.session_state["saved_channels"]
    existing_signatures = {entry["settings_signature"] for entry in saved_channels.values()}
    if existing_signatures and results["context"]["export_settings_signature"] not in existing_signatures:
        st.error(
            "Saved export channels were analysed with different global settings. Clear the saved channels or rerun with matching settings before saving this channel."
        )
        return

    saved_channels[channel] = {
        "channel": channel,
        "threshold_used": results["detection"]["threshold_used"],
        "auto_threshold": results["context"]["auto_threshold"],
        "settings_signature": results["context"]["export_settings_signature"],
        "settings": dict(results["context"]["export_settings"]),
    }
    st.success(f"Saved channel {channel} for YAML export.")


def build_export_payload(results):
    saved_channels = st.session_state["saved_channels"]
    if saved_channels:
        saved_entries = [saved_channels[channel] for channel in sorted(saved_channels)]
    else:
        saved_entries = [
            {
                "channel": results["context"]["channel"],
                "threshold_used": results["detection"]["threshold_used"],
                "auto_threshold": results["context"]["auto_threshold"],
                "settings_signature": results["context"]["export_settings_signature"],
                "settings": dict(results["context"]["export_settings"]),
            }
        ]

    signatures = {entry["settings_signature"] for entry in saved_entries}
    if len(signatures) != 1:
        raise ValueError("Saved channels were analysed with inconsistent global settings.")

    auto_threshold_modes = {entry["auto_threshold"] for entry in saved_entries}
    if len(auto_threshold_modes) != 1:
        raise ValueError("Saved channels mix auto-threshold and manual-threshold runs. Export one mode at a time.")

    channels = [entry["channel"] for entry in saved_entries]
    manual_thresholds = {entry["channel"]: entry["threshold_used"] for entry in saved_entries}
    settings = dict(saved_entries[0]["settings"])
    settings["channels"] = channels
    settings["manual_thresholds"] = manual_thresholds
    return settings


st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.caption("Interactive parameter tuning for BigFISH smFISH spot detection.")

with st.sidebar:
    with st.expander("OMERO Connection", expanded=True):
        omero_host = st.text_input("Host", value="10.34.168.89")
        omero_port = int(st.number_input("Port", min_value=1, value=4064, step=1))
        omero_user = st.text_input("Username")
        omero_pass = st.text_input("Password", type="password")

        connect_col, disconnect_col = st.columns(2)
        connect_clicked = connect_col.button("Connect", use_container_width=True)
        disconnect_clicked = disconnect_col.button(
            "Disconnect",
            disabled=not st.session_state["omero_connected"],
            use_container_width=True,
        )

        if connect_clicked:
            if not omero_user.strip() or not omero_pass:
                st.error("Enter an OMERO username and password.")
            else:
                try:
                    connection = omero_connect(omero_user, omero_pass, omero_host, omero_port)
                except Exception as exc:
                    st.error(f"Connection failed: {exc}")
                else:
                    st.session_state["omero_conn"] = connection
                    st.session_state["omero_connected"] = True
                    st.success("Connected to OMERO.")

        if disconnect_clicked:
            omero_disconnect(st.session_state["omero_conn"])
            st.session_state["omero_conn"] = None
            st.session_state["omero_connected"] = False
            clear_connection_state()
            st.info("Disconnected from OMERO.")

        if st.session_state["omero_connected"]:
            st.success("Connection status: connected")
        else:
            st.warning("Connection status: not connected")

        raw_image_id = st.text_input("Image ID", placeholder="4717 or Image:4717")
        load_image_clicked = st.button(
            "Load Image Metadata",
            disabled=not st.session_state["omero_connected"],
            use_container_width=True,
        )
        if load_image_clicked:
            try:
                normalized_image_id = normalize_image_id(raw_image_id)
                metadata = omero_load_image_metadata(st.session_state["omero_conn"], normalized_image_id)
            except Exception as exc:
                st.error(f"Image load failed: {exc}")
            else:
                st.session_state["image_id"] = metadata["image_id"]
                st.session_state["image_name"] = metadata["image_name"]
                st.session_state["image_metadata"] = metadata
                st.session_state["param_voxel_size_yx"] = format_optional_number(metadata.get("voxel_size_yx"))
                st.session_state["param_voxel_size_z"] = format_optional_number(metadata.get("voxel_size_z"))
                reset_analysis_state(clear_saved_channels=True)
                st.success(f"Loaded metadata for {metadata['image_name']}.")

    with st.expander("Image Upload", expanded=False):
        st.info("Local upload is intentionally disabled for now. Use OMERO on the laptop or VM.")

    with st.expander("Acquisition Parameters", expanded=True):
        st.text_input("voxel_size_yx (nm)", key="param_voxel_size_yx", placeholder="Required if OMERO metadata is missing")
        st.text_input("voxel_size_z (nm)", key="param_voxel_size_z", placeholder="Required if OMERO metadata is missing")
        st.number_input("Excitation wavelength (nm)", min_value=1.0, step=1.0, key="param_ex")
        st.number_input("Emission wavelength (nm)", min_value=1.0, step=1.0, key="param_em")
        st.number_input("NA", min_value=0.01, step=0.01, key="param_na", format="%.2f")
        st.number_input("RI", min_value=0.01, step=0.01, key="param_ri", format="%.2f")
        st.selectbox("Microscope", ["confocal", "widefield", "nipkow"], key="param_microscope")

    image_metadata = st.session_state["image_metadata"] or {}
    channel_options = build_channel_options(image_metadata)
    selected_channel_option = st.selectbox(
        "Channel",
        channel_options,
        disabled=not bool(st.session_state["image_metadata"]),
    )
    selected_channel = extract_channel_index(selected_channel_option)

    with st.expander("Pre-processing", expanded=True):
        st.number_input("bg_radius (px)", min_value=1, step=1, key="param_bg_radius")

    with st.expander("Spot Detection", expanded=True):
        st.toggle("Auto-threshold", key="param_auto_threshold")
        if not st.session_state["param_auto_threshold"]:
            st.number_input("Manual threshold", min_value=0.0, step=1.0, key="param_manual_threshold")

    with st.expander("Dense Region Decomposition", expanded=True):
        st.number_input("alpha", min_value=0.0, step=0.1, key="param_alpha", format="%.1f")
        st.number_input("beta", min_value=0, step=1, key="param_beta")

    with st.expander("Subpixel Fitting", expanded=True):
        st.toggle("Enable subpixel fitting", key="param_subpixel_fitting_mode")

    with st.expander("Clustering", expanded=True):
        st.number_input("bf_radius (nm)", min_value=1, step=10, key="param_bf_radius")
        st.number_input("nb_min_spots", min_value=1, step=1, key="param_nb_min_spots")

    with st.expander("Batch Configuration", expanded=False):
        st.number_input("number_of_workers", min_value=1, step=1, key="export_number_of_workers")
        st.text_input("input_pattern", key="export_input_pattern", placeholder="/path/to/images/*.tif")
        st.text_input("output_dir", key="export_output_dir", placeholder="/path/to/bf_output")
        st.text_input("output_qc_dir", key="export_output_qc_dir", placeholder="/path/to/bf_output_qc")

    analysis_context, validation_errors = build_analysis_context(selected_channel)
    run_clicked = st.button(
        "Run Analysis",
        type="primary",
        use_container_width=True,
        disabled=st.session_state["image_metadata"] is None,
    )

if run_clicked:
    if st.session_state["image_metadata"] is None:
        st.error("Load image metadata before running the analysis.")
    elif validation_errors:
        for error in validation_errors:
            st.error(error)
    else:
        try:
            st.session_state["last_run_results"] = run_analysis(analysis_context)
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")

st.header("1. Image Information")
if st.session_state["image_metadata"] is None:
    st.info("Connect to OMERO and load image metadata to begin.")
else:
    metadata = st.session_state["image_metadata"]
    info_col_1, info_col_2 = st.columns(2)
    with info_col_1:
        st.metric("Image", metadata["image_name"])
        st.text(f"Image ID: {metadata['image_id']}")
        st.text(f"Shape (Z, C, Y, X): ({metadata['size_z']}, {metadata['size_c']}, {metadata['size_y']}, {metadata['size_x']})")
        st.text(f"Pixel type: {metadata.get('pixel_type') or 'Unknown'}")
    with info_col_2:
        st.text(f"Estimated full image size: {image_size_text(metadata.get('estimated_bytes'))}")
        if metadata.get("estimated_bytes") and metadata["estimated_bytes"] > 8 * 1024 ** 3:
            st.warning("This image is larger than 8 GiB in memory across all channels. The app loads one channel at a time to reduce pressure.")
        if metadata.get("channel_names"):
            st.text(f"Channels: {', '.join(metadata['channel_names'])}")
        if metadata.get("voxel_size_yx") is not None or metadata.get("voxel_size_z") is not None:
            st.text("Voxel sizes were populated from OMERO metadata when available.")

results = st.session_state["last_run_results"]
if results is not None and analysis_context["analysis_signature"] != results["context"]["analysis_signature"]:
    st.warning("Sidebar parameters have changed since the last completed analysis. Click Run Analysis to refresh the results.")

if results is not None:
    preprocess = results["preprocess"]
    detection_result = results["detection"]
    context = results["context"]
    spot_radius_yx = preprocess["spot_radius_px"][-1]

    st.header("2. RNA Maximum Intensity Projection")
    mip_figure, mip_axis = plt.subplots(figsize=(6, 6))
    mip_axis.imshow(stretch_for_display(preprocess["raw_mip"]), cmap="gray")
    mip_axis.set_title(f"Channel {context['channel']} MIP")
    mip_axis.axis("off")
    show_matplotlib_figure(mip_figure)

    st.header("3. LoG-Filtered Image Inspection")
    log_figure = px.imshow(
        preprocess["rna_log_mip"],
        color_continuous_scale="Viridis",
        labels={"color": "Intensity"},
        aspect="equal",
    )
    log_figure.update_traces(
        hovertemplate="x=%{x}<br>y=%{y}<br>intensity=%{z:.3f}<extra></extra>"
    )
    st.plotly_chart(log_figure, use_container_width=True)

    histogram_figure, histogram_axis = plt.subplots(figsize=(8, 3))
    histogram_axis.hist(preprocess["rna_log_mip"].ravel(), bins=200, color="steelblue")
    histogram_axis.axvline(
        detection_result["threshold_used"],
        color="red",
        linestyle="--",
        label=f"threshold = {detection_result['threshold_used']:.3f}",
    )
    histogram_axis.set_xlabel("LoG intensity")
    histogram_axis.set_ylabel("Pixel count")
    histogram_axis.legend()
    show_matplotlib_figure(histogram_figure)

    st.header("4. Spot Detection")
    spot_metric_col, threshold_metric_col = st.columns(2)
    spot_metric_col.metric("Detected spots", len(detection_result["spots"]))
    threshold_metric_col.metric(
        "Threshold used",
        f"{detection_result['threshold_used']:.3f}",
    )

    if context["auto_threshold"]:
        st.subheader("Elbow Plot")
        render_bigfish_plot(
            bf_plot.plot_elbow,
            preprocess["processed_stack"],
            voxel_size=(context["voxel_size_z"], context["voxel_size_yx"], context["voxel_size_yx"]),
            spot_radius=(preprocess["psf_z"], preprocess["psf_yx"], preprocess["psf_yx"]),
            framesize=(6, 4),
        )

    render_bigfish_plot(
        bf_plot.plot_detection,
        preprocess["processed_mip"],
        detection_result["spots"],
        radius=spot_radius_yx,
        contrast=True,
        framesize=(10, 8),
    )

    if results["zero_spots"]:
        st.warning("No spots were detected. Lower the threshold or adjust the acquisition parameters, then rerun.")
    else:
        decomposition = results["decomposition"]
        st.header("5. Dense Region Decomposition")
        reference_figure_title = "Reference spot"
        render_bigfish_plot(
            bf_plot.plot_reference_spot,
            decomposition["reference_spot_display"],
            rescale=True,
            title=reference_figure_title,
            framesize=(5, 5),
        )

        before_col, after_col = st.columns(2)
        before_col.metric("Spots before decomposition", len(detection_result["spots"]))
        after_col.metric(
            "Spots after decomposition",
            len(decomposition["spots_post_decomposition"]),
        )

        render_bigfish_plot(
            bf_plot.plot_detection,
            preprocess["processed_mip"],
            decomposition["spots_post_decomposition"],
            radius=spot_radius_yx,
            contrast=True,
            framesize=(10, 8),
        )

        st.header("6. Subpixel Fitting")
        if context["subpixel_fitting_mode"]:
            subpixel_result = results["subpixel"]
            st.metric("Subpixel-refined spots", len(subpixel_result["spots_subpixel"]))
            render_bigfish_plot(
                bf_plot.plot_detection,
                preprocess["processed_mip"],
                [decomposition["spots_post_decomposition"], subpixel_result["spots_subpixel"]],
                radius=[spot_radius_yx, spot_radius_yx],
                color=["red", "blue"],
                linewidth=[1, 1],
                contrast=True,
                framesize=(10, 8),
                title="Red = pixel, Blue = subpixel",
            )
            final_spots = subpixel_result["spots_subpixel"]
        else:
            st.info("Subpixel fitting is disabled for this run.")
            final_spots = decomposition["spots_post_decomposition"]

        st.header("7. Clustering")
        clustering = results["clustering"]
        cluster_metric_col_1, cluster_metric_col_2, cluster_metric_col_3 = st.columns(3)
        cluster_metric_col_1.metric("Total spots", len(clustering["clustered_spots"]))
        cluster_metric_col_2.metric("Clusters", len(clustering["clusters"]))
        cluster_metric_col_3.metric("Spots in clusters", clustering["spots_in_clusters"])

        if len(clustering["clusters"]) > 0:
            render_bigfish_plot(
                bf_plot.plot_detection,
                preprocess["processed_mip"],
                [final_spots, clustering["clusters"][:, :3]],
                shape=["circle", "polygon"],
                radius=[spot_radius_yx, context["bf_radius"] / context["voxel_size_yx"]],
                color=["orange", "cyan"],
                linewidth=[1, 2],
                fill=[False, True],
                contrast=True,
                framesize=(10, 8),
            )
        else:
            render_bigfish_plot(
                bf_plot.plot_detection,
                preprocess["processed_mip"],
                final_spots,
                radius=spot_radius_yx,
                contrast=True,
                framesize=(10, 8),
            )

        st.header("8. Summary and YAML Export")
        st.dataframe(build_summary_rows(results), use_container_width=True)

        save_col, remove_col, clear_col = st.columns(3)
        if save_col.button("Save last analysed channel", use_container_width=True):
            save_last_run_channel(results)
        if remove_col.button(
            "Remove current channel",
            disabled=results["context"]["channel"] not in st.session_state["saved_channels"],
            use_container_width=True,
        ):
            st.session_state["saved_channels"].pop(results["context"]["channel"], None)
            st.info(f"Removed channel {results['context']['channel']} from the saved YAML export set.")
        if clear_col.button(
            "Clear saved channels",
            disabled=not st.session_state["saved_channels"],
            use_container_width=True,
        ):
            st.session_state["saved_channels"] = {}
            st.info("Cleared the saved YAML export set.")

        saved_channels = st.session_state["saved_channels"]
        if saved_channels:
            st.caption("Saved channels for YAML export")
            st.dataframe(
                [
                    {
                        "channel": channel,
                        "threshold_used": entry["threshold_used"],
                        "auto_threshold": entry["auto_threshold"],
                    }
                    for channel, entry in sorted(saved_channels.items())
                ],
                use_container_width=True,
            )
        else:
            st.caption("No channels are explicitly saved yet. YAML export will use the last analysed channel only.")

        st.caption(
            "The current batch schema supports at most two manually thresholded channels. Saved channels must also share the same global analysis settings."
        )

        yaml_content = None
        export_error = None
        try:
            export_payload = build_export_payload(results)
            yaml_content = generate_yaml(
                voxel_size_yx=export_payload["voxel_size_yx"],
                voxel_size_z=export_payload["voxel_size_z"],
                ex=export_payload["ex"],
                em=export_payload["em"],
                na=export_payload["na"],
                ri=export_payload["ri"],
                microscope=export_payload["microscope"],
                bg_radius=export_payload["bg_radius"],
                channels=export_payload["channels"],
                auto_threshold=export_payload["auto_threshold"],
                manual_thresholds=export_payload["manual_thresholds"],
                alpha=export_payload["alpha"],
                beta=export_payload["beta"],
                subpixel_fitting_mode=export_payload["subpixel_fitting_mode"],
                bf_radius=export_payload["bf_radius"],
                nb_min_spots=export_payload["nb_min_spots"],
                number_of_workers=st.session_state["export_number_of_workers"],
                input_pattern=st.session_state["export_input_pattern"],
                output_dir=st.session_state["export_output_dir"],
                output_qc_dir=st.session_state["export_output_qc_dir"],
            )
        except ValueError as exc:
            export_error = str(exc)

        if export_error:
            st.error(export_error)
        else:
            st.download_button(
                "Download configuration YAML",
                data=yaml_content,
                file_name="smFISH_analysis_config.yaml",
                mime="text/yaml",
                type="primary",
                use_container_width=True,
            )
            with st.expander("Preview YAML", expanded=False):
                st.code(yaml_content, language="yaml")

        st.header("9. Cell Segmentation")
        st.info(
            "Cellpose segmentation is intentionally disabled in this laptop and VM app. Run segmentation separately in the batch workflow on a larger machine if needed."
        )