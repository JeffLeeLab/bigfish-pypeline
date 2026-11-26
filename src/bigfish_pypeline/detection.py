"""Spot detection: spot radius, LoG filter, local maxima and thresholds.

Every function works on 3D images (z, y, x) and 2D images (y, x). Voxel
sizes and spot radii have three values (z, y, x) in 3D and two (y, x) in 2D.
"""

import math

import numpy as np
import bigfish.stack as stack
import bigfish.detection as detection
from bigfish.detection.spot_detection import _get_candidate_thresholds, _get_spot_counts

from bigfish_pypeline.psf import calculate_psf
from bigfish_pypeline.background import subtract_background

THRESHOLD_MODES = ("manual", "auto", "calibrated")
NO_THRESHOLD_WARNING = (
    "No automatic threshold: big-fish found too few candidate spots in this "
    "channel, so no spots were kept."
)


# ### Step 2: prepare ###

def get_spot_radius_nm(voxel_size, ex, em, NA, RI, microscope):
    """
    Spot radius in nm from the theoretical PSF: (psf_z, psf_yx, psf_yx) for a
    3D voxel size (z, y, x), (psf_yx, psf_yx) for a 2D voxel size (y, x).
    """
    _check_voxel_size(voxel_size)
    psf_z, psf_yx = calculate_psf(
        voxel_size[0], voxel_size[-1], ex, em, NA, RI, microscope
    )
    if len(voxel_size) == 3:
        return (psf_z, psf_yx, psf_yx)
    return (psf_yx, psf_yx)


def get_spot_radius_px(voxel_size, ex, em, NA, RI, microscope):
    """
    Spot radius in pixels for one channel, from its voxel size (nm) and the
    theoretical PSF of its wavelengths (ex, em in nm).

    Returns spot_radius_px, a tuple with one value per axis.
    """
    spot_radius_nm = get_spot_radius_nm(voxel_size, ex, em, NA, RI, microscope)
    spot_radius_px = detection.get_object_radius_pixel(
        voxel_size_nm=tuple(voxel_size),
        object_radius_nm=spot_radius_nm,
        ndim=len(voxel_size),
    )
    return spot_radius_px


def _check_voxel_size(voxel_size):
    if len(voxel_size) not in (2, 3):
        raise ValueError(
            "The voxel size needs three values (z, y, x) for a 3D image or "
            f"two values (y, x) for a 2D image; got {len(voxel_size)}."
        )


# ### Step 3: background and LoG filter ###

def filter_channel(image, spot_radius_px, bg_radius=5, bg_method="rolling_ball",
                   light_bg=False):
    """
    Remove the background of one channel and apply the LoG filter.

    image: one channel, (z, y, x) or (y, x).
    spot_radius_px: from get_spot_radius_px, one value per image axis.
    bg_radius, bg_method, light_bg: passed to subtract_background.

    Returns a dict with:
    - "rna": the image after background subtraction,
    - "rna_log": rna after the LoG filter (big-fish stack.log_filter),
    - "rna_mip": maximum projection of rna along z (rna itself in 2D).
    """
    image = np.asarray(image)
    if image.ndim != len(spot_radius_px):
        raise ValueError(
            f"The image has {image.ndim} dimensions but the spot radius has "
            f"{len(spot_radius_px)} values."
        )
    rna = subtract_background(image, bg_radius, light_bg=light_bg, method=bg_method)
    rna_log = stack.log_filter(rna, spot_radius_px)
    if rna.ndim == 3:
        rna_mip = stack.maximum_projection(rna)
    else:
        rna_mip = rna
    return {"rna": rna, "rna_log": rna_log, "rna_mip": rna_mip}


# ### Step 4: detection and thresholds ###

def find_local_maxima(rna_log, spot_radius_px):
    """Mask of the local maxima of the LoG-filtered image (candidate spots)."""
    return detection.local_maximum_detection(rna_log, min_distance=spot_radius_px)


def get_auto_threshold(rna_log, mask, lower_limit=None):
    """
    Automatic threshold from the big-fish elbow method.

    rna_log: LoG-filtered image; mask: its local maxima (find_local_maxima).
    lower_limit: optional value the threshold cannot go below.

    Returns (threshold, auto_threshold): auto_threshold is the big-fish value
    and threshold the value to use (raised to lower_limit when the big-fish
    value is lower). Both are None when big-fish returns no threshold: this
    happens when its smoothed curve of log(spot count) never rises above 2,
    which is always the case when 7 or fewer local maxima have a value above
    0 (for example on a blank image).
    """
    _, _, auto_threshold = get_elbow_values(rna_log, mask)
    return _apply_lower_limit(auto_threshold, lower_limit)


def _apply_lower_limit(auto_threshold, lower_limit):
    """(threshold to use, big-fish value); both None when there is no big-fish value."""
    if auto_threshold is None:
        return None, None
    auto_threshold = float(auto_threshold)
    threshold = auto_threshold
    if lower_limit is not None and threshold < lower_limit:
        threshold = float(lower_limit)
    return threshold, auto_threshold


