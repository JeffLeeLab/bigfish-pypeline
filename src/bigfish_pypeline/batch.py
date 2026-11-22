"""Processing of one image: every pipeline step for each FISH channel, and the image's tables.

`process_image` is the function a batch worker runs for one image.
`calibration_threshold` gives one image's automatic threshold for the
calibration pass of the calibrated threshold mode.
"""

import time
import traceback
from pathlib import Path

import numpy as np

from bigfish_pypeline import io
from bigfish_pypeline import outputs
from bigfish_pypeline.cells import assign_cells
from bigfish_pypeline.clusters import detect_clusters
from bigfish_pypeline.decomposition import decompose_dense_regions, get_seed
from bigfish_pypeline.detection import (
    detect_spots,
    exceeds_bailout,
    filter_channel,
    get_spot_radius_nm,
    get_spot_radius_px,
)
from bigfish_pypeline.measurements import measure_spots
from bigfish_pypeline.segmentation import LabelFileError, read_label_file
from bigfish_pypeline.subpixel import fit_subpixel

# Problems that stop the whole run rather than one image or channel.
PASS_THROUGH = (io.OmeroSessionEnded, KeyboardInterrupt, MemoryError)

NO_AUTO_THRESHOLD_REASON = "no automatic threshold (too few candidate spots)"


class ChannelError(Exception):
    """A channel that cannot be processed with the settings given, with a plain one-line reason."""


# OMERO connection of this process, joined once and reused for later images.
_omero = {"conn": None, "session": None}


# ---------------------------------------------------------------------------
# Small helpers shared with the batch runner
# ---------------------------------------------------------------------------


def get_ndim(config):
    """3 for 3D layouts (with Z), 2 for 2D layouts."""
    return 3 if "Z" in config.image.axes else 2


def get_voxel_size(config):
    """Voxel size in nm from the config: (z, yx, yx) in 3D, (yx, yx) in 2D."""
    voxel_size_yx = config.image.voxel_size_nm.yx
    if get_ndim(config) == 3:
        return (config.image.voxel_size_nm.z, voxel_size_yx, voxel_size_yx)
    return (voxel_size_yx, voxel_size_yx)


def run_spot_columns(config):
    """Columns of every spots table of the run: subpixel, SNR and intensity columns
    are present when any channel has them switched on."""
    return outputs.spot_columns(
        get_ndim(config),
        subpixel=any(channel.subpixel.enabled for channel in config.channels),
        snr=any(channel.measurements.snr for channel in config.channels),
        intensity=any(channel.measurements.intensity for channel in config.channels),
    )


def run_has_clusters(config):
    """True when any channel has cluster detection switched on."""
    return any(channel.clusters.enabled for channel in config.channels)


def close_omero_connection():
    """Leave the OMERO session this process joined, without ending it."""
    if _omero["conn"] is not None:
        io.detach_session(_omero["conn"])
    _omero["conn"] = None
    _omero["session"] = None


# ---------------------------------------------------------------------------
# Opening an image
# ---------------------------------------------------------------------------


def _omero_connection(host, port, key):
    """Connection to the shared OMERO session, joined on first use in this process."""
    session = (host, int(port), key)
    if _omero["conn"] is None or _omero["session"] != session:
        close_omero_connection()
        _omero["conn"] = io.join_session(host, port, key)
        _omero["session"] = session
    return _omero["conn"]


def _channel_text(n_channels):
    if n_channels == 1:
        return "1 channel (channel 0)"
    return f"{n_channels} channels (0–{n_channels - 1})"


def _check_channels(label, channels, n_channels):
    """Raise ImageReadError when a channel of the config is not in the image."""
    missing = [str(channel) for channel in channels if not 0 <= channel < n_channels]
    if missing:
        raise io.ImageReadError(
            f"{label}: channel {', '.join(missing)} does not exist; "
            f"the image has {_channel_text(n_channels)}"
        )


