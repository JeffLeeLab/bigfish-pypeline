"""The steps of one channel, one function each, as the batch runs them.

The batch, the Optimise notebook and the app's Optimise page all call these
functions, so a setting means the same thing wherever it is used. The steps
follow spec section 5.1:

    spot_radius        step 2: spot radius from the microscope and wavelengths
    filter_image       step 3: background subtraction and LoG filter
    detect             step 4: spot detection with the channel's threshold
    bailout_reason     step 4: whether the channel is skipped for too many spots
    decompose          step 5: decomposition of dense regions
    fit_subpixel       step 6: subpixel fitting
    find_clusters      step 7: clusters
    measure            step 8: SNR and LoG intensity of each spot
    assign_to_cells    step 10: cell of each spot and cluster, and the cell counts
    make_tables        the spots, clusters and cells tables, and the `.npz` arrays

Each function takes the config (`config.Config`), the channel's settings
(one entry of `config.channels`) and what the step before gave. A step that
is switched off for the channel gives back what the next step needs all the
same (for example the detected spots unchanged when decomposition is off),
so the steps can always be called in this order.

Example, for one channel of one image (`image` is the channel as read, and
`masks` the label image of the cells, or None):

    radius = steps.spot_radius(config, channel)
    filtered = steps.filter_image(config, channel, image, radius["spot_radius_px"])
    detected = steps.detect(config, channel, filtered["rna_log"], radius["spot_radius_px"])
    reason = steps.bailout_reason(config, channel, detected["spots"])
    decomposed = steps.decompose(config, channel, image_name, filtered["rna"],
                                 detected["spots"], radius["spot_radius_nm"])
    spots = decomposed["spots_post_decomposition"]
    fitted = steps.fit_subpixel(config, channel, filtered["rna"], spots, radius["spot_radius_nm"])
    clustered = steps.find_clusters(config, channel, spots, fitted["spots_subpixel"])
    measured = steps.measure(config, channel, filtered["rna"], filtered["rna_log"], spots,
                             radius["spot_radius_px"])
    assigned = steps.assign_to_cells(config, channel, masks, spots, clustered)
    tables = steps.make_tables(config, channel, image_name, spots, fitted, clustered,
                               measured, assigned)
"""

import numpy as np

from bigfish_pypeline import outputs
from bigfish_pypeline.cells import assign_cells
from bigfish_pypeline.clusters import detect_clusters
from bigfish_pypeline.decomposition import NO_SPOT_MODEL_WARNING, decompose_dense_regions, get_seed
from bigfish_pypeline.detection import (
    detect_spots,
    exceeds_bailout,
    filter_channel,
    get_spot_radius_nm,
    get_spot_radius_px,
)
from bigfish_pypeline.measurements import measure_spots
from bigfish_pypeline.subpixel import fit_subpixel as _fit_subpixel


class ChannelError(Exception):
    """A channel that cannot be processed with the settings given, with a plain one-line reason."""


# ---------------------------------------------------------------------------
# Settings read from the config
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


def threshold_settings(config, channel):
    """
    The threshold value and the lower limit that spot detection uses for this channel.

    Reads `channel.threshold`: with mode "manual", its `value`; with "auto",
    its `lower_limit`; with "calibrated", the channel's value in
    `config.resolved.thresholds`, which the calibration pass of a batch run
    fills in.

    Returns (threshold, lower_limit): (value, None) for "manual" and
    "calibrated", (None, lower limit) for "auto".

    Raises ChannelError when the mode is "calibrated" and the config holds
    no calibrated value for the channel.
    """
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


# ---------------------------------------------------------------------------
# Steps of one channel
# ---------------------------------------------------------------------------


