"""Batch processing: one image through every step, and a whole batch run.

`process_image` is the function a batch worker runs for one image.
`calibration_threshold` gives one image's automatic threshold for the
calibration pass of the calibrated threshold mode.
`run_batch` runs every image of a batch in a pool of worker processes. With
Cellpose, the main process segments each image before handing it to a worker.
`save_image_results` runs one image the way a batch does, in the calling
program itself, and saves its results in a run folder of the usual layout.
"""

import atexit
import gc
import json
import math
import multiprocessing
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import warnings
from concurrent.futures import FIRST_COMPLETED, CancelledError, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

from bigfish_pypeline import __version__, io
from bigfish_pypeline import outputs
from bigfish_pypeline import segmentation
from bigfish_pypeline import steps
from bigfish_pypeline.cells import border_labels
from bigfish_pypeline.config import parse_config
from bigfish_pypeline.detection import (
    calibrate_threshold,
    detect_spots,
    filter_channel,
    get_spot_radius_px,
)
from bigfish_pypeline.segmentation import LabelFileError, read_label_file_contents
from bigfish_pypeline.steps import ChannelError, get_ndim, get_voxel_size, run_spot_columns

# Problems that stop the whole run rather than one image or channel.
PASS_THROUGH = (io.OmeroSessionEnded, KeyboardInterrupt, MemoryError)

# Keeping the computer awake during a run (see `_KeepAwake`). On macOS this is
# the `caffeinate` program; on Windows it is the system's request that the
# computer stays awake.
CAFFEINATE = "caffeinate"
# how long to wait after starting `caffeinate` to see that it is running
CAFFEINATE_START_WAIT_S = 0.2
CAFFEINATE_STOP_WAIT_S = 5
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
KEEP_AWAKE_LID_NOTE = "a laptop still sleeps when its lid is closed"

NO_AUTO_THRESHOLD_REASON = "no automatic threshold (too few candidate spots)"

# The QC files of an image are drawn in a folder of their own,
# `qc_temporary/<image>/qc/` in the run folder, and moved into `qc/` just
# before the image's tables are written.
QC_TEMPORARY_FOLDER_NAME = "qc_temporary"
# How each interactive final QC page gets plotly's script (see
# qc.write_final_html): "embedded" puts the script inside each page, so that
# a page opens on its own, without an internet connection.
FINAL_HTML_PLOTLY_SCRIPT = "embedded"
NO_ELBOW_PLOT_WARNING = "no elbow plot: too few candidate spots in this channel to draw one"

# Start of the FutureWarning that scikit-image gives each time big-fish's
# decomposition reads `mean_intensity`; it says nothing the user can act on.
MEAN_INTENSITY_WARNING = r"`RegionProperties\.mean_intensity` is deprecated"


def hide_mean_intensity_warning():
    """Hide scikit-image's FutureWarning about `mean_intensity`, and only that warning."""
    warnings.filterwarnings("ignore", message=MEAN_INTENSITY_WARNING, category=FutureWarning)


# OMERO connection of this process, joined once and reused for later images.
_omero = {"conn": None, "session": None}


# ---------------------------------------------------------------------------
# Small helpers shared with the batch runner
# ---------------------------------------------------------------------------


def run_has_clusters(config):
    """True when any channel has cluster detection switched on."""
    return any(channel.clusters.enabled for channel in config.channels)


def channel_qc_wanted(config):
    """True when any QC file of a channel is switched on in `outputs.qc`: the
    elbow plot, the detection plot, the reference spot or the final QC."""
    settings = config.outputs.qc
    return settings.elbow_plot or settings.detection or settings.reference_spot or settings.final != "none"


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


def _keep_omero_connection(conn):
    """Keep `conn` for later images in this process; None means join again next time."""
    _omero["conn"] = conn
    if conn is None:
        _omero["session"] = None


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


def _plane_problem(config, label, n_planes):
    """The reason the planes of `segmentation.z_planes` do not fit an image of
    `n_planes` planes, or None when they do or are not used (no Cellpose, or a
    layout without Z)."""
    planes = config.segmentation.z_planes
    if not uses_cellpose(config) or not planes.chosen or "Z" not in config.image.axes:
        return None
    problem = segmentation.plane_problem(n_planes, (planes.first, planes.last))
    if problem is None:
        return None
    return f"{label}: {problem} (`segmentation.z_planes`)"


def _check_planes(config, label, n_planes):
    """Raise ImageReadError when the planes of `segmentation.z_planes` do not fit the image."""
    problem = _plane_problem(config, label, n_planes)
    if problem is not None:
        raise io.ImageReadError(problem)


def _check_omero_image(info, layout, channels):
    """Raise ImageReadError when an OMERO image's pixel type cannot be used, or the image
    does not fit the layout or lacks a channel."""
    label = f"OMERO image {info.image_id}"
    problem = io.pixel_type_problem(info)
    if problem is not None:
        raise io.ImageReadError(problem)
    if info.size_t > 1:
        raise io.ImageReadError(f"{label}: the image has {info.size_t} time points; only one is accepted")
    if sorted(layout) != sorted(info.axes):
        shape = " × ".join(str(n) for n in info.shape)
        raise io.ImageReadError(f"{label}: the image ({shape}) does not fit the layout {layout}")
    _check_channels(label, channels, info.size_c)


def _open_image(config, image_source, channels, omero_host=None, omero_port=None, omero_key=None,
                notes=None):
    """
    Check that an image can be read with the config's layout and that it holds
    the channels asked for.

    Returns (info, read_channel): the image information from the file header
    or the server, and a function that reads one channel as an array.
    Raises ImageReadError when the image cannot be used.

    For OMERO, the image information and every channel are read through one
    io.OmeroImageReader: if the connection drops, the session is rejoined once
    for the whole image, and a sentence saying so is added to `notes` (a list).
    The connection in use afterwards is kept for later images.
    """
    layout = config.image.axes
    if config.run.input.source == "omero":
        reader = io.OmeroImageReader(
            _omero_connection(omero_host, omero_port, omero_key), int(image_source),
            omero_host, omero_port, omero_key, notes=notes,
        )
        try:
            info = reader.info()
        finally:
            _keep_omero_connection(reader.conn)
        _check_omero_image(info, layout, channels)
        _check_planes(config, f"OMERO image {info.image_id}", info.size_z)

        def read_channel(channel):
            try:
                return reader.channels(layout, [channel])[channel]
            finally:
                _keep_omero_connection(reader.conn)

        return info, read_channel

    path = Path(image_source)
    info = io.get_image_info(path)
    # The pixel type, layout, time points and positions are checked from the file header.
    io.check_image(path, layout)
    sizes = dict(zip(layout, info.shape))
    _check_channels(path.name, channels, sizes.get("C", 1))
    _check_planes(config, path.name, sizes.get("Z", 1))

    def read_channel(channel):
        return io.read_channel(path, layout, channel)

    return info, read_channel


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _one_line(error):
    """Plain one-line reason for an error."""
    text = " ".join(str(error).split())
    if isinstance(error, (io.ImageReadError, LabelFileError, ChannelError,
                          segmentation.SegmentationError, segmentation.CellposeSetupError)):
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


def _process_channel(config, channel, image_name, read_channel, masks, spot_columns, found):
    """
    Steps 1–8 and 10 for one channel, through the functions of `steps`.

    found: a dict filled in as the steps go, so that the threshold and the
    number of detected spots are known even if a later step fails.

    Returns a dict with the status ("done" or "skipped"), the reason, the
    counts, the warnings, and the channel's spots, clusters and cells tables.
    With `outputs.npz` on, a channel that is done also has "arrays": the
    arrays of its `.npz` file, by name. With a QC file of the channel
    switched on, a channel that is done also has "qc": what the QC files are
    drawn from (see _write_channel_qc). The pictures in it are 2D maximum
    projections, made once, so that no second copy of the 3D channel is kept.
    """
    ndim = get_ndim(config)
    voxel_size_yx = get_voxel_size(config)[-1]
    index = channel.index
    warnings = []
    qc_settings = config.outputs.qc
    material = {} if channel_qc_wanted(config) else None

    # a missing calibrated threshold stops the channel before it is read
    steps.threshold_settings(config, channel)

    # step 1: read the channel
    image = read_channel(index)
    if material is not None and qc_settings.final != "none":
        # the final QC is drawn on the channel as read
        material["picture"] = _projection(image)

    # step 2: spot radius
    radius = steps.spot_radius(config, channel)
    spot_radius_px = radius["spot_radius_px"]
    spot_radius_nm = radius["spot_radius_nm"]

    # step 3: background and LoG filter
    filtered = steps.filter_image(config, channel, image, spot_radius_px)
    del image
    rna = filtered["rna"]
    rna_log = filtered["rna_log"]
    del filtered

    # step 4: detection
    detected = steps.detect(
        config, channel, rna_log, spot_radius_px,
        elbow=material is not None and qc_settings.elbow_plot,
    )
    spots = detected["spots"]
    threshold = detected["threshold"]
    found["threshold"] = threshold
    found["n_spots_detected"] = len(spots)
    if detected["warning"]:
        warnings.append(detected["warning"])
    if material is not None and qc_settings.elbow_plot:
        material["elbow"] = {
            key: detected[key]
            for key in ("elbow_thresholds", "elbow_counts", "threshold", "auto_threshold")
        }
    del detected

    result = {
        "threshold": threshold,
        "n_spots_detected": len(spots),
        "warnings": warnings,
        "spots": None,
        "clusters": None,
        "cells": None,
    }

    # bailout
    reason = steps.bailout_reason(config, channel, spots)
    if reason is not None:
        result["status"] = "skipped"
        result["reason"] = reason
        return result

    # step 5: decomposition of dense regions
    decomposed = steps.decompose(config, channel, image_name, rna, spots, spot_radius_nm)
    spots_post_decomposition = decomposed["spots_post_decomposition"]
    if decomposed["warning"]:
        warnings.append(decomposed["warning"])
    if material is not None and decomposed["reference_spot_for_qc"]:
        # None when decomposition was skipped for want of spots or of a reference spot
        material["reference_spot"] = decomposed["reference_spot"]
    del decomposed

    # step 6: subpixel fitting
    fitted = steps.fit_subpixel(config, channel, rna, spots_post_decomposition, spot_radius_nm)

    # step 7: clusters, on the subpixel positions when there are any
    clustered = steps.find_clusters(config, channel, spots_post_decomposition, fitted["spots_subpixel"])

    # step 8: measurements, at the pixel positions
    measured = steps.measure(config, channel, rna, rna_log, spots_post_decomposition, spot_radius_px)
    if material is not None and qc_settings.detection:
        # the detection plot is drawn on the channel after background subtraction, as in v1
        material["detection_picture"] = _projection(rna)
    del rna, rna_log

    # step 10: cell assignment, at the pixel positions
    assigned = steps.assign_to_cells(config, channel, masks, spots_post_decomposition, clustered)
    if masks is not None:
        result["n_cells"] = len(assigned["cells"])

    tables = steps.make_tables(
        config, channel, image_name, spots_post_decomposition, fitted, clustered, measured, assigned,
        spot_columns=spot_columns,
    )
    result["cells"] = tables["cells"]
    result["spots"] = tables["spots"]
    result["clusters"] = tables["clusters"]
    if tables["arrays"] is not None:
        result["arrays"] = tables["arrays"]
    clusters = clustered["clusters"]
    if material is not None:
        material["spots"] = steps.final_positions(spots_post_decomposition, fitted)
        material["clusters"] = None if clusters is None else clusters[:, :ndim]
        material["spot_radius_px"] = spot_radius_px
        material["cluster_radius_px"] = (
            channel.clusters.radius_nm / voxel_size_yx if channel.clusters.enabled else None
        )
        result["qc"] = material
    result["status"] = "done"
    result["reason"] = ""
    result["n_spots"] = len(spots_post_decomposition)
    result["n_clusters"] = 0 if clusters is None else len(clusters)
    return result


# ---------------------------------------------------------------------------
# QC files of one channel
# ---------------------------------------------------------------------------


def _projection(image):
    """Maximum projection of a 3D channel (z, y, x); a 2D channel (y, x) as it is."""
    return image.max(axis=0) if image.ndim == 3 else image


def _qc_problem(name, error):
    """Warning for a QC file that could not be written, naming the file."""
    return f"the QC file {name} could not be written: {_one_line(error)}"