def _open_image(config, image_source, channels, omero_host=None, omero_port=None, omero_key=None):
    """
    Check that an image can be read with the config's layout and that it holds
    the channels asked for.

    Returns (info, read_channel): the image information from the file header
    or the server, and a function that reads one channel as an array.
    Raises ImageReadError when the image cannot be used.
    """
    layout = config.image.axes
    if config.run.input.source == "omero":
        conn = _omero_connection(omero_host, omero_port, omero_key)
        image_id = int(image_source)
        info = io.get_omero_image_info(conn, image_id)
        label = f"OMERO image {image_id}"
        if info.size_t > 1:
            raise io.ImageReadError(f"{label}: the image has {info.size_t} time points; only one is accepted")
        if sorted(layout) != sorted(info.axes):
            shape = " × ".join(str(n) for n in info.shape)
            raise io.ImageReadError(f"{label}: the image ({shape}) does not fit the layout {layout}")
        _check_channels(label, channels, info.size_c)

        def read_channel(channel):
            arrays, conn = io.read_omero_channels_with_retry(
                _omero["conn"], image_id, layout, [channel], omero_host, omero_port, omero_key
            )
            _omero["conn"] = conn
            return arrays[channel]

        return info, read_channel

    path = Path(image_source)
    info = io.get_image_info(path)
    # Reading no channel checks the layout, time points, positions and pixel type.
    io.read_channels(path, layout, [])
    sizes = dict(zip(layout, info.shape))
    _check_channels(path.name, channels, sizes.get("C", 1))

    def read_channel(channel):
        return io.read_channel(path, layout, channel)

    return info, read_channel


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _one_line(error):
    """Plain one-line reason for an error."""
    text = " ".join(str(error).split())
    if isinstance(error, (io.ImageReadError, LabelFileError, ChannelError)):
        return text
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def _hide_session_key(text, key):
    """Text with any OMERO session key replaced by `[hidden]`."""
    text = io.SESSION_KEY_PATTERN.sub("[hidden]", str(text))
    if key:
        text = text.replace(str(key), "[hidden]")
    return text


# ---------------------------------------------------------------------------
# One channel
# ---------------------------------------------------------------------------


def _threshold_settings(config, channel):
    """(threshold value, lower limit) for detect_spots; raises ChannelError when a
    calibrated value is missing."""
    mode = channel.threshold.mode
    if mode == "manual":
        return channel.threshold.value, None
    if mode == "auto":
        return None, channel.threshold.lower_limit
    thresholds = config.resolved.thresholds if config.resolved is not None else {}
    if channel.index not in thresholds:
        raise ChannelError(
            f"no calibrated threshold for channel {channel.index}: the calibration has not "
            "been run or gave no value"
        )
    return thresholds[channel.index], None


