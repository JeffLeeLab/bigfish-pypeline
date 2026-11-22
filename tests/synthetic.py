"""Synthetic 16-bit images with Gaussian spots at known positions, for the tests."""

import numpy as np


def make_image(
    shape=(10, 128, 128),
    n_spots=20,
    spot_sigma=None,
    amplitude=1000,
    background=100,
    noise=10,
    min_spacing=6,
    margin=4,
    dense_region=None,
    blank=False,
    seed=0,
):
    """
    Make a 2D (y, x) or 3D (z, y, x) uint16 image with Gaussian spots.

    shape: image size; two values give a 2D image, three a 3D image.
    n_spots: number of separate spots, placed at random whole-pixel positions
        at least min_spacing pixels apart (in y and x) and at least margin
        pixels from the image edges. Use 0 for an image without spots.
    spot_sigma: standard deviation of each spot in pixels, one value per
        axis. Default (1.1, 1.0, 1.0) in 3D and (1.0, 1.0) in 2D, close to the
        spot radius of the test kit settings.
    amplitude: peak height of each spot above the background.
    background, noise: constant background level and standard deviation of
        the Gaussian noise added to it. noise=0 gives no noise.
    dense_region: None, or a dict with "centre" (a position), "n_spots" and
        "spread" (standard deviation in pixels of the spot positions around
        the centre), to add a patch of overlapping spots.
    blank: True gives a flat image at the background level, without spots
        or noise.
    seed: seed of the random numbers, so the same arguments give the same
        image.

    Returns (image, spots, dense_spots): spots holds the positions of the
    separate spots and dense_spots those of the spots in the dense region,
    both as int64 arrays with one row per spot (z, y, x or y, x).
    """
    ndim = len(shape)
    if ndim not in (2, 3):
        raise ValueError("shape must have two values (y, x) or three (z, y, x).")
    if spot_sigma is None:
        spot_sigma = (1.1, 1.0, 1.0) if ndim == 3 else (1.0, 1.0)
    rng = np.random.default_rng(seed)

    image = np.full(shape, float(background))
    empty = np.zeros((0, ndim), dtype=np.int64)
    if blank:
        return image.astype(np.uint16), empty, empty

    spots = _place_spots(shape, n_spots, min_spacing, margin, rng)
    for spot in spots:
        _add_spot(image, spot, spot_sigma, amplitude)

    dense_spots = empty
    if dense_region is not None:
        centre = np.asarray(dense_region["centre"], dtype=float)
        positions = rng.normal(
            centre, dense_region["spread"], size=(dense_region["n_spots"], ndim)
        )
        upper = np.array(shape) - 1
        dense_spots = np.clip(np.round(positions), 0, upper).astype(np.int64)
        for spot in dense_spots:
            _add_spot(image, spot, spot_sigma, amplitude)

    if noise > 0:
        image += rng.normal(0, noise, shape)
    image = np.clip(np.round(image), 0, 65535).astype(np.uint16)
    return image, spots, dense_spots


def _place_spots(shape, n_spots, min_spacing, margin, rng):
    """Random whole-pixel positions at least min_spacing apart in y and x."""
    ndim = len(shape)
    spots = []
    taken = np.zeros(shape[-2:], dtype=bool)
    tries = 0
    while len(spots) < n_spots:
        tries += 1
        if tries > 200 * max(n_spots, 1):
            raise ValueError(
                f"Could not place {n_spots} spots in an image of size {shape}; "
                "use a larger image or a smaller min_spacing."
            )
        position = []
        for axis in range(ndim):
            # 3D: keep spots one plane away from the top and bottom planes
            edge = margin if axis >= ndim - 2 else min(1, (shape[axis] - 1) // 2)
            position.append(rng.integers(edge, shape[axis] - edge))
        y, x = position[-2:]
        if taken[y, x]:
            continue
        spots.append(position)
        taken[
            max(y - min_spacing + 1, 0): y + min_spacing,
            max(x - min_spacing + 1, 0): x + min_spacing,
        ] = True
    return np.array(spots, dtype=np.int64).reshape((-1, ndim))


def _add_spot(image, spot, spot_sigma, amplitude):
    """Add one Gaussian spot, drawn within 4 standard deviations of its centre."""
    window = []
    for axis, centre in enumerate(spot):
        half = int(np.ceil(4 * spot_sigma[axis]))
        window.append(slice(max(centre - half, 0), min(centre + half + 1, image.shape[axis])))
    grids = np.ogrid[tuple(window)]
    exponent = 0
    for axis, grid in enumerate(grids):
        exponent = exponent + (grid - spot[axis]) ** 2 / (2 * spot_sigma[axis] ** 2)
    image[tuple(window)] += amplitude * np.exp(-exponent)
