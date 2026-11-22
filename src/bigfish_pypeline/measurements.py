"""Per-spot measurements: signal-to-noise ratio (SNR) and LoG intensity.

Every function works on 3D images (z, y, x) and 2D images (y, x). Spots are
whole-pixel positions, one row per spot (z, y, x in 3D; y, x in 2D); any
further column, such as a cluster number, is ignored.
"""

import numpy as np


def _spot_positions(spots, ndim):
    """Spot positions as an int64 array of shape (nb_spots, ndim)."""
    spots = np.asarray(spots)
    if spots.size == 0:
        return np.zeros((0, ndim), dtype=np.int64)
    if spots.ndim != 2 or spots.shape[1] < ndim:
        raise ValueError(
            f"Spots need one row per spot with at least {ndim} columns "
            f"for a {ndim}D image; got an array of shape {spots.shape}."
        )
    return spots[:, :ndim].astype(np.int64)


def compute_snr_spots_individual(image, spots, spot_radius_px):
    """
    Compute SNR for each individual spot.

    For each spot: the mean of the image within the spot radius, minus the
    mean of the ring between 1.5 and 2.5 times the spot radius, divided by
    the standard deviation of that ring. Distances are scaled by the spot
    radius on each axis, so the regions follow the shape of the spot.

    Parameters
    ----------
    image : np.ndarray
        Image with shape (z, y, x) or (y, x), usually rna.
    spots : np.ndarray
        Coordinates of spots with shape (nb_spots, 3) for zyx coordinates or
        (nb_spots, 2) for yx coordinates. Further columns are ignored.
    spot_radius_px : tuple
        Spot radius in pixels, one value per image axis (spot_radius_px from
        detection.get_spot_radius_px).

    Returns
    -------
    snr_values : np.ndarray
        Array of SNR values for each spot with shape (nb_spots,). The value is
        NaN when the ring is empty or has no variation.
    """
    image = np.asarray(image)
    ndim = image.ndim
    if ndim not in (2, 3) or len(spot_radius_px) != ndim:
        raise ValueError(
            f"The image has {ndim} dimensions but the spot radius has "
            f"{len(spot_radius_px)} values; both need 3 (z, y, x) or 2 (y, x)."
        )
    spots = _spot_positions(spots, ndim)

    # Region sizes for the background ring
    background_outer_radius = tuple([int(np.ceil(r * 2.5)) for r in spot_radius_px])

    snr_values = np.full(len(spots), np.nan)

    for i, spot_coord in enumerate(spots):
        # Bounds for extraction (with boundary checks)
        bounds = []
        for axis in range(ndim):
            c = int(spot_coord[axis])
            c_min = max(0, c - background_outer_radius[axis])
            c_max = min(image.shape[axis], c + background_outer_radius[axis] + 1)
            bounds.append((c, c_min, c_max))

        # Extract local region
        local_region = image[tuple(slice(c_min, c_max) for _, c_min, c_max in bounds)]

        # Coordinate grids relative to spot centre
        grids = np.ogrid[tuple(slice(c_min - c, c_max - c) for c, c_min, c_max in bounds)]

        # Distances (accounting for anisotropic voxels)
        distances = 0
        for axis in range(ndim):
            distances = distances + (grids[axis] / spot_radius_px[axis]) ** 2
        distances = np.sqrt(distances)

        # Masks for signal and background regions
        signal_mask = distances <= 1.0
        background_mask = (distances > 1.5) & (distances <= 2.5)

        if np.sum(signal_mask) > 0 and np.sum(background_mask) > 0:
            signal = np.mean(local_region[signal_mask])
            background = np.mean(local_region[background_mask])
            background_std = np.std(local_region[background_mask])
            if background_std > 0:
                snr_values[i] = (signal - background) / background_std

    return snr_values


def compute_log_intensity(rna_log, spots):
    """
    Value of the LoG-filtered image at each spot's own position.

    rna_log: LoG-filtered image, (z, y, x) or (y, x).
    spots: one row per spot (z, y, x or y, x); further columns are ignored.

    Returns log_intensity, an array with shape (nb_spots,) and the data type
    of rna_log.
    """
    rna_log = np.asarray(rna_log)
    spots = _spot_positions(spots, rna_log.ndim)
    return rna_log[tuple(spots.T)]


def measure_spots(rna, rna_log, spots, spot_radius_px, snr=True, intensity=True):
    """
    Spot measurements for one channel.

    rna: image after background subtraction; rna_log: rna after the LoG
    filter; spots: one row per spot; spot_radius_px: one value per axis.
    snr, intensity: which measurements to take.

    Returns a dict with "snr" and/or "log_intensity", one value per spot.
    """
    measurements = {}
    if snr:
        measurements["snr"] = compute_snr_spots_individual(rna, spots, spot_radius_px)
    if intensity:
        measurements["log_intensity"] = compute_log_intensity(rna_log, spots)
    return measurements