def _write_channel_qc(config, channel, image_name, staging, result, labels, staged):
    """
    Draw the QC files of one channel that is done, as `outputs.qc` asks, into
    `staging`: a folder that stands in for the run folder until the image's
    tables are written (see _move_qc_files).

    result: what _process_channel returned; its "qc" entry holds what the
        files are drawn from, and its tables are used for the final QC.
    labels: the label image (y, x) of the cells, or None.
    staged: a list to which (channel index, path) of each file written is added.

    Each file is written inside its own error handling: a file that cannot
    be written gives a warning naming it, and never fails the channel. Each
    figure is let go as soon as it is saved.

    Returns (warnings, details): warnings for the channel, and the full
    details of each problem for the log.
    """
    settings = config.outputs.qc
    material = result["qc"]
    index, name = channel.index, channel.name
    warnings, details = [], []
    try:
        from bigfish_pypeline import qc
    except PASS_THROUGH:
        raise
    except Exception as error:
        return ([f"the QC files of this channel could not be written: {_one_line(error)}"],
                [traceback.format_exc().rstrip()])

    def attempt(path, write):
        try:
            written = write()
        except PASS_THROUGH:
            raise
        except Exception as error:
            warnings.append(_qc_problem(path.name, error))
            details.append(traceback.format_exc().rstrip())
        else:
            if written is not None:
                staged.append((index, Path(written)))
        finally:
            gc.collect()

    if settings.elbow_plot:
        # the lower limit has no effect on a manual threshold
        lower_limit = channel.threshold.lower_limit if channel.threshold.mode != "manual" else None

        def write_elbow():
            path = qc.write_elbow_plot(
                staging, image_name, material.pop("elbow"), index, channel.threshold.mode,
                lower_limit=lower_limit, channel_name=name,
            )
            if path is None:
                warnings.append(NO_ELBOW_PLOT_WARNING)
            return path

        attempt(qc.elbow_path(staging, image_name, index), write_elbow)

    if settings.detection:
        attempt(qc.detection_path(staging, image_name, index), lambda: qc.write_detection_plot(
            staging, image_name, material.pop("detection_picture"), material["spots"], index,
            material["spot_radius_px"], clusters=material["clusters"],
            cluster_radius_px=material["cluster_radius_px"], channel_name=name,
        ))

    if settings.reference_spot and material.get("reference_spot") is not None:
        attempt(qc.reference_spot_path(staging, image_name, index), lambda: qc.write_reference_spot(
            staging, image_name, index, material.pop("reference_spot"),
        ))

    clusters = result["clusters"] if channel.clusters.enabled else None
    if settings.final == "png":
        attempt(qc.final_png_path(staging, image_name, index), lambda: qc.write_final_qc(
            staging, image_name, material.pop("picture"), result["spots"], clusters,
            result["cells"], labels, index, channel_name=name,
        ))
    elif settings.final == "html":
        attempt(qc.final_html_path(staging, image_name, index), lambda: qc.write_final_html(
            staging, image_name, material.pop("picture"), result["spots"], clusters,
            result["cells"], labels, index, channel_name=name,
            plotly_script=FINAL_HTML_PLOTLY_SCRIPT,
        ))
    return warnings, details


def _move_qc_files(staged, run_folder):
    """
    Move the QC files of an image, drawn in the folder that stands in for the
    run folder, into the run folder's `qc/` folder.

    staged: (channel index, path) of each file drawn.

    Returns (moved, problems): the paths of the files now in `qc/`, and
    (channel index, file name, error) for each file that could not be moved.
    """
    qc_folder = Path(run_folder) / outputs.QC_FOLDER_NAME
    moved, problems = [], []
    try:
        qc_folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        # each file below then gives its own warning
        pass

    for channel, path in staged:
        final = qc_folder / path.name
        try:
            os.replace(path, final)
            moved.append(final)
        except OSError as error:
            problems.append((channel, final.name, error))
    return moved, problems


def _remove_staging(staging):
    """Remove an image's folder of QC files being drawn, and the folder holding
    it when no other image's folder is left in it."""
    shutil.rmtree(staging, ignore_errors=True)
    try:
        staging.parent.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# One image
# ---------------------------------------------------------------------------


def _number(value, kind=int):
    return None if value is None else kind(value)