def spot_radius(config, channel):
    """
    Step 2: the expected radius of a spot, from the theoretical PSF.

    Reads the voxel sizes (`config.image`), the microscope (`config.microscope`:
    type, NA, RI) and the channel's wavelengths (`channel.ex`, `channel.em`).

    Returns a dict with:
    - "spot_radius_px": one value per image axis, in pixels,
    - "spot_radius_nm": one value per image axis, in nm.
    """
    voxel_size = get_voxel_size(config)
    microscope = config.microscope
    spot_radius_px = get_spot_radius_px(
        voxel_size, channel.ex, channel.em, microscope.NA, microscope.RI, microscope.type
    )
    spot_radius_nm = get_spot_radius_nm(
        voxel_size, channel.ex, channel.em, microscope.NA, microscope.RI, microscope.type
    )
    return {"spot_radius_px": spot_radius_px, "spot_radius_nm": spot_radius_nm}


def filter_image(config, channel, image, spot_radius_px):
    """
    Step 3: background subtraction and LoG filter of one channel.

    image: the channel as read, (z, y, x) or (y, x).
    spot_radius_px: from `spot_radius`.

    Reads `channel.background` (method and radius in pixels).

    Returns a dict with:
    - "rna": the channel after background subtraction,
    - "rna_log": rna after the LoG filter, where spots are found,
    - "rna_mip": maximum projection of rna along z (rna itself in 2D).

    "rna" and "rna_log" are each as large as the channel; let them go as
    soon as the later steps are done with them.
    """
    return filter_channel(
        image, spot_radius_px,
        bg_radius=channel.background.radius_px,
        bg_method=channel.background.method,
    )


def detect(config, channel, rna_log, spot_radius_px, elbow=False):
    """
    Step 4: find the spots of one channel with its threshold.

    rna_log: from `filter_image`.
    spot_radius_px: from `spot_radius`.
    elbow: also give the values of the elbow plot.

    Reads `channel.threshold` (see `threshold_settings`): a manual value, an
    automatic threshold raised to the lower limit, or the calibrated value.

    Returns a dict with:
    - "spots": one row per spot (z, y, x in 3D; y, x in 2D), whole pixels,
    - "threshold": the threshold used, or None when the automatic mode found
      none (then there are no spots),
    - "auto_threshold": the automatic value before the lower limit (automatic
      mode only, otherwise None),
    - "elbow_thresholds", "elbow_counts": the values of the elbow plot, or
      None when `elbow` is False,
    - "warning": a message when no threshold was found, otherwise None.

    Raises ChannelError when a calibrated value is missing.
    """
    threshold, lower_limit = threshold_settings(config, channel)
    return detect_spots(
        rna_log, spot_radius_px,
        threshold_mode=channel.threshold.mode,
        threshold=threshold,
        lower_limit=lower_limit,
        elbow=elbow,
    )


def bailout_reason(config, channel, spots):
    """
    Step 4: whether the channel is skipped because too many spots were found.

    spots: the detected spots, from `detect`.

    Reads `channel.bailout` (switch and largest number of spots).

    Returns the reason the channel is skipped, as written in the images
    table, or None when the channel goes on.
    """
    if channel.bailout.enabled and exceeds_bailout(len(spots), channel.bailout.max_spots):
        return (
            f"bailout: {len(spots)} spots detected, above the limit of "
            f"{channel.bailout.max_spots}"
        )
    return None


