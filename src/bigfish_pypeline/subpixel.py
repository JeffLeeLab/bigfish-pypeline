"""Subpixel fitting of spot positions.

Works on 3D images (z, y, x) and 2D images (y, x). Voxel sizes and spot radii
have three values (z, y, x) in 3D and two (y, x) in 2D.
"""

import numpy as np
import bigfish.detection as detection


def fit_subpixel(rna, spots, voxel_size, spot_radius_nm):
    """
    Fit a Gaussian on each spot to find its position to a fraction of a pixel.

    rna: the image after background subtraction, (z, y, x) or (y, x).
    spots: one row per spot (z, y, x or y, x).
    voxel_size, spot_radius_nm: in nm, one value per image axis.

    Returns a float64 array with one row per spot, in the same order as
    spots. A spot whose fit fails keeps its original position.
    """
    rna = np.asarray(rna)
    if len(spots) == 0:
        return np.zeros((0, rna.ndim), dtype=np.float64)
    return detection.fit_subpixel(
        image=rna,
        spots=spots,
        voxel_size=tuple(voxel_size),
        spot_radius=tuple(spot_radius_nm),
    )