def _process_channel(config, channel, image_name, read_channel, masks, spot_columns, found):
    """
    Steps 1–8 and 10 for one channel.

    found: a dict filled in as the steps go, so that the threshold and the
    number of detected spots are known even if a later step fails.

    Returns a dict with the status ("done" or "skipped"), the reason, the
    counts, the warnings, and the channel's spots, clusters and cells tables.
    """
    ndim = get_ndim(config)
    voxel_size = get_voxel_size(config)
    voxel_size_yx = voxel_size[-1]
    voxel_size_z = voxel_size[0] if ndim == 3 else None
    microscope = config.microscope
    index = channel.index
    warnings = []

    threshold, lower_limit = _threshold_settings(config, channel)

    # step 1: read the channel
    image = read_channel(index)

    # step 2: spot radius
    spot_radius_px = get_spot_radius_px(
        voxel_size, channel.ex, channel.em, microscope.NA, microscope.RI, microscope.type
    )
    spot_radius_nm = get_spot_radius_nm(
        voxel_size, channel.ex, channel.em, microscope.NA, microscope.RI, microscope.type
    )

    # step 3: background and LoG filter
    filtered = filter_channel(
        image, spot_radius_px,
        bg_radius=channel.background.radius_px,
        bg_method=channel.background.method,
    )
    del image
    rna = filtered["rna"]
    rna_log = filtered["rna_log"]
    del filtered

    # step 4: detection
    detected = detect_spots(
        rna_log, spot_radius_px,
        threshold_mode=channel.threshold.mode,
        threshold=threshold,
        lower_limit=lower_limit,
        elbow=False,
    )
    spots = detected["spots"]
    threshold = detected["threshold"]
    found["threshold"] = threshold
    found["n_spots_detected"] = len(spots)
    if detected["warning"]:
        warnings.append(detected["warning"])

    result = {
        "threshold": threshold,
        "n_spots_detected": len(spots),
        "warnings": warnings,
        "spots": None,
        "clusters": None,
        "cells": None,
    }

    # bailout
    if channel.bailout.enabled and exceeds_bailout(len(spots), channel.bailout.max_spots):
        result["status"] = "skipped"
        result["reason"] = (
            f"bailout: {len(spots)} spots detected, above the limit of "
            f"{channel.bailout.max_spots}"
        )
        return result

    # step 5: decomposition of dense regions
    if channel.decomposition.enabled:
        decomposed = decompose_dense_regions(
            rna, spots, voxel_size, spot_radius_nm,
            alpha=channel.decomposition.alpha,
            beta=channel.decomposition.beta,
            seed=get_seed(config.run.seed, image_name, index),
        )
        spots_post_decomposition = decomposed["spots_post_decomposition"]
        if decomposed["warning"]:
            warnings.append(decomposed["warning"])
        del decomposed
    else:
        spots_post_decomposition = spots

    # step 6: subpixel fitting
    spots_subpixel = None
    if channel.subpixel.enabled:
        spots_subpixel = fit_subpixel(rna, spots_post_decomposition, voxel_size, spot_radius_nm)

    # step 7: clusters, on the subpixel positions when there are any
    clusters = None
    cluster_id = np.full(len(spots_post_decomposition), -1, dtype=np.int64)
    if channel.clusters.enabled:
        positions = spots_subpixel if spots_subpixel is not None else spots_post_decomposition
        spots_post_clustering, clusters = detect_clusters(
            positions, voxel_size,
            radius=channel.clusters.radius_nm,
            nb_min_spots=channel.clusters.min_spots,
        )
        cluster_id = spots_post_clustering[:, ndim].astype(np.int64)

    # step 8: measurements, at the pixel positions
    spot_measurements = {}
    if channel.measurements.snr or channel.measurements.intensity:
        spot_measurements = measure_spots(
            rna, rna_log, spots_post_decomposition, spot_radius_px,
            snr=channel.measurements.snr,
            intensity=channel.measurements.intensity,
        )
    del rna, rna_log

    # step 10: cell assignment, at the pixel positions
    spot_cell_id = None
    cluster_cell_id = None
    if masks is not None:
        spots_with_cluster = np.column_stack([spots_post_decomposition, cluster_id])
        spot_cell_id, cluster_cell_id, cells = assign_cells(
            masks, spots_with_cluster, ndim, voxel_size_yx,
            clusters=clusters,
            drop_border_cells=config.segmentation.drop_border_cells,
        )
        if clusters is None:
            cluster_cell_id = None
        result["cells"] = outputs.make_cells_table(image_name, index, channel.name, cells)
        result["n_cells"] = len(cells)

    result["spots"] = outputs.make_spots_table(
        image_name, index, channel.name, spots_post_decomposition, ndim,
        voxel_size_yx, voxel_size_z,
        cluster_id=cluster_id,
        cell_id=spot_cell_id,
        subpixel=spots_subpixel,
        snr=spot_measurements.get("snr"),
        log_intensity=spot_measurements.get("log_intensity"),
        columns=spot_columns,
    )
    result["clusters"] = outputs.make_clusters_table(
        image_name, index, channel.name, clusters, ndim, voxel_size_yx, voxel_size_z,
        cell_id=cluster_cell_id,
    )
    result["status"] = "done"
    result["reason"] = ""
    result["n_spots"] = len(spots_post_decomposition)
    result["n_clusters"] = 0 if clusters is None else len(clusters)
    return result


# ---------------------------------------------------------------------------
# One image
# ---------------------------------------------------------------------------


def _number(value, kind=int):
    return None if value is None else kind(value)


