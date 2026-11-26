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
    - spots_post_clustering: spots in the same order and number type, with
      one more column holding the cluster index (-1 for a spot outside any
      cluster),
    - clusters: one row per cluster with the centre (z, y, x or y, x), the
      number of spots and the cluster index, as decimal numbers (float64).
      The centre is the exact mean position of the cluster's spots, also
      for whole-pixel spots.
    """
    voxel_size = tuple(voxel_size)
    ndim = len(voxel_size)
    if radius != int(radius):
        raise ValueError(f"The cluster radius must be a whole number of nm, not {radius}.")
    if len(spots) == 0:
        dtype = getattr(spots, "dtype", np.int64)
        spots_post_clustering = np.zeros((0, ndim + 1), dtype=dtype)
        clusters = np.zeros((0, ndim + 2), dtype=np.float64)
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
    return spots_post_clustering, _exact_centres(spots_post_clustering, clusters, ndim)


def _exact_centres(spots_post_clustering, clusters, ndim):
    """
    The clusters with each centre set to the exact mean position of its spots.

    big-fish works out the centres in the spots' own number type, so with
    whole-pixel spots it cuts them to whole pixels. The clusters, their
    number of spots and their index are kept as big-fish gives them.
    """
    clusters = np.asarray(clusters, dtype=np.float64).reshape(-1, ndim + 2)
    positions = spots_post_clustering[:, :ndim].astype(np.float64)
    labels = spots_post_clustering[:, ndim]
    for row in clusters:
        row[:ndim] = positions[labels == row[ndim + 1]].mean(axis=0)
    return clusters
