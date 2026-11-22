"""Cluster detection on spot positions.

Works on 3D positions (z, y, x) and 2D positions (y, x). Voxel sizes have
three values (z, y, x) in 3D and two (y, x) in 2D.
"""

import numpy as np
import bigfish.detection as detection


def detect_clusters(spots, voxel_size, radius=500, nb_min_spots=4):
    """
    Group spots into clusters with big-fish (DBSCAN).

    spots: one row per spot (z, y, x or y, x), whole-pixel or subpixel
        positions.
    voxel_size: in nm, one value per axis.
    radius: largest distance in nm between two neighbouring spots of a
        cluster; a whole number.
    nb_min_spots: number of spots within radius of a spot, itself included,
        for a cluster to grow from it.

    Returns (spots_post_clustering, clusters):
    - spots_post_clustering: spots in the same order, with one more column
      holding the cluster index (-1 for a spot outside any cluster),
    - clusters: one row per cluster with the centre (z, y, x or y, x), the
      number of spots and the cluster index.
    """
    voxel_size = tuple(voxel_size)
    ndim = len(voxel_size)
    if radius != int(radius):
        raise ValueError(f"The cluster radius must be a whole number of nm, not {radius}.")
    if len(spots) == 0:
        dtype = getattr(spots, "dtype", np.int64)
        spots_post_clustering = np.zeros((0, ndim + 1), dtype=dtype)
        clusters = np.zeros((0, ndim + 2), dtype=dtype)
        return spots_post_clustering, clusters
    spots = np.asarray(spots)
    if np.issubdtype(spots.dtype, np.integer):
        # big-fish converts the positions to nm in their own data type, so
        # whole-pixel positions need whole voxel sizes or decimal positions
        if all(float(size).is_integer() for size in voxel_size):
            voxel_size = tuple(int(size) for size in voxel_size)
        else:
            spots = spots.astype(np.float64)
    spots_post_clustering, clusters = detection.detect_clusters(
        spots=spots,
        voxel_size=voxel_size,
        radius=int(radius),
        nb_min_spots=int(nb_min_spots),
    )
    return spots_post_clustering, clusters