def get_elbow_values(rna_log, mask):
    """
    Values of the big-fish elbow plot, from the LoG-filtered image and its
    local maxima.

    Returns (thresholds, count_spots, threshold), the same as big-fish
    detection.get_elbow_values on the unfiltered image: candidate
    thresholds, log of the number of spots above each one (smoothed), and the
    automatic threshold. The threshold is the value big-fish
    detection.automated_threshold_setting returns, or None when there is
    none: when the two arrays are empty, when the curve has a single point,
    or when big-fish cannot give a value for the curve (for example a flat
    one). The arrays are then kept for the elbow plot.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        thresholds = _get_candidate_thresholds(rna_log.ravel())
        _, mask_spots = detection.spots_thresholding(
            rna_log, mask, threshold=float(thresholds[0]), remove_duplicate=False
        )
        value_spots = rna_log[mask_spots]
        thresholds, count_spots = _get_spot_counts(thresholds, value_spots)
        threshold = _breaking_point(thresholds, count_spots)
    return thresholds, count_spots, threshold


def _breaking_point(thresholds, count_spots):
    """The big-fish elbow value of the curve, or None when there is none.

    None is given for a curve of fewer than two points, and for a curve for
    which big-fish fails instead of giving a value (for example a flat one).
    Any other curve gets big-fish's value, also a straight falling line.
    """
    if count_spots.size < 2:
        return None
    try:
        threshold, _, _ = detection.get_breaking_point(thresholds, count_spots)
    except ValueError:
        return None
    return threshold


def detect_spots(rna_log, spot_radius_px, threshold_mode="auto", threshold=None,
                 lower_limit=None, elbow=True):
    """
    Find spots in the LoG-filtered image of one channel.

    threshold_mode:
    - "manual" or "calibrated": threshold is the value to use.
    - "auto": the big-fish elbow method on this image, not below lower_limit
      when one is given.
    elbow: also return the elbow plot values (any mode).

    Returns a dict with:
    - "spots": int64 array, one row per spot (z, y, x in 3D; y, x in 2D),
    - "threshold": the threshold used, or None when auto mode found none,
    - "auto_threshold": the big-fish value before the lower limit (auto mode
      only, otherwise None),
    - "elbow_thresholds", "elbow_counts": the elbow plot values, or None when
      elbow is False. With a manual or calibrated threshold they are empty
      when they cannot be worked out, and the spots are found all the same,
    - "warning": a message when no threshold was found, otherwise None.
    """
    if threshold_mode not in THRESHOLD_MODES:
        raise ValueError(
            f"Unknown threshold mode '{threshold_mode}'. "
            f"Use one of: {', '.join(THRESHOLD_MODES)}."
        )
    mask = find_local_maxima(rna_log, spot_radius_px)

    auto_threshold = None
    warning = None
    elbow_values = None
    if threshold_mode == "auto":
        elbow_values = get_elbow_values(rna_log, mask)
        threshold, auto_threshold = _apply_lower_limit(elbow_values[2], lower_limit)
    else:
        if threshold is None:
            raise ValueError(f"A threshold value is needed in {threshold_mode} mode.")
        threshold = float(threshold)

    if threshold is None:
        spots = np.zeros((0, rna_log.ndim), dtype=np.int64)
        warning = NO_THRESHOLD_WARNING
    else:
        spots, _ = detection.spots_thresholding(rna_log, mask, threshold)

    elbow_thresholds = None
    elbow_counts = None
    if elbow:
        if elbow_values is None:
            try:
                elbow_values = get_elbow_values(rna_log, mask)
            except Exception:
                # The threshold was given, so the spots do not depend on the elbow
                # values: without them only the elbow plot is left out.
                elbow_values = (np.zeros(0), np.zeros(0), None)
        elbow_thresholds, elbow_counts = elbow_values[0], elbow_values[1]

    return {
        "spots": spots,
        "threshold": threshold,
        "auto_threshold": auto_threshold,
        "elbow_thresholds": elbow_thresholds,
        "elbow_counts": elbow_counts,
        "warning": warning,
    }


# ### Calibrated mode ###

def calibrate_threshold(auto_thresholds):
    """
    Fixed threshold for calibrated mode: the median of the automatic
    thresholds of the calibration images.

    auto_thresholds: a list with one dict per calibration image, with keys
    "image" (name), "threshold" (the automatic value, or None) and,
    optionally, "reason" (why there is no value, e.g. the image could not be
    read).

    Returns (threshold, table): threshold is the median of the usable values;
    table is a list of dicts, one per image, with "image", "threshold",
    "used" (True or False) and "reason" (None when used).

    Raises ValueError when no image has a usable value.
    """
    table = []
    values = []
    for entry in auto_thresholds:
        value = entry.get("threshold")
        reason = entry.get("reason")
        usable = (
            value is not None
            and not isinstance(value, bool)
            and isinstance(value, (int, float, np.number))
            and math.isfinite(value)
        )
        if usable:
            values.append(float(value))
            reason = None
        elif reason is None:
            reason = "no automatic threshold"
        table.append({
            "image": entry.get("image"),
            "threshold": value,
            "used": usable,
            "reason": reason,
        })
    if not values:
        raise ValueError(
            "None of the calibration images gave a usable automatic threshold, "
            "so no calibrated threshold can be set."
        )
    threshold = float(np.median(values))
    return threshold, table


# ### Bailout ###

def exceeds_bailout(spot_count, max_spots):
    """True when spot_count is above max_spots (None means no limit)."""
    if max_spots is None:
        return False
    return spot_count > max_spots