def process_image(config, image_name, image_source, run_folder, label_folder=None,
                  omero_host=None, omero_port=None, omero_key=None):
    """
    Run every pipeline step on one image, channel by channel, and write its tables.

    config: the run's config, with full paths; calibrated thresholds, if any,
        in its `resolved` block.
    image_name: the image's output name, used in the tables and file names.
    image_source: the file path for local input, or the image ID for OMERO.
    run_folder: the run folder; the tables go to its `per_image/` folder.
    label_folder: folder holding `<image>_seglabels.tif`, or None when there
        are no cell results to make.
    omero_host, omero_port, omero_key: the OMERO server and the session key to
        join (OMERO input only). The connection is kept for later images in
        the same process; close it with `close_omero_connection`.

    Each channel is processed inside its own error handling: a failure marks
    that channel failed and the other channels are kept. When the image
    itself cannot be used, every channel is marked failed and only the
    image's `_images.csv` is written.

    Returns a dict with:
    - "image": the output name,
    - "rows": the `images` table rows, one per channel (see outputs.image_row),
    - "log_lines": text lines for the run log (warnings, and the full details
      of failures).

    OmeroSessionEnded, KeyboardInterrupt and MemoryError are not caught.
    """
    image_start = time.perf_counter()
    run_folder = Path(run_folder)
    (run_folder / outputs.PER_IMAGE_FOLDER_NAME).mkdir(parents=True, exist_ok=True)
    channels = config.channels
    log_lines = []
    rows = []

    def hide(text):
        return _hide_session_key(text, omero_key) if config.run.input.source == "omero" else text

    segmentation_source = config.segmentation.source if label_folder is not None else ""

    # step 1: open the image, check its voxel sizes and read its labels
    try:
        info, read_channel = _open_image(
            config, image_source, [channel.index for channel in channels],
            omero_host, omero_port, omero_key,
        )
    except PASS_THROUGH:
        raise
    except Exception as error:
        reason = hide(_one_line(error))
        log_lines.append(f"{image_name}: image failed: {reason}")
        log_lines.append(hide(traceback.format_exc().rstrip()))
        runtime = time.perf_counter() - image_start
        for channel in channels:
            rows.append(outputs.image_row(
                image_name, channel.index, channel.name, "failed",
                reason=reason,
                threshold_mode=channel.threshold.mode,
                segmentation_source=segmentation_source,
                runtime_s=runtime,
            ))
        outputs.write_image_tables(run_folder, image_name, outputs.make_images_table(rows))
        return {"image": image_name, "rows": rows, "log_lines": log_lines}

    image_warnings = []
    voxel_size = get_voxel_size(config)
    voxel_warning = io.check_voxel_sizes(
        info, voxel_size[0] if len(voxel_size) == 3 else None, voxel_size[-1]
    )
    if voxel_warning:
        image_warnings.append(voxel_warning)

    masks = None
    segmentation_status = ""
    if label_folder is not None:
        try:
            masks = read_label_file(label_folder, image_name, info.shape[-2:])
            segmentation_status = "done"
        except PASS_THROUGH:
            raise
        except Exception as error:
            segmentation_status = "no_labels"
            image_warnings.append(f"no cell results: {_one_line(error)}")
    for warning in image_warnings:
        log_lines.append(f"{image_name}: warning: {hide(warning)}")

    # steps 2–8 and 10, one channel at a time
    spot_columns = run_spot_columns(config)
    spot_tables, cluster_tables, cell_tables = [], [], []
    for channel in channels:
        channel_start = time.perf_counter()
        found = {"threshold": None, "n_spots_detected": None}
        label = f"{image_name}, channel {channel.index}"
        try:
            result = _process_channel(
                config, channel, image_name, read_channel, masks, spot_columns, found
            )
        except PASS_THROUGH:
            raise
        except Exception as error:
            reason = hide(_one_line(error))
            log_lines.append(f"{label}: failed: {reason}")
            log_lines.append(hide(traceback.format_exc().rstrip()))
            rows.append(outputs.image_row(
                image_name, channel.index, channel.name, "failed",
                reason=reason,
                threshold_mode=channel.threshold.mode,
                threshold=_number(found["threshold"], float),
                n_spots_detected=_number(found["n_spots_detected"]),
                segmentation_source=segmentation_source,
                segmentation_status=segmentation_status,
                warnings=image_warnings,
                runtime_s=time.perf_counter() - channel_start,
            ))
            continue

        for warning in result["warnings"]:
            log_lines.append(f"{label}: warning: {hide(warning)}")
        if result["status"] == "skipped":
            log_lines.append(f"{label}: skipped: {result['reason']}")
        for tables, kind in ((spot_tables, "spots"), (cluster_tables, "clusters"), (cell_tables, "cells")):
            if result[kind] is not None:
                tables.append(result[kind])
        rows.append(outputs.image_row(
            image_name, channel.index, channel.name, result["status"],
            reason=result["reason"],
            threshold_mode=channel.threshold.mode,
            threshold=_number(result["threshold"], float),
            n_spots_detected=_number(result["n_spots_detected"]),
            n_spots=_number(result.get("n_spots")),
            n_clusters=_number(result.get("n_clusters")),
            n_cells=_number(result.get("n_cells")),
            segmentation_source=segmentation_source,
            segmentation_status=segmentation_status,
            warnings=image_warnings + [hide(warning) for warning in result["warnings"]],
            runtime_s=time.perf_counter() - channel_start,
        ))
        del result

    ndim = get_ndim(config)
    spots_table = outputs.join_tables(spot_tables, columns=spot_columns)
    clusters_table = None
    if run_has_clusters(config):
        clusters_table = outputs.join_tables(cluster_tables, columns=outputs.cluster_columns(ndim))
    cells_table = None
    if masks is not None:
        cells_table = outputs.join_tables(cell_tables, columns=outputs.CELLS_TABLE_COLUMNS)
    outputs.write_image_tables(
        run_folder, image_name, outputs.make_images_table(rows),
        spots=spots_table, clusters=clusters_table, cells=cells_table,
    )
    return {"image": image_name, "rows": rows, "log_lines": log_lines}


