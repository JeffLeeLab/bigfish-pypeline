"""Batch processing: one image through every step, and a whole batch run.

`process_image` is the function a batch worker runs for one image.
`calibration_threshold` gives one image's automatic threshold for the
calibration pass of the calibrated threshold mode.
`run_batch` runs every image of a batch in a pool of worker processes.
"""

import atexit
import json
import math
import multiprocessing
import os
import signal
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil

from bigfish_pypeline import io
from bigfish_pypeline import outputs
from bigfish_pypeline.cells import assign_cells
from bigfish_pypeline.clusters import detect_clusters
from bigfish_pypeline.decomposition import decompose_dense_regions, get_seed
from bigfish_pypeline.detection import (
    calibrate_threshold,
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


def _check_omero_image(info, layout, channels):
    """Raise ImageReadError when an OMERO image does not fit the layout or lacks a channel."""
    label = f"OMERO image {info.image_id}"
    if info.size_t > 1:
        raise io.ImageReadError(f"{label}: the image has {info.size_t} time points; only one is accepted")
    if sorted(layout) != sorted(info.axes):
        shape = " × ".join(str(n) for n in info.shape)
        raise io.ImageReadError(f"{label}: the image ({shape}) does not fit the layout {layout}")
    _check_channels(label, channels, info.size_c)


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
        _check_omero_image(info, layout, channels)

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


# ---------------------------------------------------------------------------
# Batch run
# ---------------------------------------------------------------------------

# Memory needed by one worker: 35 bytes for each voxel of one channel of the
# largest image (about 5 GB for 2048 × 2048 × 35), and never less than 0.5 GB.
BYTES_PER_VOXEL_PER_WORKER = 35
MIN_MEMORY_PER_WORKER = 0.5e9
# Memory kept free for the main process and other programs.
MEMORY_RESERVE = 2e9

LOG_NAME = "run.log"
PROGRESS_NAME = "progress.json"
CANCEL_NAME = "cancel"
CHECK_INTERVAL_S = 1
PROGRESS_INTERVAL_S = 10
THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
WORKER_STOPPED_REASON = "worker stopped unexpectedly, probably out of memory"


class BatchError(Exception):
    """A problem found before any image is processed, with a plain message."""


@dataclass
class RunImage:
    """One image of a run.

    name: the output name, used in the tables and file names.
    listed: the name written in `run_config.yaml` (the file name for local
        input, the output name for OMERO); calibration filters are matched
        against it.
    source: the file path for local input, or the image ID for OMERO.
    """

    name: str
    listed: str
    source: object


@dataclass
class BatchResult:
    """Outcome of a batch run.

    status: "finished", "cancelled" or "stopped".
    message: a plain sentence saying how the run ended.
    """

    run_folder: Path
    status: str
    message: str


# -- number of workers -------------------------------------------------------


def _gb(n_bytes):
    return f"{n_bytes / 1e9:.1f} GB"


def memory_per_worker(voxels_per_channel):
    """Estimated memory in bytes for one worker, from the voxels of one channel of the largest image."""
    return max(MIN_MEMORY_PER_WORKER, BYTES_PER_VOXEL_PER_WORKER * voxels_per_channel)


def choose_workers(requested, n_images, voxels_per_channel, cpu_count, available_memory,
                   total_memory=None):
    """
    Number of worker processes for a run.

    requested: `run.workers` from the config, "auto" or a whole number.
    n_images: number of images in the run.
    voxels_per_channel: voxels in one channel of the largest image.
    cpu_count: number of processor cores (None when not known).
    available_memory: memory available now, in bytes.
    total_memory: memory of the computer, in bytes (None: taken to be the
        available memory).

    "auto" gives the smaller of (cores − 1) and (available memory − reserve)
    ÷ (memory per worker), never more than the number of images and at
    least 1. When the available memory is short for one worker but the
    computer's memory is enough, one worker is used, with a warning: a
    computer in everyday use often reports little available memory and
    frees more when it is needed. A number given is used as it is, but
    never more than the number of images.

    Returns (n_workers, reason, warning): the reason is a sentence for the
    log, the warning is None or a sentence saying memory may run short.
    Raises BatchError when "auto" finds that the computer's memory is too
    small for one worker.
    """
    per_worker = memory_per_worker(voxels_per_channel)
    usable = available_memory - MEMORY_RESERVE
    fit_in_memory = int(usable // per_worker) if usable > 0 else 0
    memory_text = (
        f"{_gb(available_memory)} of memory available, {_gb(MEMORY_RESERVE)} kept free, "
        f"about {_gb(per_worker)} per worker"
    )
    n_images = max(1, n_images)

    if requested == "auto":
        if fit_in_memory < 1:
            if total_memory is None:
                total_memory = available_memory
            if total_memory - MEMORY_RESERVE < per_worker:
                raise BatchError(
                    f"There is not enough memory for one worker: this computer has "
                    f"{_gb(total_memory)} of memory, and a worker needs about {_gb(per_worker)} "
                    f"with {_gb(MEMORY_RESERVE)} kept free. Use a computer with more memory, "
                    "or smaller images."
                )
            reason = f"1 worker(s), chosen automatically: {memory_text} (room for 0)"
            warning = (
                f"little memory is available at the moment ({memory_text}). The run goes on "
                "with one worker, but may be slow. Closing other programs frees memory."
            )
            return 1, reason, warning
        cores = max(1, (cpu_count or 1) - 1)
        n_workers = max(1, min(cores, fit_in_memory, n_images))
        reason = (
            f"{n_workers} worker(s), chosen automatically: {cpu_count or 1} processor cores "
            f"(one left for the main process) and {memory_text} (room for {fit_in_memory}); "
            f"{n_images} image(s)"
        )
        return n_workers, reason, None

    n_workers = max(1, min(int(requested), n_images))
    reason = f"{n_workers} worker(s), as set in the config"
    if n_workers < int(requested):
        reason += f" ({requested} asked for, but there are only {n_images} image(s))"
    warning = None
    if n_workers > fit_in_memory:
        warning = (
            f"memory may run short with {n_workers} worker(s): {memory_text}, room for "
            f"{fit_in_memory}. If workers stop unexpectedly, use fewer workers or `workers: auto`."
        )
    return n_workers, reason, warning


def _voxels_per_channel(shape, axes):
    """Voxels in one channel, from a shape and its axes (C is left out)."""
    if axes is not None and len(axes) == len(shape):
        return math.prod(size for axis, size in zip(axes, shape) if axis != "C")
    return math.prod(shape)


# -- worker processes --------------------------------------------------------


def _start_worker():
    """Run in each worker process as it starts: Ctrl+C is left to the main
    process, and the OMERO session is left when the process ends."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    atexit.register(close_omero_connection)


class _WorkerPool:
    """A pool of worker processes started with "spawn", made on first use."""

    def __init__(self, n_workers):
        self.n_workers = n_workers
        self._executor = None

    def submit(self, function, **arguments):
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=self.n_workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_start_worker,
            )
        return self._executor.submit(function, **arguments)

    def stop_now(self):
        """Stop every worker process at once, dropping the work in progress."""
        executor, self._executor = self._executor, None
        if executor is None:
            return
        # ProcessPoolExecutor has no public way to stop its processes at once
        # in Python 3.12, so its list of processes is used directly.
        processes = list((getattr(executor, "_processes", None) or {}).values())
        for process in processes:
            try:
                process.terminate()
            except Exception:
                pass
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.kill()
                process.join(timeout=10)
        executor.shutdown(wait=True, cancel_futures=True)

    def close(self):
        """Let the worker processes finish and end."""
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True)


# -- checks before the run ---------------------------------------------------


def _check_segmentation(config):
    """The label folder for the run, or None when there is no segmentation."""
    segmentation = config.segmentation
    if not segmentation.enabled:
        return None
    if segmentation.source == "cellpose":
        raise BatchError(
            "Segmentation with Cellpose is not available yet. Use label files "
            "(`segmentation.source: label_files`) or switch segmentation off."
        )
    label_folder = config.full_label_folder()
    if label_folder is None or not label_folder.is_dir():
        raise BatchError(f"The label folder {label_folder} does not exist (`segmentation.label_folder`).")
    return label_folder


def _check_output_folder(config):
    try:
        outputs.check_writable(outputs.output_root(config))
    except outputs.OutputError as error:
        raise BatchError(str(error)) from None


def _local_images(config):
    """Images of a local run, and the header of each (None when it cannot be read)."""
    folder = config.full_input_folder()
    if folder is None:
        raise BatchError("There is no input folder: set `run.input.folder`.")
    if not folder.is_dir():
        raise BatchError(f"The input folder {folder} does not exist.")

    if config.resolved is not None:
        paths = [folder / name for name in config.resolved.images]
        missing = [path.name for path in paths if not path.is_file()]
        if missing:
            raise BatchError(
                f"These images listed in the config are missing from {folder}: {', '.join(missing)}"
            )
    else:
        paths = io.list_images(folder, config.run.input.filter, config.run.input.extension)
    if not paths:
        raise BatchError(
            f"No images in {folder} match the filter `{config.run.input.filter}` "
            f"and the extension {config.run.input.extension}."
        )
    try:
        io.check_output_names(paths)
    except ValueError as error:
        raise BatchError(str(error)) from None

    images = [RunImage(io.output_name(path), path.name, path) for path in paths]
    headers = []
    for path in paths:
        try:
            headers.append(io.get_image_info(path))
        except Exception:
            headers.append(None)
    return images, headers


def _omero_ids(config):
    """Image IDs listed in `resolved`, read from the start of each output name."""
    ids = []
    for name in config.resolved.images:
        text = name.split("_", 1)[0]
        if not text.isdigit():
            raise BatchError(f"`{name}` in `resolved.images` does not start with an OMERO image ID.")
        ids.append(int(text))
    return ids


def _omero_images(config, conn):
    """Images of an OMERO run, and the information of each (None when it cannot be read)."""
    omero = config.run.input.omero
    try:
        if config.resolved is not None:
            ids = _omero_ids(config)
            try:
                io.list_omero_images(conn, image_ids=ids)
            except ValueError as error:
                raise BatchError(f"An image listed in the config is missing: {error}") from None
            images = [RunImage(name, name, image_id) for name, image_id in zip(config.resolved.images, ids)]
        else:
            if omero.dataset_id is not None and omero.image_ids:
                raise BatchError("Give either a dataset ID or image IDs for OMERO, not both.")
            if omero.dataset_id is not None:
                listed = io.list_omero_images(conn, dataset_id=omero.dataset_id)
            else:
                listed = io.list_omero_images(conn, image_ids=omero.image_ids)
            names = [io.omero_output_name(image_id, name) for image_id, name in listed]
            images = [RunImage(name, name, image_id) for name, (image_id, _) in zip(names, listed)]
    except (ValueError, ConnectionError) as error:
        raise BatchError(str(error)) from None
    if not images:
        raise BatchError(f"OMERO dataset {omero.dataset_id} holds no images.")

    headers = []
    for image in images:
        try:
            headers.append(io.get_omero_image_info(conn, image.source))
        except io.OmeroSessionEnded:
            raise
        except Exception:
            headers.append(None)
    return images, headers


def _check_first_image(config, image, header):
    """Stop when the first image does not fit the layout or lacks a channel of the config."""
    channels = [channel.index for channel in config.channels]
    try:
        if config.run.input.source == "omero":
            if header is None:
                raise io.ImageReadError(f"OMERO image {image.source}: its information cannot be read")
            _check_omero_image(header, config.image.axes, channels)
        else:
            _open_image(config, image.source, channels)
    except io.ImageReadError as error:
        raise BatchError(
            f"The first image cannot be used with these settings: {_one_line(error)}"
        ) from None


def _calibration_subsets(config, images):
    """For each channel to calibrate, the images whose names contain its filter, in run order."""
    known = config.resolved.thresholds if config.resolved is not None else {}
    subsets = {}
    for channel in config.channels:
        if channel.threshold.mode != "calibrated" or channel.index in known:
            continue
        text = channel.threshold.calibration_filter
        subset = [image for image in images if text in image.listed]
        if not subset:
            raise BatchError(
                f"No image name contains `{text}`, the calibration filter of channel "
                f"{channel.index} (`threshold.calibration_filter`)."
            )
        subsets[channel.index] = subset
    return subsets


def _largest_channel(config, headers):
    """Voxels in one channel of the largest image whose header could be read."""
    sizes = [0]
    for header in headers:
        if header is None:
            continue
        if isinstance(header, io.OmeroImageInfo):
            sizes.append(header.size_z * header.size_y * header.size_x)
        else:
            axes = config.image.axes if len(config.image.axes) == len(header.shape) else header.axes
            sizes.append(_voxels_per_channel(header.shape, axes))
    return max(sizes)


def _log_in_to_omero(config):
    """Log in to OMERO as the owner of the session; the password is asked for."""
    from bigfish_pypeline.omero_tools import connect_to_omero

    omero = config.run.input.omero
    if not omero.username.strip():
        raise BatchError("Set your OMERO user name (`run.input.omero.username`).")
    try:
        return connect_to_omero(omero.username, omero.host, omero.port)
    except Exception as error:
        raise BatchError(f"Could not log in to OMERO: {_hide_session_key(_one_line(error), None)}") from None


# -- the run -----------------------------------------------------------------


@dataclass
class _Task:
    """One piece of work for the pool: an image, or an image and channel for calibration."""

    order: int
    image: RunImage
    label: str
    function: object
    arguments: dict
    channel: int | None = None


def _now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _duration(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def _threshold_text(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "none"
    return f"{value:g}"


class _Run:
    """State of one batch run, from the creation of its folder to the end."""

    def __init__(self, config, run_folder, images, label_folder, subsets, thresholds,
                 n_workers, omero, show, image_function, calibration_function):
        self.config = config
        self.run_folder = Path(run_folder)
        self.images = images
        self.label_folder = label_folder
        self.subsets = subsets
        self.thresholds = dict(thresholds)
        self.pool = _WorkerPool(n_workers)
        self.omero = omero
        self.show = show
        self.image_function = image_function
        self.calibration_function = calibration_function
        self.start = time.monotonic()
        self.started_text = _now_text()

        self.step = "images"
        self.status = "running"
        self.message = "The run has started."
        self.in_progress = []
        self.finished = set()
        self.channel_counts = {"done": 0, "failed": 0, "skipped": 0}
        self.calibration_total = 0
        self.calibration_finished = 0
        self.cancel_reason = None
        self.last_progress = 0.0

    # -- log and progress ----------------------------------------------------

    def hide(self, text):
        """Text with the OMERO session key hidden (OMERO runs only)."""
        if self.omero["key"] is None:
            return str(text)
        return _hide_session_key(text, self.omero["key"])

    def log(self, text, details=False):
        """Add a line (or several) to run.log, and show it unless it is details."""
        text = self.hide(text).rstrip()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = text.splitlines() or [""]
        written = [f"{stamp}  {lines[0]}"] + [" " * (len(stamp) + 2) + line for line in lines[1:]]
        with open(self.run_folder / LOG_NAME, "a", encoding="utf-8", newline="\n") as log_file:
            log_file.write("\n".join(written) + "\n")
        if self.show is not None and not details:
            self.show(text)

    def write_progress(self):
        progress = {
            "status": self.status,
            "step": self.step,
            "n_images": len(self.images),
            "n_finished": len(self.finished),
            "in_progress": list(self.in_progress),
            "channels": dict(self.channel_counts),
            "calibration": {"total": self.calibration_total, "finished": self.calibration_finished},
            "workers": self.pool.n_workers,
            "started": self.started_text,
            "updated": _now_text(),
            "message": self.hide(self.message),
        }
        outputs.write_text_replacing(self.run_folder / PROGRESS_NAME, json.dumps(progress, indent=2) + "\n")
        self.last_progress = time.monotonic()

    # -- cancel --------------------------------------------------------------

    def interrupt(self, signum=None, frame=None):
        """Ctrl+C in the main process: the run is cancelled."""
        if self.cancel_reason is None:
            self.cancel_reason = "Ctrl+C was pressed"

    def cancel_requested(self):
        if self.cancel_reason is None and (self.run_folder / CANCEL_NAME).exists():
            self.cancel_reason = "a `cancel` file was found in the run folder"
        return self.cancel_reason is not None

    # -- per-image files -----------------------------------------------------

    def remove_image_files(self, image):
        """Remove every file of an image from `per_image/`, finished or not."""
        for kind in outputs.TABLE_KINDS:
            path = outputs.per_image_path(self.run_folder, image.name, kind)
            for candidate in (path, path.with_name(path.name + outputs.TEMPORARY_SUFFIX)):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass

    def write_failed_image(self, image, reason, runtime=None):
        """Write `_images.csv` for an image the runner marks failed, every channel failed."""
        self.remove_image_files(image)
        source = self.config.segmentation.source if self.label_folder is not None else ""
        rows = [
            outputs.image_row(
                image.name, channel.index, channel.name, "failed",
                reason=reason, threshold_mode=channel.threshold.mode,
                segmentation_source=source, runtime_s=runtime,
            )
            for channel in self.config.channels
        ]
        outputs.write_image_tables(self.run_folder, image.name, outputs.make_images_table(rows))
        return rows

    # -- running tasks in the pool -------------------------------------------

    def run_tasks(self, tasks, on_result, on_error, on_lost_twice):
        """
        Hand tasks to the pool in order, one only when a worker is free.

        on_result(task, result) takes a finished task's result;
        on_error(task, error) takes an error the task function raised;
        on_lost_twice(task) takes a task lost in a second stopped worker.

        Returns None when every task is done, or "cancelled" or "stopped"
        (with self.message set).
        """
        pending = list(tasks)
        running = {}
        lost_before = set()

        while pending or running:
            if self.cancel_requested():
                self.discard(running.values())
                return "cancelled"

            while pending and len(running) < self.pool.n_workers:
                task = pending.pop(0)
                running[self.pool.submit(task.function, **task.arguments)] = task
                self.in_progress.append(task.label)
                self.log(f"{task.label}: started")
                self.write_progress()

            done, _ = wait(list(running), timeout=CHECK_INTERVAL_S, return_when=FIRST_COMPLETED)
            lost = []
            stop_message = None
            for future in sorted(done, key=lambda item: running[item].order):
                task = running.pop(future)
                self.in_progress.remove(task.label)
                try:
                    result = future.result()
                except (BrokenProcessPool, MemoryError):
                    lost.append(task)
                    continue
                except io.OmeroSessionEnded:
                    running[future] = task
                    self.in_progress.append(task.label)
                    stop_message = (
                        "The OMERO session has ended, so no more images can be read. "
                        "Log in again and start a new run."
                    )
                    continue
                except outputs.OutputError as error:
                    running[future] = task
                    self.in_progress.append(task.label)
                    stop_message = f"Results cannot be written: {error}"
                    continue
                except Exception as error:
                    on_error(task, error)
                    continue
                on_result(task, result)

            if stop_message is not None:
                self.discard(running.values())
                self.message = stop_message
                self.log(stop_message)
                return "stopped"

            if lost:
                # Tasks that finished just before the worker stopped are kept.
                for future, task in list(running.items()):
                    if future.done() and not future.cancelled() and future.exception() is None:
                        del running[future]
                        self.in_progress.remove(task.label)
                        on_result(task, future.result())
                lost += list(running.values())
                running.clear()
                self.in_progress.clear()
                self.pool.stop_now()
                lost.sort(key=lambda task: task.order)
                for task in lost:
                    self.discard_files(task)

                twice = [task for task in lost if task.order in lost_before]
                once = [task for task in lost if task.order not in lost_before]
                self.log(
                    "A worker process stopped unexpectedly, probably because it ran out of memory. "
                    f"Lost: {', '.join(task.label for task in lost)}."
                )
                for task in twice:
                    on_lost_twice(task)

                if self.pool.n_workers == 1:
                    self.message = (
                        "A worker process stopped unexpectedly (probably out of memory) while only "
                        "one worker was running, so the run has ended. Finished images are kept. "
                        "Try again with smaller or fewer images, or close other programs."
                    )
                    self.log(self.message)
                    return "stopped"

                self.pool = _WorkerPool(max(1, self.pool.n_workers // 2))
                lost_before.update(task.order for task in once)
                pending = sorted(once + pending, key=lambda task: task.order)
                if once:
                    self.log(
                        f"Starting again with {self.pool.n_workers} worker(s); "
                        f"{', '.join(task.label for task in once)} will be tried once more."
                    )
                else:
                    self.log(f"Going on with {self.pool.n_workers} worker(s).")
                self.write_progress()
            elif done or time.monotonic() - self.last_progress >= PROGRESS_INTERVAL_S:
                self.write_progress()
        return None

    def discard(self, tasks):
        """Stop the workers at once and remove what the tasks in progress have written."""
        tasks = list(tasks)
        self.pool.stop_now()
        for task in tasks:
            self.discard_files(task)
        self.in_progress.clear()
        if tasks:
            self.log(f"Discarded (in progress): {', '.join(task.label for task in tasks)}")

    def discard_files(self, task):
        if task.channel is None:
            self.remove_image_files(task.image)

    # -- calibration pass ----------------------------------------------------

    def calibrate(self):
        """Calibration pass. Returns None when every channel has a threshold,
        otherwise "cancelled" or "stopped"."""
        self.step = "calibration"
        tasks = []
        for image in self.images:
            for channel_index, subset in self.subsets.items():
                if image in subset:
                    tasks.append(_Task(
                        order=len(tasks), image=image, channel=channel_index,
                        label=f"{image.name}, channel {channel_index} (calibration)",
                        function=self.calibration_function,
                        arguments=dict(
                            config=self.config, image_name=image.name, image_source=image.source,
                            channel_index=channel_index, **self.omero_arguments(),
                        ),
                    ))
        self.calibration_total = len(tasks)
        self.log(f"Calibration: automatic thresholds on {len(tasks)} image(s) and channel(s).")
        self.write_progress()
        results = {}

        def on_result(task, result):
            self.calibration_finished += 1
            results[task.order] = result
            for line in result.get("log_lines", []):
                self.log(line, details=not line.startswith(task.image.name))
            if result["threshold"] is None:
                self.log(f"{task.label}: no value ({result['reason']})")
            else:
                self.log(f"{task.label}: automatic threshold {_threshold_text(result['threshold'])}")

        def on_error(task, error):
            reason = self.hide(_one_line(error))
            on_result(task, {"image": task.image.name, "channel": task.channel,
                             "threshold": None, "reason": reason, "log_lines": []})
            self.log("".join(traceback.format_exception(error)), details=True)

        def on_lost_twice(task):
            on_result(task, {"image": task.image.name, "channel": task.channel,
                             "threshold": None, "reason": WORKER_STOPPED_REASON, "log_lines": []})

        stopped = self.run_tasks(tasks, on_result, on_error, on_lost_twice)
        if stopped is not None:
            return stopped

        rows = []
        unusable = []
        for channel_index in self.subsets:
            entries = [results[task.order] for task in tasks if task.channel == channel_index]
            try:
                threshold, table = calibrate_threshold(entries)
            except ValueError:
                threshold = None
                table = [{"image": entry["image"], "threshold": entry["threshold"], "used": False,
                          "reason": entry["reason"] or "no automatic threshold"} for entry in entries]
            for entry in table:
                rows.append({
                    "image": entry["image"], "channel": channel_index,
                    "auto_threshold": entry["threshold"], "used": entry["used"],
                    "reason": entry["reason"] or "",
                })
            if threshold is None:
                unusable.append(channel_index)
                self.log(f"Channel {channel_index}: none of the calibration images gave a usable threshold.")
            else:
                self.thresholds[channel_index] = threshold
                n_used = sum(entry["used"] for entry in table)
                self.log(
                    f"Channel {channel_index}: calibrated threshold {_threshold_text(threshold)} "
                    f"(median of {n_used} image(s); {len(table) - n_used} left out)"
                )
        outputs.write_calibration(self.run_folder, rows)
        if unusable:
            channels = ", ".join(str(index) for index in unusable)
            self.message = (
                f"No calibrated threshold for channel {channels}: none of the calibration images "
                "gave a usable automatic threshold (see calibration.csv). Change the calibration "
                "filter or the threshold settings and run again."
            )
            self.log(self.message)
            return "stopped"
        outputs.add_thresholds_to_run_config(self.run_folder, self.thresholds)
        self.config = self.config.with_resolved([image.listed for image in self.images], self.thresholds)
        return None

    # -- main pass -----------------------------------------------------------

    def omero_arguments(self):
        if self.config.run.input.source != "omero":
            return {}
        return {"omero_host": self.omero["host"], "omero_port": self.omero["port"],
                "omero_key": self.omero["key"]}

    def record_rows(self, image, rows):
        for row in rows:
            self.channel_counts[row["status"]] = self.channel_counts.get(row["status"], 0) + 1
            text = f"{image.name}, channel {row['channel']}: {row['status']}, threshold {_threshold_text(row['threshold'])}"
            if row["status"] == "done":
                counts = [f"{row['n_spots']} spots"]
                if row.get("n_clusters") is not None:
                    counts.append(f"{row['n_clusters']} clusters")
                if row.get("n_cells") is not None:
                    counts.append(f"{row['n_cells']} cells")
                text += ", " + ", ".join(counts)
            else:
                text += f" ({row['reason']})"
            self.log(text)
        if rows and all(row["status"] == "failed" for row in rows):
            self.log(f"{image.name}: failed: {rows[0]['reason']}")
        else:
            self.log(f"{image.name}: finished")
        self.finished.add(image.name)

    def process_images(self):
        self.step = "images"
        tasks = [
            _Task(
                order=order, image=image, label=image.name,
                function=self.image_function,
                arguments=dict(
                    config=self.config, image_name=image.name, image_source=image.source,
                    run_folder=self.run_folder, label_folder=self.label_folder,
                    **self.omero_arguments(),
                ),
            )
            for order, image in enumerate(self.images)
        ]

        def on_result(task, result):
            for line in result.get("log_lines", []):
                self.log(line, details="\n" in line or line.startswith("Traceback"))
            self.record_rows(task.image, result["rows"])

        def on_error(task, error):
            reason = self.hide(_one_line(error))
            self.log("".join(traceback.format_exception(error)), details=True)
            self.record_rows(task.image, self.write_failed_image(task.image, reason))

        def on_lost_twice(task):
            self.record_rows(task.image, self.write_failed_image(task.image, WORKER_STOPPED_REASON))

        return self.run_tasks(tasks, on_result, on_error, on_lost_twice)

    # -- end -----------------------------------------------------------------

    def finish(self, status):
        """Combine the finished images, tidy `per_image/`, log the summary and set the final status."""
        self.step = "end"
        finished = [
            image.name for image in self.images
            if image.name in self.finished and outputs.image_is_complete(self.run_folder, image.name)
        ]
        outputs.combine_tables(self.run_folder, finished)
        for leftover in (self.run_folder / outputs.PER_IMAGE_FOLDER_NAME).glob("*" + outputs.TEMPORARY_SUFFIX):
            try:
                leftover.unlink()
            except OSError:
                pass

        not_processed = len(self.images) - len(finished)
        counts = ", ".join(f"{n} {name}" for name, n in self.channel_counts.items())
        if status == "finished":
            self.message = f"The run finished: {len(finished)} image(s) processed."
        elif status == "cancelled":
            self.message = (
                f"The run was cancelled ({self.cancel_reason}). "
                f"{len(finished)} finished image(s) are kept."
            )
        self.status = status
        self.log(
            f"Summary: {len(finished)} of {len(self.images)} image(s) finished, "
            f"{not_processed} not processed; channels: {counts}. "
            f"Total time {_duration(time.monotonic() - self.start)}."
        )
        if status != "stopped":
            self.log(self.message)
        self.write_progress()


def _set_thread_variables():
    """Set the thread variables to 1 for the workers; returns the old values."""
    old = {name: os.environ.get(name) for name in THREAD_VARIABLES}
    for name in THREAD_VARIABLES:
        os.environ[name] = "1"
    return old


def _restore_variables(old):
    for name, value in old.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@dataclass
class RunPlan:
    """What the checks before a run found.

    images: the RunImage of every image, in run order.
    headers: what could be read of each image's file (None when it cannot be read).
    label_folder: the folder of label files, or None when there is no segmentation.
    subsets: for each channel to calibrate, the images used to calibrate it.
    n_workers, workers_reason, workers_warning: the number of workers, a
        sentence giving the reason, and a sentence saying memory may run
        short (None when it should be fine).
    omero: the host, port and session key of an OMERO run (None values for a local run).
    omero_conn: the OMERO connection of the run, or None.
    owned_conn: the connection the checks logged in, which `close` ends; None
        when the caller brought its own connection.
    """

    images: list
    headers: list
    label_folder: object
    subsets: dict
    n_workers: int
    workers_reason: str
    workers_warning: object
    omero: dict
    omero_conn: object = None
    owned_conn: object = None

    def close(self):
        """End the OMERO session this plan logged in to, if any."""
        conn, self.owned_conn = self.owned_conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def plan_run(config, omero_conn=None):
    """
    Carry out every check made before a run, and return what was found.

    Nothing is created. For OMERO input this logs in (the password is asked
    for) unless `omero_conn` is given; call `close` on the result when done.

    Raises BatchError with a plain message for any problem.
    """
    source = config.run.input.source

    # checks that need only the config
    label_folder = _check_segmentation(config)
    _check_output_folder(config)
    omero = {"host": None, "port": None, "key": None}
    owned_conn = None
    if source == "omero":
        settings = config.run.input.omero
        if config.resolved is None and settings.dataset_id is None and not settings.image_ids:
            raise BatchError("Give an OMERO dataset ID or image IDs (`run.input.omero`).")
        if not settings.host.strip():
            raise BatchError("Set the OMERO server (`run.input.omero.host`).")
        if omero_conn is None:
            omero_conn = owned_conn = _log_in_to_omero(config)

    try:
        if source == "omero":
            omero = {"host": settings.host, "port": settings.port, "key": io.session_key(omero_conn)}
            try:
                images, headers = _omero_images(config, omero_conn)
            except io.OmeroSessionEnded as error:
                raise BatchError(str(error)) from None
        else:
            images, headers = _local_images(config)
        _check_first_image(config, images[0], headers[0])
        subsets = _calibration_subsets(config, images)
        n_workers, workers_reason, workers_warning = choose_workers(
            config.run.workers, len(images), _largest_channel(config, headers),
            os.cpu_count(), psutil.virtual_memory().available, psutil.virtual_memory().total,
        )
    except BaseException:
        if owned_conn is not None:
            try:
                owned_conn.close()
            except Exception:
                pass
        raise
    return RunPlan(images, headers, label_folder, subsets, n_workers, workers_reason,
                   workers_warning, omero, omero_conn, owned_conn)


def run_batch(config, config_file=None, omero_conn=None, show=None,
              image_function=None, calibration_function=None):
    """
    Run every image of a batch, as set out in the config.

    config: the run's Config.
    config_file: path of the config file, written in the log (optional).
    omero_conn: an OMERO connection that is already logged in. When None and
        the input is OMERO, this function logs in (the password is asked for)
        and closes the session at the end.
    show: a function called with each log line (e.g. print), or None.
    image_function, calibration_function: stand-ins for `process_image` and
        `calibration_threshold`, used by the tests.

    Problems found before any image is processed raise BatchError with a
    plain message, and no run folder is made.

    Returns a BatchResult with the run folder, the final status
    ("finished", "cancelled" or "stopped") and a plain message.
    """
    image_function = image_function or process_image
    calibration_function = calibration_function or calibration_threshold

    plan = plan_run(config, omero_conn)
    try:
        try:
            run_folder = outputs.make_run_folder(config)
        except outputs.OutputError as error:
            raise BatchError(str(error)) from None

        thresholds = dict(config.resolved.thresholds) if config.resolved is not None else {}
        run_config = config.with_full_paths().with_resolved([image.listed for image in plan.images], thresholds)
        run = _Run(run_config, run_folder, plan.images, plan.label_folder, plan.subsets, thresholds,
                   plan.n_workers, plan.omero, show, image_function, calibration_function)
        return _run(run, config_file, plan.workers_reason, plan.workers_warning)
    finally:
        plan.close()


def _run(run, config_file, workers_reason, workers_warning):
    """Carry out a run whose folder has been made; returns a BatchResult."""
    config = run.config
    old_variables = _set_thread_variables()
    old_handler = None
    if threading.current_thread() is threading.main_thread():
        old_handler = signal.signal(signal.SIGINT, run.interrupt)
    try:
        run.log(f"Run folder: {run.run_folder}")
        if config_file is not None:
            run.log(f"Config file: {config_file}")
        if config.run.input.source == "omero":
            settings = config.run.input.omero
            where = (f"dataset {settings.dataset_id}" if settings.dataset_id is not None
                     else "the image IDs given")
            run.log(f"Input: OMERO server {run.omero['host']}, {where}")
        else:
            run.log(f"Input folder: {config.full_input_folder()}")
        run.log(f"{len(run.images)} image(s):\n" + "\n".join(f"  {image.listed}" for image in run.images))
        if run.label_folder is not None:
            run.log(f"Label folder: {run.label_folder}")
        outputs.write_run_config(run.run_folder, config, [image.listed for image in run.images], run.thresholds)
        run.log(f"Workers: {workers_reason}.")
        if workers_warning:
            run.log(f"Warning: {workers_warning}")
        for index, value in sorted(run.thresholds.items()):
            run.log(f"Channel {index}: calibrated threshold {_threshold_text(value)}, from the config (not calibrated again)")
        run.write_progress()

        status = None
        if run.subsets:
            status = run.calibrate()
        if status is None:
            status = run.process_images()
        run.pool.close()
        run.finish(status or "finished")
    except BaseException as error:
        run.pool.stop_now()
        run.status = "stopped"
        run.message = f"The run stopped because of an unexpected problem: {_one_line(error)}"
        try:
            run.log(run.message)
            run.log("".join(traceback.format_exception(error)), details=True)
            run.write_progress()
        except Exception:
            pass
        raise
    finally:
        run.pool.stop_now()
        _restore_variables(old_variables)
        if old_handler is not None:
            signal.signal(signal.SIGINT, old_handler)
    return BatchResult(run.run_folder, run.status, run.message)