def decompose(config, channel, image_name, rna, spots, spot_radius_nm):
    """
    Step 5: split dense regions into single spots.

    image_name: the image's output name; with the channel number and
        `config.run.seed` it sets the random choice of spots for the
        reference spot, so a run gives the same spots every time.
    rna: from `filter_image`.
    spots: the detected spots, from `detect`.
    spot_radius_nm: from `spot_radius`.

    Reads `channel.decomposition` (switch, alpha and beta) and `config.run.seed`.

    Returns a dict with:
    - "spots_post_decomposition": the spots after decomposition; the
      detected spots unchanged when decomposition is off or skipped,
    - "reference_spot": the reference spot built from rna, or None,
    - "reference_spot_for_qc": True when the reference spot belongs in the
      QC file (decomposition is on and a Gaussian could be fitted to it),
    - "warning": a message when decomposition was skipped or less reliable,
      otherwise None.
    """
    if not channel.decomposition.enabled:
        return {
            "spots_post_decomposition": spots,
            "reference_spot": None,
            "reference_spot_for_qc": False,
            "warning": None,
        }
    decomposed = decompose_dense_regions(
        rna, spots, get_voxel_size(config), spot_radius_nm,
        alpha=channel.decomposition.alpha,
        beta=channel.decomposition.beta,
        seed=get_seed(config.run.seed, image_name, channel.index),
    )
    return {
        "spots_post_decomposition": decomposed["spots_post_decomposition"],
        "reference_spot": decomposed["reference_spot"],
        "reference_spot_for_qc": NO_SPOT_MODEL_WARNING not in (decomposed["warning"] or ""),
        "warning": decomposed["warning"],
    }


def fit_subpixel(config, channel, rna, spots, spot_radius_nm):
    """
    Step 6: positions of the spots to a fraction of a pixel.

    rna: from `filter_image`.
    spots: the spots after decomposition, from `decompose`.
    spot_radius_nm: from `spot_radius`.

    Reads `channel.subpixel` (switch).

    Returns a dict with:
    - "spots_subpixel": one row per spot, in the same order as `spots`, in
      pixels with decimals; None when subpixel fitting is off.
    """
    spots_subpixel = None
    if channel.subpixel.enabled:
        spots_subpixel = _fit_subpixel(rna, spots, get_voxel_size(config), spot_radius_nm)
    return {"spots_subpixel": spots_subpixel}


def find_clusters(config, channel, spots, spots_subpixel=None):
    """
    Step 7: group the spots into clusters.

    spots: the spots after decomposition, from `decompose`.
    spots_subpixel: from `fit_subpixel`; when given, the clusters are built
        on these positions instead.

    Reads `channel.clusters` (switch, radius in nm and smallest number of spots).

    Returns a dict with:
    - "spots_post_clustering": the positions used, with one more column
      holding each spot's cluster number; None when clusters are off,
    - "clusters": one row per cluster (centre, number of spots, cluster
      number); None when clusters are off,
    - "cluster_id": the cluster number of each spot, in the order of
      `spots` (-1 outside any cluster, and for every spot when clusters are off).
    """
    clusters = None
    spots_post_clustering = None
    cluster_id = np.full(len(spots), -1, dtype=np.int64)
    if channel.clusters.enabled:
        positions = spots_subpixel if spots_subpixel is not None else spots
        spots_post_clustering, clusters = detect_clusters(
            positions, get_voxel_size(config),
            radius=channel.clusters.radius_nm,
            nb_min_spots=channel.clusters.min_spots,
        )
        cluster_id = spots_post_clustering[:, get_ndim(config)].astype(np.int64)
    return {
        "spots_post_clustering": spots_post_clustering,
        "clusters": clusters,
        "cluster_id": cluster_id,
    }


def measure(config, channel, rna, rna_log, spots, spot_radius_px):
    """
    Step 8: measurements of each spot, at its whole-pixel position.

    rna, rna_log: from `filter_image`.
    spots: the spots after decomposition, from `decompose`.
    spot_radius_px: from `spot_radius`.

    Reads `channel.measurements` (SNR and intensity switches).

    Returns a dict with "snr" and/or "log_intensity", one value per spot,
    for the measurements switched on; an empty dict when both are off.
    """
    if channel.measurements.snr or channel.measurements.intensity:
        return measure_spots(
            rna, rna_log, spots, spot_radius_px,
            snr=channel.measurements.snr,
            intensity=channel.measurements.intensity,
        )
    return {}