# ---------------------------------------------------------------------------
# Calibration pass
# ---------------------------------------------------------------------------


def _channel_settings(config, channel_index):
    for channel in config.channels:
        if channel.index == channel_index:
            return channel
    raise ChannelError(f"channel {channel_index} is not in the config")


def calibration_threshold(config, image_name, image_source, channel_index,
                          omero_host=None, omero_port=None, omero_key=None):
    """
    Automatic threshold of one image and channel, for the calibrated mode.

    The threshold is the big-fish elbow value, raised to the channel's lower
    limit when it is lower. Bailout is not applied.

    Returns a dict with "image", "channel", "threshold" (None when there is no
    value), "reason" (why there is no value, otherwise None) and "log_lines"
    (full details of a failure). The "image", "threshold" and "reason" keys
    are those detection.calibrate_threshold reads.

    OmeroSessionEnded, KeyboardInterrupt and MemoryError are not caught.
    """
    result = {
        "image": image_name, "channel": channel_index,
        "threshold": None, "reason": None, "log_lines": [],
    }

    def hide(text):
        return _hide_session_key(text, omero_key) if config.run.input.source == "omero" else text

    try:
        channel = _channel_settings(config, channel_index)
        _, read_channel = _open_image(
            config, image_source, [channel_index], omero_host, omero_port, omero_key
        )
        voxel_size = get_voxel_size(config)
        microscope = config.microscope
        spot_radius_px = get_spot_radius_px(
            voxel_size, channel.ex, channel.em, microscope.NA, microscope.RI, microscope.type
        )
        image = read_channel(channel_index)
        rna_log = filter_channel(
            image, spot_radius_px,
            bg_radius=channel.background.radius_px,
            bg_method=channel.background.method,
        )["rna_log"]
        del image
        detected = detect_spots(
            rna_log, spot_radius_px, threshold_mode="auto",
            lower_limit=channel.threshold.lower_limit, elbow=False,
        )
    except PASS_THROUGH:
        raise
    except Exception as error:
        result["reason"] = hide(_one_line(error))
        result["log_lines"] = [
            f"{image_name}, channel {channel_index}: no calibration value: {result['reason']}",
            hide(traceback.format_exc().rstrip()),
        ]
        return result

    if detected["threshold"] is None:
        result["reason"] = NO_AUTO_THRESHOLD_REASON
    else:
        result["threshold"] = float(detected["threshold"])
    return result