def process_image(config, image_name, image_source, run_folder, label_folder=None,
                  omero_host=None, omero_port=None, omero_key=None,
                  segmentation_warnings=(), segmentation_error=None):
    """
    Run every pipeline step on one image, channel by channel, and write its tables.

    config: the run's config, with full paths; calibrated thresholds, if any,
        in its `resolved` block.
    image_name: the image's output name, used in the tables and file names.
    image_source: the file path for local input, or the image ID for OMERO.
    run_folder: the run folder; the tables go to its `per_image/` folder,
        the `.npz` files (with `outputs.npz` on) to its `npz/` folder, and
        the QC files switched on in `outputs.qc` to its `qc/` folder.
    label_folder: folder holding `<image>_seglabels.tif`, or None when there
        are no cell results to make.
    omero_host, omero_port, omero_key: the OMERO server and the session key to
        join (OMERO input only). The connection is kept for later images in
        the same process; close it with `close_omero_connection`.
    segmentation_warnings: warnings from segmenting this image with Cellpose
        in the main process. They are added to the `warnings` column but not
        to the log lines, because the main process has logged them already.
    segmentation_error: the one-line reason when Cellpose segmentation of
        this image failed. No label file is read, cell-level results are
        skipped and `segmentation_status` is "failed".

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

    # sentences about a dropped OMERO connection, moved to the log as they come
    notes = []

    def add_notes():
        log_lines.extend(f"{image_name}: {hide(note)}" for note in notes)
        notes.clear()

    segmentation_source = config.segmentation.source if label_folder is not None else ""
    # Warnings for the `warnings` column only (the main process has logged them).
    noted = [hide(warning) for warning in segmentation_warnings]
    segmentation_failed = f"no cell results: segmentation failed: {hide(segmentation_error)}"
    if label_folder is not None and segmentation_error is not None:
        noted.append(segmentation_failed)

    # step 1: open the image, check its voxel sizes and read its labels
    try:
        info, read_channel = _open_image(
            config, image_source, [channel.index for channel in channels],
            omero_host, omero_port, omero_key, notes=notes,
        )
    except PASS_THROUGH:
        raise
    except Exception as error:
        reason = hide(_one_line(error))
        add_notes()
        log_lines.append(f"{image_name}: image failed: {reason}")
        log_lines.append(hide(traceback.format_exc().rstrip()))
        runtime = time.perf_counter() - image_start
        if hide(segmentation_error or "") == reason:
            # Cellpose could not read the image for the same reason: the reason is enough.
            noted = [warning for warning in noted if warning != segmentation_failed]
        # With Cellpose, the image was segmented before it came here, so its
        # segmentation status is kept; label files have not been read yet.
        status = ""
        if label_folder is not None and segmentation_error is not None:
            status = "failed"
        elif (label_folder is not None and config.segmentation.source == "cellpose"
              and segmentation.label_file_path(label_folder, image_name).is_file()):
            status = "done"
        for channel in channels:
            rows.append(outputs.image_row(
                image_name, channel.index, channel.name, "failed",
                reason=reason,
                threshold_mode=channel.threshold.mode,
                segmentation_source=segmentation_source,
                segmentation_status=status,
                warnings=noted,
                runtime_s=runtime,
            ))
        outputs.write_image_tables(run_folder, image_name, outputs.make_images_table(rows))
        return {"image": image_name, "rows": rows, "log_lines": log_lines}

    add_notes()
    image_warnings = []
    voxel_size = get_voxel_size(config)
    voxel_warning = io.check_voxel_sizes(
        info, voxel_size[0] if len(voxel_size) == 3 else None, voxel_size[-1]
    )
    if voxel_warning:
        image_warnings.append(voxel_warning)

    masks = None
    segmentation_status = ""
    files_read = []
    if label_folder is not None and segmentation_error is not None:
        segmentation_status = "failed"
    elif label_folder is not None:
        try:
            masks, data, details = read_label_file_contents(label_folder, image_name, info.shape[-2:])
            segmentation_status = "done"
        except PASS_THROUGH:
            raise
        except Exception as error:
            segmentation_status = "no_labels"
            image_warnings.append(f"no cell results: {_one_line(error)}")
        else:
            if config.segmentation.source == "label_files":
                # A label file given by the user is recorded in run_info.yaml, from
                # the bytes its labels were read from.
                try:
                    files_read.append(outputs.file_record(
                        segmentation.label_file_path(label_folder, image_name), "label file",
                        data=data, details=details,
                    ))
                except Exception as error:
                    log_lines.append(
                        f"{image_name}: warning: the label file could not be recorded in "
                        f"{outputs.RUN_INFO_NAME} ({hide(_one_line(error))})"
                    )
            del data
    for warning in image_warnings:
        log_lines.append(f"{image_name}: warning: {hide(warning)}")
    if masks is not None and config.segmentation.drop_border_cells:
        log_lines.append(f"{image_name}: {_border_cells_text(masks)}")

    staging = run_folder / QC_TEMPORARY_FOLDER_NAME / image_name
    try:
        result = _process_channels(
            config, image_name, run_folder, read_channel, masks, staging, segmentation_source,
            segmentation_status, noted, image_warnings, rows, log_lines, add_notes, hide,
        )
    finally:
        if channel_qc_wanted(config):
            _remove_staging(staging)
    result["files_read"] = files_read
    return result


def _border_cells_text(masks):
    """How many cells a label image holds and how many are kept with `drop_border_cells` on, for the log."""
    labels = np.unique(masks)
    found = int(np.count_nonzero(labels))
    on_border = len(border_labels(masks))
    return (
        f"{_count_text(found, 'cell')} in the label image, {found - on_border} kept "
        f"({on_border} touching the image border left out, as `segmentation.drop_border_cells` is on)"
    )


def _count_text(number, singular, plural=None):
    """A number and its noun, e.g. "1 cluster" or "6 clusters"."""
    return f"{number} {singular if number == 1 else (plural or singular + 's')}"


def _process_channels(config, image_name, run_folder, read_channel, masks, staging,
                      segmentation_source, segmentation_status, noted, image_warnings, rows,
                      log_lines, add_notes, hide):
    """
    Steps 2–8 and 10 for each channel of an image that could be opened, then
    the image's QC files and tables (see process_image).

    The QC files of each channel are drawn in `staging` as soon as the
    channel is done. Once every channel is done they are moved into `qc/`,
    and then the tables are written, `_images.csv` last, so the image counts
    as finished only once all its files are there. If the tables cannot be
    written, the image's QC files are removed again.
    """
    channels = config.channels
    spot_columns = run_spot_columns(config)
    spot_tables, cluster_tables, cell_tables = [], [], []
    arrays = {}
    staged = []
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
            add_notes()
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
                warnings=noted + image_warnings,
                runtime_s=time.perf_counter() - channel_start,
            ))
            continue

        add_notes()
        qc_details = []
        if result.get("qc") is not None:
            qc_warnings, qc_details = _write_channel_qc(
                config, channel, image_name, staging, result, masks, staged
            )
            result["warnings"].extend(qc_warnings)
            del result["qc"]
        for warning in result["warnings"]:
            log_lines.append(f"{label}: warning: {hide(warning)}")
        log_lines.extend(hide(text) for text in qc_details)
        if result["status"] == "skipped":
            log_lines.append(f"{label}: skipped: {result['reason']}")
        for tables, kind in ((spot_tables, "spots"), (cluster_tables, "clusters"), (cell_tables, "cells")):
            if result[kind] is not None:
                tables.append(result[kind])
        if result.get("arrays") is not None:
            arrays[channel.index] = result["arrays"]
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
            warnings=noted + image_warnings + [hide(warning) for warning in result["warnings"]],
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

    moved = []
    if staged:
        moved, problems = _move_qc_files(staged, run_folder)
        for channel_index, name, error in problems:
            warning = _qc_problem(name, error)
            log_lines.append(f"{image_name}, channel {channel_index}: warning: {hide(warning)}")
            for row in rows:
                if row["channel"] == channel_index:
                    row["warnings"] = "; ".join(text for text in (row["warnings"], hide(warning)) if text)
    try:
        outputs.write_image_tables(
            run_folder, image_name, outputs.make_images_table(rows),
            spots=spots_table, clusters=clusters_table, cells=cells_table, arrays=arrays or None,
        )
    except BaseException:
        for path in moved:
            try:
                path.unlink()
            except OSError:
                pass
        raise
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
    value), "elbow_threshold" (the elbow value before the lower limit, or
    None), "reason" (why there is no value, otherwise None) and "log_lines"
    (full details of a failure). The "image", "threshold" and "reason" keys
    are those detection.calibrate_threshold reads.

    OmeroSessionEnded, KeyboardInterrupt and MemoryError are not caught.
    """
    result = {
        "image": image_name, "channel": channel_index,
        "threshold": None, "elbow_threshold": None, "reason": None, "log_lines": [],
    }

    def hide(text):
        return _hide_session_key(text, omero_key) if config.run.input.source == "omero" else text

    # sentences about a dropped OMERO connection
    notes = []
    try:
        channel = _channel_settings(config, channel_index)
        _, read_channel = _open_image(
            config, image_source, [channel_index], omero_host, omero_port, omero_key, notes=notes,
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
        result["log_lines"] = [f"{image_name}: {hide(note)}" for note in notes] + [
            f"{image_name}, channel {channel_index}: no calibration value: {result['reason']}",
            hide(traceback.format_exc().rstrip()),
        ]
        return result

    result["log_lines"] = [f"{image_name}: {hide(note)}" for note in notes]
    if detected["threshold"] is None:
        result["reason"] = NO_AUTO_THRESHOLD_REASON
    else:
        result["threshold"] = float(detected["threshold"])
        result["elbow_threshold"] = float(detected["auto_threshold"])
    return result


# ---------------------------------------------------------------------------
# Batch run
# ---------------------------------------------------------------------------

# Memory needed by one worker: 38 bytes for each voxel of one channel of the
# largest image (about 5.6 GB for 2048 × 2048 × 35), and never less than 0.5 GB.
BYTES_PER_VOXEL_PER_WORKER = 38
MIN_MEMORY_PER_WORKER = 0.5e9
# Memory kept free for the main process and other programs.
MEMORY_RESERVE = 2e9
# Further memory kept free when the main process segments with Cellpose: with
# the model loaded it holds up to about 2.9 GB while the workers run.
CELLPOSE_MEMORY_RESERVE = 3e9
# Processor threads Cellpose may use on the CPU in the main process (never more
# than the computer has). The workers each use one thread, and `workers: auto`
# leaves these cores to Cellpose.
CELLPOSE_CPU_THREADS = 4

# Label files made by Cellpose, in the run folder: kept in `labels/`, or in a
# temporary folder that is removed at the end when `outputs.label_images` is off.
LABEL_FOLDER_NAME = "labels"
TEMPORARY_LABEL_FOLDER_NAME = "labels_temporary"

LOG_NAME = "run.log"
PROGRESS_NAME = "progress.json"
CANCEL_NAME = "cancel"
CHECK_INTERVAL_S = 1
PROGRESS_INTERVAL_S = 10
THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
WORKER_STOPPED_REASON = "worker stopped unexpectedly, probably out of memory"
UNEXPECTED_PROBLEM_TEXT = "The run stopped because of an unexpected problem"
OMERO_SESSION_ENDED_MESSAGE = (
    "The OMERO session has ended, so no more images can be read. "
    "Log in again and start a new run."
)


class BatchError(Exception):
    """A problem found before any image is processed, with a plain message."""


class RunStoppedError(Exception):
    """A run that stopped because of an unexpected problem, after its run folder was made.

    run_folder: the run folder; its `run.log` holds the full details.
    reason: the problem in one line, with any OMERO session key hidden.
    """

    def __init__(self, run_folder, reason):
        self.run_folder = Path(run_folder)
        self.reason = reason
        super().__init__(
            f"{UNEXPECTED_PROBLEM_TEXT}: {reason}\n"
            f"The details are in {LOG_NAME} in the run folder: {self.run_folder}"
        )


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


def cellpose_threads(cpu_count):
    """Processor threads for Cellpose on the CPU: CELLPOSE_CPU_THREADS, or fewer on a small computer."""
    return max(1, min(CELLPOSE_CPU_THREADS, cpu_count or 1))


def worker_cores(cpu_count, cellpose_on_cpu=False):
    """Processor cores `workers: auto` may give to workers: all but one, or all
    but the Cellpose threads when Cellpose runs on the CPU; at least one."""
    cpu_count = cpu_count or 1
    kept = cellpose_threads(cpu_count) if cellpose_on_cpu else 1
    return max(1, cpu_count - kept)


def memory_reserve(cellpose=False):
    """Memory in bytes kept free, besides the workers; larger when Cellpose runs in the main process."""
    return MEMORY_RESERVE + (CELLPOSE_MEMORY_RESERVE if cellpose else 0)


def choose_workers(requested, n_images, voxels_per_channel, cpu_count, available_memory,
                   total_memory=None, cellpose=False, cellpose_on_cpu=False):
    """
    Number of worker processes for a run.

    requested: `run.workers` from the config, "auto" or a whole number.
    n_images: number of images in the run.
    voxels_per_channel: voxels in one channel of the largest image.
    cpu_count: number of processor cores (None when not known).
    available_memory: memory available now, in bytes.
    total_memory: memory of the computer, in bytes (None: taken to be the
        available memory).
    cellpose: True when the main process segments with Cellpose; the
        reserve then also covers the model (see memory_reserve).
    cellpose_on_cpu: True when Cellpose is known to run on the CPU; "auto"
        then leaves its threads' cores free (see worker_cores).

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
    reserve = memory_reserve(cellpose)
    usable = available_memory - reserve
    fit_in_memory = int(usable // per_worker) if usable > 0 else 0
    reserve_text = f"{_gb(reserve)} kept free"
    if cellpose:
        reserve_text += f" (including {_gb(CELLPOSE_MEMORY_RESERVE)} for the Cellpose model)"
    memory_text = (
        f"{_gb(available_memory)} of memory available, {reserve_text}, "
        f"about {_gb(per_worker)} per worker"
    )
    n_images = max(1, n_images)

    if requested == "auto":
        if fit_in_memory < 1:
            if total_memory is None:
                total_memory = available_memory
            if total_memory - reserve < per_worker:
                raise BatchError(
                    f"There is not enough memory for one worker: this computer has "
                    f"{_gb(total_memory)} of memory, and a worker needs about {_gb(per_worker)} "
                    f"with {reserve_text}. Use a computer with more memory, "
                    "or smaller images."
                )
            reason = f"1 worker(s), chosen automatically: {memory_text} (room for 0)"
            warning = (
                f"little memory is available at the moment ({memory_text}). The run goes on "
                "with one worker, but may be slow. Closing other programs frees memory."
            )
            return 1, reason, warning
        cores = worker_cores(cpu_count, cellpose_on_cpu)
        n_workers = max(1, min(cores, fit_in_memory, n_images))
        left_text = "one left for the main process"
        if cellpose_on_cpu:
            left_text = f"{cellpose_threads(cpu_count)} left for Cellpose on the CPU"
        reason = (
            f"{n_workers} worker(s), chosen automatically: {cpu_count or 1} processor cores "
            f"({left_text}) and {memory_text} (room for {fit_in_memory}); "
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
    process, the OMERO session is left when the process ends, and omero-py
    can neither print its own messages nor set up logging for the process, and
    scikit-image's warning about `mean_intensity` is hidden."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    io.start_plain_logging()
    hide_mean_intensity_warning()
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


class _CallingProcess:
    """
    Takes the place of the pool of workers when one image is processed in the
    calling program itself (see save_image_results): no process is started.

    A task handed over is carried out by `carry_out`, called just before the
    run waits for results. An error of the task is kept as its result, as a
    worker's would be; KeyboardInterrupt and MemoryError are raised at once.
    """

    n_workers = 1

    def __init__(self):
        self._waiting = {}

    def submit(self, function, **arguments):
        future = Future()
        self._waiting[future] = (function, arguments)
        return future

    def carry_out(self, futures):
        """Carry out, one after the other, the tasks among `futures` not yet done."""
        for future in futures:
            call = self._waiting.pop(future, None)
            if call is None:
                continue
            function, arguments = call
            try:
                result = function(**arguments)
            except MemoryError:
                raise
            except Exception as error:
                future.set_exception(error)
            else:
                future.set_result(result)

    def stop_now(self):
        """Drop the tasks not yet carried out."""
        for future in self._waiting:
            future.cancel()
        self._waiting.clear()

    def close(self):
        self.stop_now()


# -- checks before the run ---------------------------------------------------


def uses_cellpose(config):
    """True when the run segments the cells with Cellpose."""
    return config.segmentation.enabled and config.segmentation.source == "cellpose"


def _check_segmentation(config):
    """The folder of label files given by the user, or None when there is none
    (segmentation off, or labels made by Cellpose during the run)."""
    settings = config.segmentation
    if not settings.enabled:
        return None
    if settings.source == "cellpose":
        try:
            segmentation.describe_pretreatment(**_pretreatment_settings(config))
        except ValueError as error:
            raise BatchError(f"Segmentation settings: {error}") from None
        return None
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
    """Images of a local run, the header of each (None when it cannot be read) and,
    for a header that cannot be read, the reason (else None)."""
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
    headers, reasons = [], []
    for path in paths:
        try:
            headers.append(io.get_image_info(path))
            reasons.append(None)
        except Exception as error:
            headers.append(None)
            reasons.append(_one_line(error))
    return images, headers, reasons


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
    """Images of an OMERO run, the information of each (None when it cannot be read)
    and, for information that cannot be read, the reason (else None)."""
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

    headers, reasons = [], []
    for image in images:
        try:
            headers.append(io.get_omero_image_info(conn, image.source))
            reasons.append(None)
        except io.OmeroSessionEnded:
            raise
        except Exception as error:
            headers.append(None)
            reasons.append(_hide_session_key(
                f"OMERO image {image.source}: its information cannot be read ({_one_line(error)})", None
            ))
    return images, headers, reasons


def _needed_channels(config):
    """The channels the run reads: the FISH channels, and the segmentation channel when
    Cellpose is used."""
    channels = [channel.index for channel in config.channels]
    if uses_cellpose(config) and config.segmentation.channel not in channels:
        channels.append(config.segmentation.channel)
    return channels


def _image_problem(config, header, reason=None, channels=None):
    """
    The reason an image cannot be used with the settings, or None when it can,
    found from its header with the same checks the run makes: the pixel type,
    the layout, the channels (see _needed_channels) and, with Cellpose, the
    planes of `segmentation.z_planes`. A TIFF file is checked by the reader
    itself (io.check_image), which reads the file header only.

    header: the image's ImageInfo or OmeroImageInfo, or None when it could
        not be read; `reason` then gives why.
    """
    if header is None:
        return reason or "the image information cannot be read"
    if channels is None:
        channels = _needed_channels(config)
    layout = config.image.axes
    try:
        if isinstance(header, io.OmeroImageInfo):
            _check_omero_image(header, layout, channels)
            _check_planes(config, f"OMERO image {header.image_id}", header.size_z)
        else:
            io.check_image(header.path, layout, channels)
            sizes = dict(zip(layout, header.shape))
            _check_planes(config, Path(header.path).name, sizes.get("Z", 1))
    except io.ImageReadError as error:
        return _one_line(error)
    return None


def _image_problems(config, headers, reasons):
    """The reason each image cannot be used, or None (see _image_problem). Raises
    BatchError when no image can be used, so that settings that fit no image stop
    the run before it starts."""
    channels = _needed_channels(config)
    problems = [_image_problem(config, header, reason, channels)
                for header, reason in zip(headers, reasons)]
    if all(problem is not None for problem in problems):
        raise BatchError(
            f"None of the images can be used with these settings. The first image: {problems[0]}"
        )
    return problems


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


def _will_be_refused(config, header):
    """True when an image's header shows that the run will refuse the image (see _image_problem)."""
    return header is None or _image_problem(config, header) is not None


def _largest_channel(config, headers, problems=None):
    """Voxels in one channel of the largest image whose header could be read,
    leaving out the images the run will refuse.

    problems: the reason each image cannot be used, or None (see
    _image_problems); found from the headers when not given.
    """
    if problems is None:
        problems = [_image_problem(config, header) for header in headers]
    sizes = [0]
    for header, problem in zip(headers, problems):
        if header is None or problem is not None:
            continue
        if isinstance(header, io.OmeroImageInfo):
            sizes.append(header.size_z * header.size_y * header.size_x)
        else:
            sizes.append(_voxels_per_channel(header.shape, config.image.axes))
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


# -- Cellpose in the main process --------------------------------------------


def _pretreatment_settings(config):
    """The pre-treatment settings of the config, as arguments of segmentation.pretreat_channel."""
    settings = config.segmentation
    return dict(
        projection=settings.projection,
        clip=settings.clip.enabled,
        clip_value=settings.clip.value,
        background=settings.background.enabled,
        bg_method=settings.background.method,
        bg_radius=settings.background.radius_px,
        median_px=settings.median_px,
        gaussian_sigma_px=settings.gaussian_sigma_px,
        z_planes=(settings.z_planes.first, settings.z_planes.last),
    )


@dataclass
class CellposeSetup:
    """The device and the loaded Cellpose model of a run.

    device: "cuda", "mps" or "cpu".
    report: a sentence for the log naming the device.
    warnings: sentences for the log (a GPU passed over; slow on the CPU).
    threads: processor threads Cellpose may use on the CPU.
    load_seconds: time taken to choose the device and load the model; None
        when the model was loaded before the run, or the cells were found
        before it (see save_image_results).
    model_file: the record of a model file of the user's own (see
        outputs.file_record), or None for one of Cellpose's models.
    """

    model_name: str
    model: object
    device: str
    report: str
    warnings: list
    threads: int
    load_seconds: float
    model_file: dict | None = None

    def release(self):
        """Let go of the model and hand the GPU memory it used back to the computer."""
        self.model = None
        gc.collect()
        if self.device in ("cuda", "mps"):
            try:
                import torch
                if self.device == "cuda":
                    torch.cuda.empty_cache()
                else:
                    torch.mps.empty_cache()
            except Exception:
                pass


def prepare_cellpose(config, device_chooser=None, model_loader=None):
    """
    Choose and test the device, and load the Cellpose model once for the run.

    device_chooser, model_loader: stand-ins for segmentation.choose_device
        and segmentation.load_cellpose_model, used by the tests.

    While this runs, the thread variables (OMP_NUM_THREADS and the others)
    are set to the number of threads Cellpose may use: when PyTorch is
    loaded while they are 1, it stays on one thread whatever it is told later.

    Returns a CellposeSetup. Raises BatchError with the plain message of a
    CellposeSetupError when the device or the model cannot be used.
    """
    device_chooser = device_chooser or segmentation.choose_device
    model_loader = model_loader or segmentation.load_cellpose_model
    settings = config.segmentation
    threads = cellpose_threads(os.cpu_count())
    started = time.perf_counter()
    # A model file given by its path is recorded before it is loaded; a model
    # added in the Cellpose window is found only once Cellpose is loaded.
    model_path = segmentation.custom_model_file(settings.cellpose.model)
    model_file = model_state = None
    if model_path is not None:
        model_file, model_state = _model_file_record(model_path)
    old_variables = _set_thread_variables(str(threads))
    try:
        device, report, warnings = device_chooser(settings.device)
        model = model_loader(settings.cellpose.model, device, threads=threads)
    except segmentation.CellposeSetupError as error:
        raise BatchError(_one_line(error)) from None
    finally:
        _restore_variables(old_variables)
    load_seconds = time.perf_counter() - started
    warnings = list(warnings)
    if model_path is None:
        model_path = segmentation.custom_model_file(settings.cellpose.model)
        if model_path is not None:
            model_file, _ = _model_file_record(model_path)
    elif _file_state(model_path) != model_state:
        try:
            model_file = outputs.file_record(model_path, "Cellpose model")
        except OSError:
            warnings.append(
                f"The Cellpose model file {model_path} changed while it was being loaded and can "
                f"no longer be read. {outputs.RUN_INFO_NAME} records it as it was before loading."
            )
        else:
            warnings.append(
                f"The Cellpose model file {model_path} changed while it was being loaded. "
                f"{outputs.RUN_INFO_NAME} records it as it was after loading, which may not be "
                "the model used."
            )
    return CellposeSetup(
        model_name=settings.cellpose.model, model=model, device=device, report=report,
        warnings=warnings, threads=threads, load_seconds=load_seconds, model_file=model_file,
    )


def _file_state(path):
    """(size, time last changed) of a file, or None when it cannot be found."""
    try:
        details = os.stat(path)
    except OSError:
        return None
    return details.st_size, details.st_mtime_ns


def _model_file_record(model_path):
    """The record of a Cellpose model file of the user's own (see outputs.file_record),
    and its size and date just before it was read (see _file_state)."""
    state = _file_state(model_path)
    try:
        return outputs.file_record(model_path, "Cellpose model"), state
    except OSError as error:
        raise BatchError(f"The Cellpose model file {model_path} could not be read: {error}") from None


class _Segmenter:
    """
    Segments one image at a time with Cellpose, in a background thread of the
    main process, so that the run can go on noticing a cancel, writing
    progress.json and collecting finished images while Cellpose works.

    Cellpose cannot be stopped part way through an image. A segmentation that
    is no longer wanted (cancel or stop) is abandoned: its thread runs on
    until Cellpose is done, but writes nothing more. Files are written while
    holding a lock that `abandon` also takes, so a file is never left half
    written.
    """

    def __init__(self, run, setup):
        self.run = run
        self.setup = setup
        self.pretreatment = _pretreatment_settings(run.config)
        self.pretreatment_text = segmentation.describe_pretreatment(**self.pretreatment)
        self.eval_settings = segmentation.cellpose_eval_settings(run.config.segmentation.cellpose)
        self.write_qc = run.config.outputs.qc.cellpose
        channel = run.config.segmentation.channel
        # the name of the FISH channel of the same number, when there is one
        self.channel_name = next(
            (item.name for item in run.config.channels if item.index == channel and item.name), None
        )
        self.lock = threading.Lock()
        self.abandoned = False
        self.task = None
        self.future = None

    @property
    def busy(self):
        return self.task is not None

    def start(self, task):
        """Start segmenting the task's image."""
        self.task = task
        self.future = Future()
        thread = threading.Thread(
            target=self._segment, args=(task, self.future),
            name=f"Cellpose: {task.label}", daemon=True,
        )
        thread.start()

    def take(self):
        """(task, outcome) of a finished segmentation, or (None, None) when none has finished."""
        if self.task is None or not self.future.done():
            return None, None
        task, outcome = self.task, self.future.result()
        self.task = self.future = None
        return task, outcome

    def abandon(self):
        """Write nothing more, and return the task being segmented (or None)."""
        with self.lock:
            self.abandoned = True
        task, self.task, self.future = self.task, None, None
        return task

    def _write(self, write):
        """Call write() unless the segmentation has been abandoned; True when it was called."""
        with self.lock:
            if self.abandoned:
                return False
            write()
            return True

    def _segment(self, task, future):
        """Read, pre-treat and segment one image, then write its label file and QC figure.

        When the run was given the image's segmentation (see _Run), that is
        used as it is and Cellpose is not run.
        """
        image = task.image
        given = self.run.given_segmentation
        outcome = {"error": None, "details": None, "session_ended": None, "warnings": [],
                   "notes": [], "n_cells": None, "seconds": None, "total_seconds": None,
                   "given": given is not None}
        started = time.perf_counter()
        try:
            result = given
            if result is None:
                channel = self.run.read_segmentation_channel(image, notes=outcome["notes"])
                if channel.ndim == 3:
                    label = (f"OMERO image {image.source}" if self.run.config.run.input.source == "omero"
                             else Path(image.source).name)
                    _check_planes(self.run.config, label, channel.shape[0])
                prepared = segmentation.pretreat_channel(channel, **self.pretreatment)
                del channel
                result = segmentation.segment_cells(self.setup.model, prepared, **self.eval_settings)
                del prepared
            self._write(lambda: segmentation.write_label_file(
                result["masks"], self.run.label_folder, image.name,
                pixel_size_nm=self.run.config.image.voxel_size_nm.yx))
            outcome["n_cells"] = result["n_cells"]
            outcome["seconds"] = result["seconds"]
            if result["warning"]:
                outcome["warnings"].append(result["warning"])
            if self.write_qc:
                try:
                    from bigfish_pypeline import qc
                    self._write(lambda: qc.write_cellpose_qc(
                        self.run.run_folder, image.name, result,
                        self.run.config.segmentation.channel, self.pretreatment_text,
                        self.eval_settings["diameter"], channel_name=self.channel_name,
                    ))
                except Exception as error:
                    outcome["warnings"].append(
                        f"the Cellpose QC figure could not be written: {_one_line(error)}"
                    )
                    outcome["details"] = traceback.format_exc().rstrip()
        except io.OmeroSessionEnded as error:
            outcome["session_ended"] = str(error)
        except Exception as error:
            outcome["error"] = _one_line(error)
            outcome["details"] = traceback.format_exc().rstrip()
        finally:
            outcome["total_seconds"] = time.perf_counter() - started
            future.set_result(outcome)


# -- the run -----------------------------------------------------------------


@dataclass
class _Task:
    """One piece of work for the pool: an image, or an image and channel for calibration.

    ready: False while the image still has to be segmented with Cellpose.
    """

    order: int
    image: RunImage
    label: str
    function: object
    arguments: dict
    channel: int | None = None
    ready: bool = True


def _now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _record_time():
    """Date and time for the run record, with the difference from UTC, e.g. "2026-11-24 10:05:31+00:00"."""
    return datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")


def _duration(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def _write_log(run_folder, text):
    """Add a line (or several) to the run folder's run.log, with the time in front."""
    text = str(text).rstrip()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = text.splitlines() or [""]
    written = [f"{stamp}  {lines[0]}"] + [" " * (len(stamp) + 2) + line for line in lines[1:]]
    with open(Path(run_folder) / LOG_NAME, "a", encoding="utf-8", newline="\n") as log_file:
        log_file.write("\n".join(written) + "\n")


def _channel_problems_text(counts):
    """The failed and skipped channels in words, e.g. "2 channel(s) failed and 1 skipped";
    empty when there are none."""
    failed, skipped = counts.get("failed", 0), counts.get("skipped", 0)
    parts = []
    if failed:
        parts.append(f"{failed} channel(s) failed")
    if skipped:
        parts.append(f"{skipped} skipped" if failed else f"{skipped} channel(s) skipped")
    return " and ".join(parts)


def _threshold_text(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "none"
    return f"{value:g}"


def _system_name():
    """The name of the operating system: Darwin (macOS), Windows or Linux."""
    return platform.system()


def _set_execution_state(flags):
    """Tell Windows what the calling thread needs (`SetThreadExecutionState`).

    Returns the thread's earlier state, or 0 when Windows did not accept the request.
    """
    import ctypes

    function = ctypes.windll.kernel32.SetThreadExecutionState
    function.argtypes = [ctypes.c_uint]
    function.restype = ctypes.c_uint
    return function(flags)


class _KeepAwake:
    """Keeps the computer from going to sleep on its own while a run is going.

    macOS: a `caffeinate` process that is tied to this process, so that it ends
    by itself when this process ends, even if this process is killed.
    Windows: a request to the system that the computer stays awake, made from
    the thread that calls `start` and withdrawn from the same thread by `stop`.
    Linux and other systems: nothing is done.

    `start` returns the line for run.log; a computer that cannot be kept
    awake gives a warning line, never an error. `stop` can be called at any
    time, also when `start` was never called, and more than once.
    """

    def __init__(self):
        self.process = None
        self.requested = False

    def start(self, enabled):
        """Switch keep-awake on when `enabled`; returns the line for run.log."""
        if not enabled:
            return "Keep awake: off (`run.keep_awake` is off), so the computer may go to sleep during the run."
        system = _system_name()
        if system == "Darwin":
            problem = self._start_caffeinate()
        elif system == "Windows":
            problem = self._request_windows()
        elif system == "Linux":
            return ("Keep awake: not available on Linux, so the computer may go to sleep "
                    "during the run.")
        else:
            return ("Keep awake: not available on this system, so the computer may go to sleep "
                    "during the run.")
        if problem is not None:
            return (f"Warning: the computer could not be kept awake ({problem}); the run goes on, "
                    "and the computer may go to sleep.")
        return f"Keep awake: the computer is kept from sleeping on its own until the run ends ({KEEP_AWAKE_LID_NOTE})."

    def _start_caffeinate(self):
        """Start `caffeinate`; returns None, or the reason in one line."""
        program = shutil.which(CAFFEINATE)
        if program is None:
            return f"`{CAFFEINATE}` was not found"
        try:
            # -i: no sleep when the computer is idle; -w: end when this process ends.
            # Its own session keeps a Ctrl+C in the terminal from reaching it.
            process = subprocess.Popen(
                [program, "-i", "-w", str(os.getpid())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as error:
            return _one_line(error)
        try:
            code = process.wait(timeout=CAFFEINATE_START_WAIT_S)
        except subprocess.TimeoutExpired:
            self.process = process
            return None
        return f"`{CAFFEINATE}` stopped at once (exit code {code})"

    def _request_windows(self):
        """Ask Windows to stay awake; returns None, or the reason in one line."""
        try:
            before = _set_execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception as error:
            return _one_line(error)
        if not before:
            return "Windows did not accept the request"
        self.requested = True
        return None

    def stop(self):
        """End keep-awake; does nothing when it was not started."""
        process, self.process = self.process, None
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=CAFFEINATE_STOP_WAIT_S)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            except Exception:
                pass
        if self.requested:
            self.requested = False
            try:
                _set_execution_state(ES_CONTINUOUS)
            except Exception:
                pass


class _Run:
    """State of one batch run, from the creation of its folder to the end."""

    def __init__(self, config, run_folder, images, label_folder, subsets, thresholds,
                 n_workers, omero, show, image_function, calibration_function,
                 cellpose=None, omero_conn=None, start=None, in_process=False,
                 given_segmentation=None):
        """
        label_folder: the folder the workers read label files from: the
            user's folder for label files, a folder in the run folder for
            Cellpose (see LABEL_FOLDER_NAME), or None without segmentation.
        cellpose: the CellposeSetup when the main process segments, else None.
        omero_conn: the OMERO connection of the main process (OMERO runs).
        start: the time the run started (time.monotonic()), shared with the
            run record so that both give the same duration; now when None.
        in_process: True when the images are processed in the calling
            program, one after the other, with no worker process (see
            _CallingProcess and save_image_results).
        given_segmentation: the result of segmentation.segment_cells for the
            run's one image, made before the run; its masks are written as
            the image's label file and Cellpose is not run. None otherwise.
        """
        self.config = config
        self.run_folder = Path(run_folder)
        self.images = images
        self.label_folder = label_folder
        self.subsets = subsets
        self.thresholds = dict(thresholds)
        self.in_process = in_process
        self.given_segmentation = given_segmentation
        self.pool = _CallingProcess() if in_process else _WorkerPool(n_workers)
        self.omero = omero
        self.omero_conn = omero_conn
        self.show = show
        self.image_function = image_function
        self.calibration_function = calibration_function
        self.cellpose = cellpose
        self.segmenter = None
        self.segmenting = None
        self.start = time.monotonic() if start is None else start
        self.started_text = _now_text()
        # set when the run ends (see note_end)
        self.duration = None
        self.ended_text = None
        # the label files given by the user that were read, by path (see outputs.file_record)
        self.files_read = {}

        self.step = "images"
        self.status = "running"
        self.message = "The run has started."
        self.in_progress = []
        self.finished = set()
        # images in which every channel failed, in the order they ended
        self.failed_images = []
        self.channel_counts = {"done": 0, "failed": 0, "skipped": 0}
        self.calibration_total = 0
        self.calibration_finished = 0
        self.cancel_reason = None
        self.last_progress = 0.0
        # each restart of the pool after a worker stopped: time, new number of workers, images lost
        self.restarts = []

    # -- log and progress ----------------------------------------------------

    def hide(self, text):
        """Text with the OMERO session key hidden (OMERO runs only)."""
        if self.omero["key"] is None:
            return str(text)
        return _hide_session_key(text, self.omero["key"])

    def log(self, text, details=False):
        """Add a line (or several) to run.log, and show it unless it is details."""
        text = self.hide(text).rstrip()
        _write_log(self.run_folder, text)
        if self.show is not None and not details:
            self.show(text)

    def write_progress(self):
        progress = {
            "status": self.status,
            "step": self.step,
            "n_images": len(self.images),
            "n_finished": len(self.finished),
            "in_progress": list(self.in_progress),
            "segmenting": self.segmenting,
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
        """Remove every file of an image from `per_image/`, `npz/` and `qc/`, finished
        or not (its Cellpose QC figure apart; see remove_segmentation_files)."""
        outputs.remove_image_files(
            self.run_folder, image.name, [channel.index for channel in self.config.channels]
        )
        self.remove_qc_files(image)

    def remove_qc_files(self, image):
        """Remove the QC files of an image's channels from `qc/`, and the folder
        they are drawn in."""
        if not channel_qc_wanted(self.config):
            return
        shutil.rmtree(self.run_folder / QC_TEMPORARY_FOLDER_NAME / image.name, ignore_errors=True)
        from bigfish_pypeline import qc

        for channel in self.config.channels:
            for path in qc.channel_qc_paths(self.run_folder, image.name, channel.index):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

    def tidy_qc_folder(self, finished):
        """
        Keep in `qc/` the QC files of finished images only, with no temporary
        file. Remove the folder the QC files are drawn in, and `qc/` itself
        when it is empty.
        """
        shutil.rmtree(self.run_folder / QC_TEMPORARY_FOLDER_NAME, ignore_errors=True)
        qc_folder = self.run_folder / outputs.QC_FOLDER_NAME
        if not qc_folder.is_dir():
            return
        for image in self.images:
            if image.name not in finished:
                self.remove_qc_files(image)
        for leftover in qc_folder.glob("*" + outputs.TEMPORARY_SUFFIX):
            try:
                leftover.unlink()
            except OSError:
                pass
        try:
            qc_folder.rmdir()
        except OSError:
            # the folder is not empty
            pass

    def remove_segmentation_files(self, image):
        """Remove an image's label file and Cellpose QC figure made in this run."""
        if self.cellpose is None:
            return
        from bigfish_pypeline import qc

        label_path = segmentation.label_file_path(self.label_folder, image.name)
        qc_path = qc.cellpose_qc_path(self.run_folder, image.name)
        for path in (label_path, segmentation.temporary_label_path(label_path),
                     qc_path, qc.temporary_qc_path(qc_path)):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def remove_temporary_label(self, image):
        """Remove a finished image's label file when label images are not kept."""
        if self.cellpose is None or self.config.outputs.label_images:
            return
        try:
            segmentation.label_file_path(self.label_folder, image.name).unlink()
        except FileNotFoundError:
            pass

    def read_segmentation_channel(self, image, notes=None):
        """Read only the segmentation channel of an image (local file, or OMERO
        through the main process's connection, rejoining the session once if it
        drops; a sentence saying so is added to `notes`, a list)."""
        channel = self.config.segmentation.channel
        layout = self.config.image.axes
        if self.config.run.input.source == "omero":
            host, port, key = self.omero["host"], self.omero["port"], self.omero["key"]
            if self.omero_conn is None:
                # rejoining failed for an earlier image
                self.omero_conn = io.join_session(host, port, key)
            reader = io.OmeroImageReader(self.omero_conn, image.source, host, port, key, notes=notes)
            try:
                return reader.channels(layout, [channel])[channel]
            finally:
                self.omero_conn = reader.conn
        return io.read_channel(image.source, layout, channel)

    def write_failed_image(self, task, reason, runtime=None):
        """Write `_images.csv` for an image the runner marks failed, every channel failed.

        With Cellpose, the image's segmentation status and warnings are kept:
        "failed" with the reason when its segmentation failed, otherwise "done".
        """
        image = task.image
        self.remove_image_files(image)
        source = self.config.segmentation.source if self.label_folder is not None else ""
        status, warnings = "", []
        if self.cellpose is not None:
            warnings = list(task.arguments.get("segmentation_warnings", ()))
            error = task.arguments.get("segmentation_error")
            if error is not None:
                status = "failed"
                warnings.append(f"no cell results: segmentation failed: {error}")
            elif segmentation.label_file_path(self.label_folder, image.name).is_file():
                status = "done"
        rows = [
            outputs.image_row(
                image.name, channel.index, channel.name, "failed",
                reason=reason, threshold_mode=channel.threshold.mode,
                segmentation_source=source, segmentation_status=status,
                warnings=warnings, runtime_s=runtime,
            )
            for channel in self.config.channels
        ]
        outputs.write_image_tables(self.run_folder, image.name, outputs.make_images_table(rows))
        return rows

    # -- running tasks in the pool -------------------------------------------

    def run_tasks(self, tasks, on_result, on_error, on_lost_twice):
        """
        Hand tasks to the pool in order, one only when a worker is free.

        A task that is not ready is first segmented with Cellpose in the main
        process, one image at a time and in order. The next image is
        segmented only when no segmented image is waiting for a worker, so
        segmentation never runs far ahead of the workers.

        on_result(task, result) takes a finished task's result;
        on_error(task, error) takes an error the task function raised;
        on_lost_twice(task) takes a task lost in a second stopped worker.

        Once a reason to stop is found (the OMERO session has ended, or
        results cannot be written), no further result is taken: the workers
        are stopped at once and the files of every task in progress are
        removed, also those of a task lost in the same pass. A finished
        segmentation is looked at before the workers' results of the same
        pass, so a stop it reports keeps those results out too.

        When a worker stops, the pool is started again with half the workers
        (see restart_pool). This also happens when the pool is found broken
        while a task is handed to it; that task stays first in the queue.

        Returns None when every task is done, or "cancelled" or "stopped"
        (with self.message set).
        """
        pending = list(tasks)
        running = {}
        lost_before = set()
        segmenter = self.segmenter

        while pending or running or (segmenter is not None and segmenter.busy):
            if self.cancel_requested():
                self.discard(running.values())
                return "cancelled"

            broken = False
            while pending and pending[0].ready and len(running) < self.pool.n_workers:
                task = pending[0]
                try:
                    future = self.pool.submit(task.function, **task.arguments)
                except BrokenProcessPool:
                    # A worker stopped since the last check; the task stays in the queue.
                    broken = True
                    break
                pending.pop(0)
                running[future] = task
                self.in_progress.append(task.label)
                self.log(f"{task.label}: started")
                self.write_progress()

            if (not broken and segmenter is not None and not segmenter.busy
                    and not any(task.ready for task in pending)):
                task = next((task for task in pending if not task.ready), None)
                if task is not None:
                    pending.remove(task)
                    segmenter.start(task)
                    self.segmenting = task.label
                    self.log(f"{task.label}: segmenting with Cellpose")
                    self.write_progress()

            waiting_for = list(running)
            if segmenter is not None and segmenter.busy:
                waiting_for.append(segmenter.future)
            done = []
            if waiting_for:
                if self.in_process:
                    self.pool.carry_out(waiting_for)
                done, _ = wait(waiting_for, timeout=CHECK_INTERVAL_S, return_when=FIRST_COMPLETED)
                done = [future for future in done if future in running]

            pending, stop_message = self.take_segmentation(pending)
            lost = []
            if stop_message is None:
                lost, stop_message = self.take_results(done, running, on_result, on_error)

            if stop_message is not None:
                self.discard(list(running.values()) + lost)
                self.message = stop_message
                return "stopped"

            if lost or broken:
                pending, stopped = self.restart_pool(
                    running, lost, pending, lost_before, on_result, on_error, on_lost_twice
                )
                if stopped:
                    return "stopped"
            elif done or time.monotonic() - self.last_progress >= PROGRESS_INTERVAL_S:
                self.write_progress()
        return None

    def take_segmentation(self, pending):
        """
        Look at the segmentation that has finished, if any: a segmented image
        joins the queue, in order, ready for a worker.

        Returns (pending, stop_message): the tasks still to do, and the message
        of the stop when the segmentation found a reason to stop the run (the
        OMERO session has ended), else None.
        """
        if self.segmenter is None:
            return pending, None
        task, outcome = self.segmenter.take()
        if task is None:
            return pending, None
        self.segmenting = None
        stop_message = None
        if outcome["session_ended"] is not None:
            stop_message = OMERO_SESSION_ENDED_MESSAGE
        else:
            self.record_segmentation(task, outcome)
            task.ready = True
            pending = sorted(pending + [task], key=lambda item: item.order)
        self.write_progress()
        return pending, stop_message

    def take_results(self, futures, running, on_result, on_error):
        """
        Take the results of finished tasks in order: a result goes to
        on_result, an error the task function raised to on_error.

        Returns (lost, stop_message): the tasks lost with a stopped worker,
        and the message of the stop when a result shows the run must stop
        (the OMERO session has ended, or results cannot be written), else
        None. Once a reason to stop is found, no further result is taken;
        the task that gave it stays in `running`.
        """
        lost = []
        for future in sorted(futures, key=lambda item: running[item].order):
            task = running[future]
            try:
                result = future.result()
            except (BrokenProcessPool, MemoryError, CancelledError):
                self.take_out(running, future)
                lost.append(task)
            except io.OmeroSessionEnded:
                return lost, OMERO_SESSION_ENDED_MESSAGE
            except outputs.OutputError as error:
                return lost, f"Results cannot be written: {error}"
            except Exception as error:
                self.take_out(running, future)
                on_error(task, error)
            else:
                self.take_out(running, future)
                on_result(task, result)
        return lost, None

    def take_out(self, running, future):
        """Take a task whose result has come in out of those in progress."""
        task = running.pop(future)
        self.in_progress.remove(task.label)
        return task

    def restart_pool(self, running, lost, pending, lost_before, on_result, on_error, on_lost_twice):
        """
        After a worker stopped: stop the pool, remove the files of the tasks it
        lost, and start a pool with half the workers; a task lost a second
        time goes to on_lost_twice. With one worker, the run stops instead.

        Tasks that finished after the pass was taken are first looked at as in
        the pass (see take_results): their results and errors are taken, and
        a reason to stop among them stops the run, with nothing tried again.

        Returns (pending, stopped): the tasks still to do, with the tasks lost
        once put back in order, and True when the run has stopped.
        """
        finished = [future for future in running if future.done()]
        more_lost, stop_message = self.take_results(finished, running, on_result, on_error)
        lost = lost + more_lost
        if stop_message is not None:
            self.discard(list(running.values()) + lost)
            self.message = stop_message
            return pending, True

        lost = sorted(lost + list(running.values()), key=lambda task: task.order)
        running.clear()
        self.in_progress.clear()
        self.pool.stop_now()
        for task in lost:
            self.discard_files(task)

        twice = [task for task in lost if task.order in lost_before]
        once = [task for task in lost if task.order not in lost_before]
        text = "A worker process stopped unexpectedly, probably because it ran out of memory."
        if lost:
            text += f" Lost: {', '.join(task.label for task in lost)}."
        else:
            text += " No image was in progress in it."
        self.log(text)
        for task in twice:
            on_lost_twice(task)

        if self.pool.n_workers == 1:
            self.message = (
                "A worker process stopped unexpectedly (probably out of memory) while only "
                "one worker was running, so the run has ended. Finished images are kept. "
                "Try again with smaller or fewer images, or close other programs."
            )
            return pending, True

        self.pool = _WorkerPool(max(1, self.pool.n_workers // 2))
        self.restarts.append({
            "time": _record_time(),
            "workers": self.pool.n_workers,
            "images_lost": [task.label for task in lost],
        })
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
        return pending, False

    def discard(self, tasks):
        """Stop the workers at once, abandon the image being segmented, and remove
        what the tasks in progress have written."""
        tasks = sorted(tasks, key=lambda task: task.order)
        self.pool.stop_now()
        for task in tasks:
            self.discard_files(task)
        self.in_progress.clear()
        labels = [task.label for task in tasks]
        if self.segmenter is not None:
            segmenting = self.segmenter.abandon()
            self.segmenting = None
            if segmenting is not None:
                self.remove_segmentation_files(segmenting.image)
                labels.append(f"{segmenting.label} (being segmented)")
        if labels:
            self.log(f"Discarded (in progress): {', '.join(labels)}")

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
            for entry, found in zip(table, entries):
                rows.append({
                    "image": entry["image"], "channel": channel_index,
                    "auto_threshold": entry["threshold"],
                    "elbow_threshold": found.get("elbow_threshold"),
                    "used": entry["used"], "reason": entry["reason"] or "",
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
        if self.config.outputs.qc.elbow_plot:
            self.write_calibration_plot(rows)
        if unusable:
            channels = ", ".join(str(index) for index in unusable)
            self.message = (
                f"No calibrated threshold for channel {channels}: none of the calibration images "
                "gave a usable automatic threshold (see calibration.csv). Change the calibration "
                "filter or the threshold settings and run again."
            )
            return "stopped"
        outputs.add_thresholds_to_run_config(self.run_folder, self.thresholds)
        self.config = self.config.with_resolved([image.listed for image in self.images], self.thresholds)
        return None

    def write_calibration_plot(self, rows):
        """Write `qc/calibration.png` from the rows of calibration.csv. A plot
        that cannot be written gives a warning in the log; the run goes on."""
        channels = [channel for channel in self.config.channels if channel.index in self.subsets]
        thresholds = {channel.index: self.thresholds[channel.index]
                      for channel in channels if channel.index in self.thresholds}
        lower_limits = {channel.index: channel.threshold.lower_limit for channel in channels}
        names = {channel.index: channel.name for channel in channels if channel.name}
        try:
            from bigfish_pypeline import qc

            qc.write_calibration_plot(
                self.run_folder, outputs.make_calibration_table(rows), thresholds, lower_limits, names
            )
        except Exception as error:
            self.log(f"Warning: {_qc_problem('calibration.png', error)}")
            self.log(traceback.format_exc(), details=True)
        finally:
            gc.collect()

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
                counts = [_count_text(row["n_spots"], "spot")]
                if row.get("n_clusters") is not None:
                    counts.append(_count_text(row["n_clusters"], "cluster"))
                if row.get("n_cells") is not None:
                    counts.append(_count_text(row["n_cells"], "cell"))
                text += ", " + ", ".join(counts)
            else:
                text += f" ({row['reason']})"
            self.log(text)
        if rows and all(row["status"] == "failed" for row in rows):
            self.failed_images.append(image.name)
            self.log(f"{image.name}: failed: {rows[0]['reason']}")
        else:
            self.log(f"{image.name}: finished")
        self.finished.add(image.name)
        self.remove_temporary_label(image)

    def record_segmentation(self, task, outcome):
        """Log how an image's segmentation went, and pass it on to the image's worker."""
        name = task.image.name
        for note in outcome["notes"]:
            self.log(f"{name}: {note}")
        if outcome["error"] is not None:
            reason = self.hide(outcome["error"])
            self.log(f"{name}: segmentation failed: {reason}")
            self.log(outcome["details"], details=True)
            task.arguments["segmentation_error"] = reason
            return
        if outcome.get("given"):
            self.log(
                f"{name}: {outcome['n_cells']} cell(s) found with Cellpose before saving, "
                "used as they are (Cellpose was not run again)"
            )
        else:
            self.log(
                f"{name}: segmented with Cellpose in {outcome['seconds']:.1f} s, "
                f"{outcome['n_cells']} cell(s) ({outcome['total_seconds']:.1f} s with reading, "
                "pre-treatment and saving)"
            )
        for warning in outcome["warnings"]:
            self.log(f"{name}: warning: {warning}")
        if outcome["details"]:
            self.log(outcome["details"], details=True)
        task.arguments["segmentation_warnings"] = [self.hide(warning) for warning in outcome["warnings"]]

    def process_images(self):
        self.step = "images"
        if self.cellpose is not None:
            self.segmenter = _Segmenter(self, self.cellpose)
        tasks = [
            _Task(
                order=order, image=image, label=image.name,
                function=self.image_function,
                arguments=dict(
                    config=self.config, image_name=image.name, image_source=image.source,
                    run_folder=self.run_folder, label_folder=self.label_folder,
                    **self.omero_arguments(),
                ),
                ready=self.segmenter is None,
            )
            for order, image in enumerate(self.images)
        ]

        def on_result(task, result):
            for line in result.get("log_lines", []):
                self.log(line, details="\n" in line or line.startswith("Traceback"))
            for record in result.get("files_read", ()):
                self.files_read.setdefault(record["path"], record)
            self.record_rows(task.image, result["rows"])

        def on_error(task, error):
            reason = self.hide(_one_line(error))
            self.log("".join(traceback.format_exception(error)), details=True)
            self.record_rows(task.image, self.write_failed_image(task, reason))

        def on_lost_twice(task):
            self.record_rows(task.image, self.write_failed_image(task, WORKER_STOPPED_REASON))

        status = self.run_tasks(tasks, on_result, on_error, on_lost_twice)
        if status is not None:
            # A stop can come while an image is being segmented.
            self.discard([])
        return status

    def end_segmentation(self):
        """Abandon any segmentation still going, remove the temporary label
        folder and let go of the Cellpose model."""
        if self.segmenter is not None:
            self.segmenter.abandon()
            self.segmenter = None
        self.segmenting = None
        if self.cellpose is not None and not self.config.outputs.label_images:
            shutil.rmtree(self.label_folder, ignore_errors=True)
        self.cellpose = None

    # -- end -----------------------------------------------------------------

    def log_image_lists(self, finished):
        """Log the images in which every channel failed, and the images not processed."""
        if self.failed_images:
            self.log(f"Images in which every channel failed: {', '.join(self.failed_images)}")
        missing = [image.name for image in self.images if image.name not in finished]
        if missing:
            self.log(f"Images not processed: {', '.join(missing)}")

    def finish(self, status):
        """Combine the finished images, tidy `per_image/`, log the summary and set the final status."""
        self.step = "end"
        finished = [
            image.name for image in self.images
            if image.name in self.finished and outputs.image_is_complete(self.run_folder, image.name)
        ]
        outputs.combine_tables(self.run_folder, finished)
        for folder in (outputs.PER_IMAGE_FOLDER_NAME, outputs.NPZ_FOLDER_NAME):
            for leftover in (self.run_folder / folder).glob("*" + outputs.TEMPORARY_SUFFIX):
                try:
                    leftover.unlink()
                except OSError:
                    pass
        # .npz files are kept only for finished images
        channels = [channel.index for channel in self.config.channels]
        for image in self.images:
            if image.name not in finished:
                for channel in channels:
                    try:
                        outputs.npz_path(self.run_folder, image.name, channel).unlink()
                    except OSError:
                        pass
        # Label files and Cellpose QC figures are kept only for finished images.
        for image in self.images:
            if image.name not in finished:
                self.remove_segmentation_files(image)
        self.tidy_qc_folder(finished)

        not_processed = len(self.images) - len(finished)
        counts = ", ".join(f"{n} {name}" for name, n in self.channel_counts.items())
        problems = _channel_problems_text(self.channel_counts)
        if status == "finished":
            self.message = f"The run finished: {len(finished)} image(s) processed"
            self.message += f"; {problems}. {SEE_TABLES}" if problems else "."
        elif status == "cancelled":
            self.message = (
                f"The run was cancelled ({self.cancel_reason}). "
                f"{len(finished)} finished image(s) are kept"
            )
            self.message += f"; {problems}. {SEE_TABLES}" if problems else "."
        elif problems:
            self.message += f" In the finished images, {problems}. {SEE_TABLES}"
        self.status = status
        self.note_end()
        # The run folder is given again here, so that the message with the
        # counts stays the last line.
        self.log(f"Run folder: {self.run_folder}")
        self.log(
            f"Summary: {len(finished)} of {len(self.images)} image(s) finished, "
            f"{not_processed} not processed; channels: {counts}. "
            f"Total time {_duration(self.duration)}."
        )
        self.log_image_lists(finished)
        self.log(self.message)
        self.write_progress()

    def note_end(self):
        """Note when the run ended and how long it took, for run.log and run_info.yaml alike."""
        self.duration = time.monotonic() - self.start
        self.ended_text = _record_time()


NOT_ENDED = "not ended"
SEE_TABLES = "See images.csv and run.log in the run folder."
NOT_ENDED_MESSAGE = (
    "The run has not ended: it is still going, or it was ended before it could finish "
    "this file (for example when the computer was switched off)."
)
COMMAND_FROM_PYTHON = "started from Python (run_batch), not from the command line"


def _thresholds_for_record(thresholds):
    if not thresholds:
        return "none"
    return {f"channel {index}": float(value) for index, value in sorted(thresholds.items())}


def _hide_in_values(value, key):
    """`value` with the OMERO session key hidden in every text it holds."""
    if isinstance(value, str):
        return _hide_session_key(value, key)
    if isinstance(value, dict):
        return {name: _hide_in_values(item, key) for name, item in value.items()}
    if isinstance(value, list):
        return [_hide_in_values(item, key) for item in value]
    return value


class _RunRecord:
    """The run record `run_info.yaml`: its first part is written when the run
    folder is made, and it is completed when the run ends, however it ends."""

    def __init__(self, config, run_folder, plan, n_workers, workers_reason, cellpose,
                 command, config_file, started_text, start):
        self.run_folder = Path(run_folder)
        self.key = plan.omero["key"]
        self.start = start
        try:
            folder = os.getcwd()
        except OSError:
            folder = outputs.NOT_AVAILABLE
        if config.run.input.source == "omero":
            omero_server = f"{plan.omero['host']}, port {plan.omero['port']}"
        else:
            omero_server = "not used"
        thresholds = config.resolved.thresholds if config.resolved is not None else {}
        self.info = {
            "status": NOT_ENDED,
            "message": NOT_ENDED_MESSAGE,
            "started": started_text,
            "ended": NOT_ENDED,
            "duration": NOT_ENDED,
            "command": command or COMMAND_FROM_PYTHON,
            "started_in_folder": folder,
            "settings_file": str(config_file) if config_file is not None else "not given",
            "pipeline_version": __version__,
            "git_commit": outputs.git_commit() or outputs.NOT_AVAILABLE,
            "python_version": platform.python_version(),
            "package_versions": outputs.package_versions(),
            "operating_system": outputs.operating_system(),
            "processor_cores": os.cpu_count() or outputs.NOT_AVAILABLE,
            "computer_memory": outputs.computer_memory(),
            "cellpose_device": cellpose.device if cellpose is not None else "not used",
            "workers": n_workers,
            "workers_reason": workers_reason,
            "worker_restarts": "none",
            "random_seed": config.run.seed,
            "calibrated_thresholds": _thresholds_for_record(thresholds),
            "omero_server": omero_server,
        }
        # Label files given by the user, and a Cellpose model file of the user's own
        # (not one of Cellpose's models), with their size, date and checksum.
        self.reads_label_files = (
            config.segmentation.enabled and config.segmentation.source == "label_files"
        )
        self.model_files = [cellpose.model_file] if cellpose is not None and cellpose.model_file else []
        if self.reads_label_files:
            self.info["files_read"] = NOT_ENDED
        else:
            self.info["files_read"] = self.model_files or "none"

    def write(self):
        info = self.info if self.key is None else _hide_in_values(self.info, self.key)
        outputs.write_run_info(self.run_folder, info)

    def complete(self, run, error=None):
        """Fill in how the run ended and write the whole file.

        run: the _Run, or None when the run ended before it was set up.
        error: the problem that ended the run, or None.
        A file that cannot be written gives a line in the log; it does not
        change how the run ends.
        """
        if run is not None and run.status != "running":
            status, message = run.status, run.message
        elif isinstance(error, KeyboardInterrupt):
            status, message = "cancelled", "The run was cancelled (Ctrl+C was pressed)."
        elif isinstance(error, BatchError):
            status, message = "stopped", str(error)
        elif error is not None:
            status = "stopped"
            message = f"{UNEXPECTED_PROBLEM_TEXT}: {_one_line(error)}"
        else:
            status, message = "stopped", "The run ended before any image was processed."
        ended, duration = _record_time(), time.monotonic() - self.start
        if run is not None and run.duration is not None:
            # the same figures as the summary line of run.log
            ended, duration = run.ended_text, run.duration
        self.info.update(status=status, message=message, ended=ended, duration=_duration(duration))
        if run is not None:
            self.info["worker_restarts"] = list(run.restarts) or "none"
            self.info["calibrated_thresholds"] = _thresholds_for_record(run.thresholds)
        if self.reads_label_files:
            read = {} if run is None else run.files_read
            self.info["files_read"] = [read[path] for path in sorted(read)] or "none"
        try:
            self.write()
        except Exception as problem:
            if run is not None:
                try:
                    run.log(f"Warning: {outputs.RUN_INFO_NAME} could not be completed: {_one_line(problem)}")
                except Exception:
                    pass


def _set_thread_variables(value="1"):
    """Set the thread variables (1 for the workers by default); returns the old values."""
    old = {name: os.environ.get(name) for name in THREAD_VARIABLES}
    for name in THREAD_VARIABLES:
        os.environ[name] = value
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
    label_folder: the folder of label files given by the user, or None (no
        segmentation, or labels made by Cellpose during the run).
    subsets: for each channel to calibrate, the images used to calibrate it.
    n_workers, workers_reason, workers_warning: the number of workers, a
        sentence giving the reason, and a sentence saying memory may run
        short (None when it should be fine).
    omero: the host, port and session key of an OMERO run (None values for a local run).
    omero_conn: the OMERO connection of the run, or None.
    owned_conn: the connection the checks logged in, which `close` ends; None
        when the caller brought its own connection.
    problems: for each image, the reason it cannot be used, or None when it
        can (see _image_problem).
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
    problems: list = None

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

    Every image is checked from its header (see _image_problem). Images that
    cannot be used fail one by one in the run; only when no image can be used
    does this raise BatchError. With Cellpose, the segmentation channel is
    checked too, but the device is not tested and the model is not loaded;
    the run does that (see prepare_cellpose).

    Nothing is created. For OMERO input this logs in (the password is asked
    for) unless `omero_conn` is given; call `close` on the result when done.

    Raises BatchError with a plain message for any problem.

    While the checks run, omero-py cannot set up logging for the whole program
    (see io.start_plain_logging).
    """
    with io.plain_logging():
        return _plan_run(config, omero_conn)


def _plan_run(config, omero_conn):
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
                images, headers, reasons = _omero_images(config, omero_conn)
            except io.OmeroSessionEnded as error:
                raise BatchError(str(error)) from None
        else:
            images, headers, reasons = _local_images(config)
        problems = _image_problems(config, headers, reasons)
        subsets = _calibration_subsets(config, images)
        n_workers, workers_reason, workers_warning = choose_workers(
            config.run.workers, len(images), _largest_channel(config, headers, problems),
            os.cpu_count(), psutil.virtual_memory().available, psutil.virtual_memory().total,
            cellpose=uses_cellpose(config),
            cellpose_on_cpu=uses_cellpose(config) and config.segmentation.device == "cpu",
        )
    except BaseException:
        if owned_conn is not None:
            try:
                owned_conn.close()
            except Exception:
                pass
        raise
    return RunPlan(images, headers, label_folder, subsets, n_workers, workers_reason,
                   workers_warning, omero, omero_conn, owned_conn, problems)


def run_batch(config, config_file=None, omero_conn=None, show=None,
              image_function=None, calibration_function=None,
              device_chooser=None, model_loader=None, command=None):
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
    device_chooser, model_loader: stand-ins for segmentation.choose_device
        and segmentation.load_cellpose_model, used by the tests.
    command: the command that started the run, written in `run_info.yaml`
        (e.g. the command line). When None, the file says the run was
        started from Python.

    With Cellpose, the device is chosen and tested and the model is loaded
    once, before the run folder is made; the model is let go at the end.

    Problems found before any image is processed raise BatchError with a
    plain message, and no run folder is made. If the folder for the label
    images of a Cellpose run cannot be made, BatchError is raised too; the
    run folder is then left with its run.log and run_info.yaml saying so.

    An unexpected problem during the run raises RunStoppedError, whose
    message gives the problem in one line, with any OMERO session key
    hidden; the full details are in run.log. Ctrl+C outside the run itself
    raises KeyboardInterrupt.

    Returns a BatchResult with the run folder, the final status
    ("finished", "cancelled" or "stopped") and a plain message.

    While the run is in progress, omero-py cannot set up logging for the whole
    program (see io.start_plain_logging), and scikit-image's warning about
    `mean_intensity` is hidden.
    """
    with io.plain_logging(), warnings.catch_warnings():
        hide_mean_intensity_warning()
        return _run_batch(config, config_file, omero_conn, show, image_function,
                          calibration_function, device_chooser, model_loader, command)


def _run_batch(config, config_file, omero_conn, show, image_function, calibration_function,
               device_chooser, model_loader, command=None):
    image_function = image_function or process_image
    calibration_function = calibration_function or calibration_threshold

    plan = plan_run(config, omero_conn)

    def get_cellpose():
        if show is not None:
            show("Getting Cellpose ready: testing the device and loading the model...")
        return prepare_cellpose(config, device_chooser, model_loader)

    return _run_planned(config, plan, config_file, show, image_function, calibration_function,
                        get_cellpose, command)


def _run_planned(config, plan, config_file, show, image_function, calibration_function,
                 get_cellpose, command, in_process=False, given_segmentation=None):
    """
    Carry out a run whose checks have been made (see plan_run), from getting
    Cellpose ready to the end; returns a BatchResult.

    get_cellpose: function called with no argument that gives the run's
        CellposeSetup; called only when the run uses Cellpose.
    in_process, given_segmentation: see _Run. In the calling program, the
        number of workers is not lowered for Cellpose on the CPU.

    The Cellpose setup is let go at the end, and `plan` is closed.
    """
    started_text, start = _record_time(), time.monotonic()
    cellpose = None
    run = None
    try:
        if uses_cellpose(config):
            cellpose = get_cellpose()
        n_workers, workers_reason = plan.n_workers, plan.workers_reason
        if (not in_process and cellpose is not None and cellpose.device == "cpu"
                and config.run.workers == "auto"):
            # the device was chosen automatically, after the workers were counted
            cores = worker_cores(os.cpu_count(), cellpose_on_cpu=True)
            if n_workers > cores:
                n_workers = cores
                workers_reason += (
                    f"; lowered to {cores} because Cellpose runs on the CPU "
                    f"with {cellpose.threads} thread(s)"
                )
        try:
            run_folder = outputs.make_run_folder(config)
        except outputs.OutputError as error:
            raise BatchError(str(error)) from None

        record = _RunRecord(config, run_folder, plan, n_workers, workers_reason, cellpose,
                            command, config_file, started_text, start)
        try:
            record.write()
        except outputs.OutputError as error:
            raise BatchError(str(error)) from None

        ending = None
        stopped = None
        try:
            label_folder = plan.label_folder
            if cellpose is not None:
                name = LABEL_FOLDER_NAME if config.outputs.label_images else TEMPORARY_LABEL_FOLDER_NAME
                label_folder = run_folder / name
                try:
                    label_folder.mkdir()
                except OSError as error:
                    message = (
                        f"The folder for the label images, {label_folder}, could not be made "
                        f"({error}), so the run stopped before any image was processed. Check that "
                        "the output folder can be written to and has free space, then run again."
                    )
                    _write_log(run_folder, _hide_session_key(message, plan.omero["key"]))
                    raise BatchError(message) from None

            thresholds = dict(config.resolved.thresholds) if config.resolved is not None else {}
            run_config = config.with_full_paths().with_resolved([image.listed for image in plan.images], thresholds)
            run = _Run(run_config, run_folder, plan.images, label_folder, plan.subsets, thresholds,
                       n_workers, plan.omero, show, image_function, calibration_function,
                       cellpose=cellpose, omero_conn=plan.omero_conn, start=start,
                       in_process=in_process, given_segmentation=given_segmentation)
            return _run(run, config_file, workers_reason, plan.workers_warning)
        except BaseException as error:
            ending = error
            if not isinstance(error, Exception) or isinstance(error, BatchError):
                raise
            stopped = _unexpected_problem(error, run_folder, run, plan.omero["key"])
        finally:
            record.complete(run, ending)
        # raised here, outside the error handling, so that the original error
        # and its text do not travel with it
        raise stopped
    finally:
        if run is not None and run.omero_conn is not plan.omero_conn:
            # The main process rejoined the session after a drop. Its login
            # connection has been let go, so a session this run logged in to
            # is ended through the new connection.
            if plan.owned_conn is not None and run.omero_conn is not None:
                try:
                    run.omero_conn.close()
                except Exception:
                    pass
            else:
                io.detach_session(run.omero_conn)
        if cellpose is not None:
            cellpose.release()
        plan.close()


def _unexpected_problem(error, run_folder, run, key):
    """RunStoppedError for an unexpected problem in a run, with any OMERO session key hidden.

    When the problem came before the run was set up, it is written to run.log
    here; otherwise `_run` has written it already.
    """
    reason = _one_line(error)
    if key is not None:
        reason = _hide_session_key(reason, key)
    if run is None:
        try:
            details = "".join(traceback.format_exception(error))
            if key is not None:
                details = _hide_session_key(details, key)
            _write_log(run_folder, f"{UNEXPECTED_PROBLEM_TEXT}: {reason}")
            _write_log(run_folder, details)
        except Exception:
            pass
    return RunStoppedError(run_folder, reason)


def _run(run, config_file, workers_reason, workers_warning):
    """Carry out a run whose folder has been made; returns a BatchResult.

    A run in the calling program (run.in_process) starts no worker process,
    so the thread variables are left as they are, and Ctrl+C (or stopping a
    notebook cell) raises KeyboardInterrupt as usual rather than cancelling.
    """
    config = run.config
    old_variables = {}
    old_handler = None
    if not run.in_process:
        old_variables = _set_thread_variables()
        if threading.current_thread() is threading.main_thread():
            old_handler = signal.signal(signal.SIGINT, run.interrupt)
    keep_awake = _KeepAwake()
    try:
        run.log(f"Run folder: {run.run_folder}")
        if config_file is not None:
            run.log(f"Config file: {config_file}")
        else:
            run.log("Config file: none (the settings were passed from Python)")
        if config.run.input.source == "omero":
            settings = config.run.input.omero
            where = (f"dataset {settings.dataset_id}" if settings.dataset_id is not None
                     else "the image IDs given")
            run.log(f"Input: OMERO server {run.omero['host']}, {where}")
        else:
            run.log(f"Input folder: {config.full_input_folder()}")
        run.log(f"{len(run.images)} image(s):\n" + "\n".join(f"  {image.listed}" for image in run.images))
        if run.cellpose is not None:
            _log_cellpose(run)
        elif run.label_folder is not None:
            run.log(f"Label folder: {run.label_folder}")
        outputs.write_run_config(run.run_folder, config, [image.listed for image in run.images], run.thresholds)
        run.log(f"Workers: {workers_reason}.")
        if workers_warning:
            run.log(f"Warning: {workers_warning}")
        run.log(keep_awake.start(config.run.keep_awake))
        run.log(f"QC images: {_qc_images_text(config, bool(run.subsets), run.cellpose is not None)}")
        for channel in config.channels:
            run.log(
                f"FISH channel {_channel_label(channel)}: {_threshold_setting(channel)}; "
                f"{_spot_radius_text(config, channel)}"
            )
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
        run.message = run.hide(f"{UNEXPECTED_PROBLEM_TEXT}: {_one_line(error)}")
        run.note_end()
        try:
            # not shown: the caller is told through the error raised
            run.log(run.message, details=True)
            run.log("".join(traceback.format_exception(error)), details=True)
            run.log(
                f"Summary: {len(run.finished)} of {len(run.images)} image(s) finished before the "
                f"run stopped; channels: {', '.join(f'{n} {name}' for name, n in run.channel_counts.items())}. "
                f"Total time {_duration(run.duration)}.",
                details=True,
            )
            run.write_progress()
        except Exception:
            pass
        raise
    finally:
        keep_awake.stop()
        run.pool.stop_now()
        run.end_segmentation()
        _restore_variables(old_variables)
        if old_handler is not None:
            signal.signal(signal.SIGINT, old_handler)
    return BatchResult(run.run_folder, run.status, run.hide(run.message))


def _qc_images_text(config, calibrates, cellpose):
    """The QC images a run makes, in words, for the log: those switched on in
    `outputs.qc` that apply to the run."""
    settings = config.outputs.qc
    names = []
    if settings.elbow_plot:
        names.append("elbow plot")
        if calibrates:
            names.append("calibration plot")
    if settings.detection:
        names.append("detection plot")
    if settings.reference_spot and any(channel.decomposition.enabled for channel in config.channels):
        names.append("reference spot")
    if settings.final != "none":
        names.append(f"final QC ({settings.final.upper()})")
    if settings.cellpose and cellpose:
        names.append("Cellpose QC figure")
    return ", ".join(names) if names else "none"


def _channel_label(channel):
    return f"{channel.index} ({channel.name})" if channel.name else str(channel.index)


def _threshold_setting(channel):
    """The threshold setting of a channel, in words, for the log."""
    threshold = channel.threshold
    if threshold.mode == "manual":
        return f"manual threshold {_threshold_text(threshold.value)}"
    if threshold.mode == "auto":
        text = "automatic threshold, found for each image"
        if threshold.lower_limit is not None:
            text += f", never below {_threshold_text(threshold.lower_limit)}"
        return text
    return f"calibrated threshold, from the images whose names contain `{threshold.calibration_filter}`"


def _spot_radius_text(config, channel):
    """The spot radius of a channel in pixels, for the log, e.g.
    "spot radius 1.12 px in Z, 0.99 px in Y and X"."""
    microscope = config.microscope
    radius = get_spot_radius_px(
        get_voxel_size(config), channel.ex, channel.em, microscope.NA, microscope.RI, microscope.type
    )
    if len(radius) == 3:
        return f"spot radius {radius[0]:.2f} px in Z, {radius[-1]:.2f} px in Y and X"
    return f"spot radius {radius[-1]:.2f} px in Y and X"


def _log_cellpose(run):
    """Log the segmentation settings, the device, the model and where the labels go."""
    setup = run.cellpose
    settings = run.config.segmentation
    run.log(
        f"Segmentation: Cellpose model {setup.model_name} on channel {settings.channel} "
        f"({segmentation.describe_pretreatment(**_pretreatment_settings(run.config))})."
    )
    run.log(setup.report)
    for warning in setup.warnings:
        run.log(f"Warning: {warning}")
    if setup.load_seconds is not None:
        text = f"Cellpose ready in {setup.load_seconds:.1f} s (device tested and model loaded)"
        if setup.device == "cpu":
            text += f"; it uses {setup.threads} processor thread(s)"
        run.log(text + ".")
    if run.config.outputs.label_images:
        run.log(f"Label images: saved in {run.label_folder}")
    else:
        run.log(
            "Label images: not kept (`outputs.label_images` is off); each is deleted "
            "once its image is finished."
        )


# ---------------------------------------------------------------------------
# The results of one image, saved from the notebook or the app
# ---------------------------------------------------------------------------

IN_PROCESS_WORKERS_REASON = (
    "1 worker(s): the image was processed by the program that saved its results "
    "(no worker process was started)"
)
CELLPOSE_DEVICE_NOT_KNOWN = "not known (the cells were found before saving)"
SAVED_FROM_PYTHON = "saved from Python (save_image_results), not from the command line"


@dataclass
class SavedImage:
    """Outcome of save_image_results.

    run_folder: the run folder.
    status: how the run ended, "finished" or "stopped" (see BatchResult). A
        run is "finished" also when the image or a channel failed; the
        `images` rows say so.
    message: a plain sentence saying how the run ended.
    images: the image's rows of the `images` table, one per channel, as a
        pandas table (empty when the image did not finish).
    """

    run_folder: Path
    status: str
    message: str
    images: object


def save_image_results(config, image, omero_conn=None, cellpose_result=None, cellpose_model=None,
                       command=None, show=None):
    """
    Run one image through every step, exactly as a batch run does, and save
    its results in a new run folder of the usual layout.

    The image is processed in this program itself (for example the
    notebook), without worker processes. The run folder is made where a
    batch run would make it (`run.output_folder`, or `bigfish_results/` in
    the image's folder) and holds the same files as a batch run of this one
    image: the tables, `per_image/`, the label image, the QC files switched
    on in `outputs.qc`, the `.npz` files when switched on, `run_config.yaml`,
    `run_info.yaml`, `progress.json` and `run.log`. Passing `run_config.yaml`
    to `bigfish-pypeline batch` repeats the run.

    config: the settings (a Config). For a local image, the run's input
        folder is the image's folder. A calibrated threshold must already be
        in `resolved.thresholds` (run the calibration first).
    image: the image file (a path), or an OMERO image ID (a whole number).
    omero_conn: for an OMERO image, the connection that is already logged
        in. This function never logs in and never asks for a password.
    cellpose_result: with `segmentation.source: cellpose`, the result of
        segmentation.segment_cells for this image, made with the settings in
        `config`. Its masks are used as they are and saved as the label
        image, and the Cellpose QC figure is drawn from it; Cellpose is not
        run again. When None, Cellpose is run here, as in a batch run.
    cellpose_model: a Cellpose model already loaded (for example in the
        notebook), used instead of loading the model again. It must be the
        model named in `segmentation.cellpose.model`.
    command: the command or notebook that saved the results, written in
        `run_info.yaml`. When None, the file says the results were saved
        from Python.
    show: a function called with each log line (e.g. print), or None.

    Problems found before the image is processed raise BatchError with a
    plain message, and no run folder is made. A failure of the image or of
    one of its channels is recorded in the tables and in `run.log`, as in a
    batch run; it does not raise. An unexpected problem during the run
    raises RunStoppedError, as run_batch does. Ctrl+C, or stopping the
    notebook cell, stops the run and is passed on (KeyboardInterrupt).

    The thread settings of this program are the same afterwards as before.

    Returns a SavedImage with the run folder, the status, a plain message and
    the image's rows of the `images` table.
    """
    with io.plain_logging(), warnings.catch_warnings():
        hide_mean_intensity_warning()
        torch_threads = _torch_threads()
        try:
            return _save_image_results(config, image, omero_conn, cellpose_result, cellpose_model,
                                       command, show)
        finally:
            _restore_torch_threads(torch_threads)


def _save_image_results(config, image, omero_conn, cellpose_result, cellpose_model, command, show):
    config, plan, given = _plan_image(config, image, omero_conn, cellpose_result)

    def get_cellpose():
        if given is not None or cellpose_model is not None:
            return _cellpose_without_loading(config, cellpose_model, cells_given=given is not None)
        if show is not None:
            show("Getting Cellpose ready: testing the device and loading the model...")
        return prepare_cellpose(config)

    # The images are read through the caller's OMERO connection, as a worker
    # reads through its own; a connection made to rejoin the session after a
    # drop is let go at the end.
    omero_before = dict(_omero)
    if plan.omero_conn is not None:
        _omero["conn"] = plan.omero_conn
        _omero["session"] = (plan.omero["host"], int(plan.omero["port"]), plan.omero["key"])
    try:
        result = _run_planned(config, plan, None, show, process_image, calibration_threshold,
                              get_cellpose, command or SAVED_FROM_PYTHON, in_process=True,
                              given_segmentation=given)
    finally:
        if plan.omero_conn is not None:
            if _omero["conn"] is not None and _omero["conn"] is not plan.omero_conn:
                io.detach_session(_omero["conn"])
            _omero.clear()
            _omero.update(omero_before)

    table = result.run_folder / "images.csv"
    images = pd.read_csv(table) if table.is_file() else pd.DataFrame(columns=outputs.IMAGE_COLUMNS)
    return SavedImage(result.run_folder, result.status, result.message, images)


def _changed_config(config, change):
    """Copy of a config after `change(data)` has edited its settings."""
    data = config.to_dict()
    change(data)
    return parse_config(data, config.config_folder)


def _plan_image(config, image, omero_conn, cellpose_result):
    """
    Every check made before a run, for one image (see plan_run).

    Returns (config, plan, given): the config of the run, whose `resolved`
    block names the image; the RunPlan; and the checked segmentation passed
    in, or None. Raises BatchError with a plain message for any problem.
    """
    thresholds = dict(config.resolved.thresholds) if config.resolved is not None else {}
    omero_image = isinstance(image, (int, np.integer)) and not isinstance(image, bool)
    if not omero_image and not isinstance(image, (str, os.PathLike)):
        raise BatchError("Give the image as the path of its file, or as an OMERO image ID (a whole number).")

    if omero_image:
        image_id = int(image)

        def change(data):
            data["run"]["input"]["source"] = "omero"
            data["run"]["input"]["omero"].update(dataset_id=None, image_ids=[image_id])
            data.pop("resolved", None)

        config = _changed_config(config, change)
    else:
        path = Path(os.path.abspath(Path(image).expanduser()))
        if not path.is_file():
            raise BatchError(f"The image {path} does not exist.")

        def change(data):
            data["run"]["input"].update(source="local", folder=str(path.parent))

        config = _changed_config(config, change).with_resolved([path.name], thresholds)

    # checks that need only the config
    label_folder = _check_segmentation(config)
    _check_output_folder(config)
    _check_calibrated_thresholds(config)
    if cellpose_result is not None and not uses_cellpose(config):
        raise BatchError(
            "A Cellpose segmentation was passed in, but these settings do not use Cellpose: "
            "set `segmentation.enabled` to true and `segmentation.source` to `cellpose`."
        )

    omero = {"host": None, "port": None, "key": None}
    if omero_image:
        settings = config.run.input.omero
        if not settings.host.strip():
            raise BatchError("Set the OMERO server (`run.input.omero.host`).")
        if omero_conn is None:
            raise BatchError(
                "An OMERO image needs the OMERO connection that is already logged in "
                "(`omero_conn`). Log in to OMERO first, then save again."
            )
        try:
            key = io.session_key(omero_conn)
        except ConnectionError:
            raise BatchError(
                "The OMERO connection passed in is not logged in. Log in to OMERO first, then save again."
            ) from None
        omero = {"host": settings.host, "port": settings.port, "key": key}
        try:
            images, headers, reasons = _omero_images(config, omero_conn)
        except io.OmeroSessionEnded as error:
            raise BatchError(str(error)) from None
        config = config.with_resolved([images[0].listed], thresholds)
    else:
        images, headers, reasons = _local_images(config)

    problem = _image_problem(config, headers[0], reasons[0])
    if problem is not None:
        raise BatchError(f"The image cannot be used with these settings: {problem}")
    given = None
    if cellpose_result is not None:
        given = _checked_segmentation(config, cellpose_result, _image_size_yx(config, headers[0]))

    plan = RunPlan(images, headers, label_folder, {}, 1, IN_PROCESS_WORKERS_REASON, None, omero,
                   omero_conn if omero_image else None, None, [None])
    return config, plan, given


def _check_calibrated_thresholds(config):
    """Raise BatchError when a channel uses a calibrated threshold whose value is not in
    `resolved.thresholds`: one image cannot be calibrated on its own."""
    known = config.resolved.thresholds if config.resolved is not None else {}
    missing = [str(channel.index) for channel in config.channels
               if channel.threshold.mode == "calibrated" and channel.index not in known]
    if not missing:
        return
    if len(missing) == 1:
        start, value = f"Channel {missing[0]} uses", "it"
    else:
        start, value = f"Channels {', '.join(missing)} use", "them"
    raise BatchError(
        f"{start} a calibrated threshold (`threshold.mode: calibrated`), but the settings hold "
        f"no calibrated value for {value} yet (`resolved.thresholds`). Run the calibration first, "
        "or set `threshold.mode` to `manual` with the threshold value shown in the notebook."
    )


def _image_size_yx(config, header):
    """(Y, X) size of an image, from its header."""
    if isinstance(header, io.OmeroImageInfo):
        return header.size_y, header.size_x
    sizes = dict(zip(config.image.axes, header.shape))
    return sizes["Y"], sizes["X"]


def _checked_segmentation(config, result, size_yx):
    """
    The Cellpose result passed in, checked against the image, with the masks
    as a label image (see segmentation.check_labels) and the number of cells
    counted from them. Raises BatchError when it cannot be used.
    """
    masks = result.get("masks") if isinstance(result, dict) else None
    if masks is None:
        raise BatchError(
            "The Cellpose segmentation passed in holds no masks: pass the result of "
            "`segmentation.segment_cells` for this image."
        )
    try:
        masks = segmentation.check_labels(masks, size_yx, name="Cellpose masks passed in")
    except LabelFileError as error:
        raise BatchError(f"{error}. Pass the masks Cellpose made for this image.") from None
    if config.outputs.qc.cellpose and (result.get("model_input") is None or result.get("flows") is None):
        raise BatchError(
            "The Cellpose segmentation passed in lacks what the Cellpose QC figure is drawn from "
            "(`model_input` and `flows`): pass the whole result of `segmentation.segment_cells`, "
            "or switch off `outputs.qc.cellpose`."
        )
    n_cells = len(np.unique(masks[masks > 0]))
    return {
        "masks": masks,
        "model_input": result.get("model_input"),
        "flows": result.get("flows"),
        "n_cells": n_cells,
        "seconds": result.get("seconds"),
        "warning": segmentation.NO_CELLS_WARNING if n_cells == 0 else None,
    }


def _cellpose_without_loading(config, model, cells_given):
    """
    The CellposeSetup of a run whose model was loaded before it (`model`), or
    whose cells were found before it (`cells_given`; `model` may then be
    None). The device is the model's, or not known without a model.
    """
    settings = config.segmentation
    device = getattr(getattr(model, "device", None), "type", None)
    if device not in segmentation.DEVICE_NAMES:
        device = None
    where = f" on {segmentation.DEVICE_NAMES[device]}" if device is not None else ""
    warnings_found = []
    if cells_given:
        report = (f"Cellpose: the cells found before saving{where} are used as they are; "
                  "Cellpose is not run again.")
    else:
        report = f"Cellpose runs{where}, with the model loaded before saving."
        if device == "cpu":
            warnings_found.append(segmentation.CPU_WARNING)
    model_file = None
    model_path = segmentation.custom_model_file(settings.cellpose.model)
    if model_path is not None:
        model_file, _ = _model_file_record(model_path)
    return CellposeSetup(
        model_name=settings.cellpose.model, model=model,
        device=device or CELLPOSE_DEVICE_NOT_KNOWN, report=report, warnings=warnings_found,
        threads=cellpose_threads(os.cpu_count()), load_seconds=None, model_file=model_file,
    )


def _torch_threads():
    """The number of threads PyTorch uses, or None when PyTorch is not loaded."""
    torch = sys.modules.get("torch")
    if torch is None:
        return None
    try:
        return torch.get_num_threads()
    except Exception:
        return None


def _restore_torch_threads(threads):
    """Set PyTorch back to `threads` threads (see _torch_threads)."""
    if threads is None:
        return
    try:
        torch = sys.modules["torch"]
        if torch.get_num_threads() != threads:
            torch.set_num_threads(threads)
    except Exception:
        pass