def assign_to_cells(config, channel, masks, spots, clustered):
    """
    Step 10: the cell of each spot and cluster, and the counts of each cell.

    masks: the label image of the cells (y, x), or None when there are no
        cells; then nothing is assigned.
    spots: the spots after decomposition, from `decompose`; their
        whole-pixel positions are used.
    clustered: from `find_clusters`.

    Reads `config.segmentation.drop_border_cells`: when on, cells touching
    the image border are left out and their spots and clusters get cell -1.

    Returns a dict with:
    - "spot_cell_id": the cell of each spot (-1 outside any cell),
    - "cluster_cell_id": the cell of each cluster; None when clusters are off,
    - "cells": a table with one row per cell (see `cells.assign_cells`).
    Every entry is None when `masks` is None.
    """
    if masks is None:
        return {"spot_cell_id": None, "cluster_cell_id": None, "cells": None}
    clusters = clustered["clusters"]
    spots_with_cluster = np.column_stack([spots, clustered["cluster_id"]])
    spot_cell_id, cluster_cell_id, cells = assign_cells(
        masks, spots_with_cluster, get_ndim(config), get_voxel_size(config)[-1],
        clusters=clusters,
        drop_border_cells=config.segmentation.drop_border_cells,
    )
    if clusters is None:
        cluster_cell_id = None
    return {"spot_cell_id": spot_cell_id, "cluster_cell_id": cluster_cell_id, "cells": cells}


def make_tables(config, channel, image_name, spots, fitted, clustered, measured, assigned,
                spot_columns=None):
    """
    The channel's spots, clusters and cells tables, as the batch writes them.

    image_name: the image's output name, written in every row.
    spots: the spots after decomposition, from `decompose`.
    fitted, clustered, measured, assigned: from `fit_subpixel`,
        `find_clusters`, `measure` and `assign_to_cells`.
    spot_columns: the columns of the spots table; by default those of a run
        with this config (see `run_spot_columns`).

    Reads `outputs.npz`, and the clusters switch for which arrays go in the
    `.npz` file.

    Returns a dict with:
    - "spots": the spots table,
    - "clusters": the clusters table (no rows when clusters are off),
    - "cells": the cells table, or None when there are no cells,
    - "arrays": the arrays of the channel's `.npz` file by name, or None
      when `outputs.npz` is off.
    """
    ndim = get_ndim(config)
    voxel_size = get_voxel_size(config)
    voxel_size_yx = voxel_size[-1]
    voxel_size_z = voxel_size[0] if ndim == 3 else None
    if spot_columns is None:
        spot_columns = run_spot_columns(config)
    index = channel.index
    spots_subpixel = fitted["spots_subpixel"]
    clusters = clustered["clusters"]

    tables = {"spots": None, "clusters": None, "cells": None, "arrays": None}
    if assigned["cells"] is not None:
        tables["cells"] = outputs.make_cells_table(image_name, index, channel.name, assigned["cells"])
    tables["spots"] = outputs.make_spots_table(
        image_name, index, channel.name, spots, ndim,
        voxel_size_yx, voxel_size_z,
        cluster_id=clustered["cluster_id"],
        cell_id=assigned["spot_cell_id"],
        subpixel=spots_subpixel,
        snr=measured.get("snr"),
        log_intensity=measured.get("log_intensity"),
        columns=spot_columns,
    )
    tables["clusters"] = outputs.make_clusters_table(
        image_name, index, channel.name, clusters, ndim, voxel_size_yx, voxel_size_z,
        cell_id=assigned["cluster_cell_id"],
    )
    if config.outputs.npz:
        # the arrays and names of the v1 scripts: the general script with
        # clusters, the HCRv3 script without
        if channel.clusters.enabled:
            tables["arrays"] = {
                "spots_post_clustering": clustered["spots_post_clustering"],
                "clusters": clusters,
            }
        else:
            tables["arrays"] = {"spots": final_positions(spots, fitted)}
    return tables


def final_positions(spots, fitted):
    """The subpixel positions of the spots when there are any, otherwise their
    whole-pixel positions (`spots`, from `decompose`; `fitted`, from `fit_subpixel`)."""
    spots_subpixel = fitted["spots_subpixel"]
    return spots_subpixel if spots_subpixel is not None else spots
