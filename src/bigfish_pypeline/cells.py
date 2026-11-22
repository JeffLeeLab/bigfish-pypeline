"""Assigning spots and clusters to cells, and the per-cell table."""

import numpy as np
import pandas as pd

CELL_COLUMNS = [
    "cell_id",
    "area_px",
    "area_um2",
    "centroid_y_px",
    "centroid_x_px",
    "touches_border",
    "n_spots",
    "n_spots_in_clusters",
    "n_spots_outside_clusters",
    "n_clusters",
    "mean_spots_per_cluster",
]


def label_at(masks, y, x):
    """
    Label value at each (y, x) position, with -1 where the label is 0.

    Decimal positions are rounded to the nearest pixel, and every position
    is kept inside the image, so a position on the image edge always has a
    label.
    """
    masks = np.asarray(masks)
    y = np.clip(np.round(np.asarray(y, dtype=float)), 0, masks.shape[0] - 1).astype(np.int64)
    x = np.clip(np.round(np.asarray(x, dtype=float)), 0, masks.shape[1] - 1).astype(np.int64)
    cell_id = masks[y, x].astype(np.int64)
    cell_id[cell_id == 0] = -1
    return cell_id


def assign_spots(spots, masks, ndim):
    """
    `cell_id` of each spot: the label at its pixel position (y, x).

    spots: rows of (z, y, x, ...) for ndim=3 or (y, x, ...) for ndim=2, in
    pixels; any extra column (such as the cluster number) is ignored.
    The Z position is not used.
    """
    spots = _as_rows(spots, ndim)
    return label_at(masks, spots[:, ndim - 2], spots[:, ndim - 1])


def assign_clusters(clusters, masks, ndim):
    """
    `cell_id` of each cluster: the label at its centre.

    clusters: rows of (z, y, x, n_spots, cluster_id) for ndim=3 or
    (y, x, n_spots, cluster_id) for ndim=2. A decimal centre is rounded to
    the nearest pixel.
    """
    clusters = _as_rows(clusters, ndim)
    return label_at(masks, clusters[:, ndim - 2], clusters[:, ndim - 1])


def border_labels(masks):
    """Labels (other than 0) with at least one pixel on the first or last row or column."""
    masks = np.asarray(masks)
    edge = np.concatenate([masks[0, :], masks[-1, :], masks[:, 0], masks[:, -1]])
    labels = np.unique(edge)
    return labels[labels != 0].astype(np.int64)


def assign_cells(masks, spots, ndim, voxel_size_yx, clusters=None, drop_border_cells=False):
    """
    Assign spots and clusters to cells and make the cell table.

    masks: 2D label image, 0 for background and one whole number per cell.
    spots: rows of (z, y, x[, cluster_id]) for ndim=3 or (y, x[, cluster_id])
        for ndim=2, at pixel positions. Without a cluster_id column every
        spot counts as outside clusters.
    ndim: 3 for 3D spot coordinates, 2 for 2D.
    voxel_size_yx: pixel size in nm, used for `area_um2`.
    clusters: rows of (z, y, x, n_spots, cluster_id) or (y, x, n_spots,
        cluster_id); None when clustering is off.
    drop_border_cells: if True, cells touching the image border are left out
        of the cell table and their spots and clusters get cell_id = -1.

    Returns (spot_cell_id, cluster_cell_id, cells):
    - spot_cell_id: cell_id of each spot (-1 outside any cell).
    - cluster_cell_id: cell_id of each cluster (-1 outside any cell); empty
      when clusters is None.
    - cells: DataFrame with one row per label in masks (cells with no spots
      included) and the columns in CELL_COLUMNS.
    """
    masks = np.asarray(masks)
    if masks.ndim != 2:
        raise ValueError(f"The label image must be 2D; this one has shape {masks.shape}.")
    if ndim not in (2, 3):
        raise ValueError(f"ndim must be 2 or 3, not {ndim}.")

    spots = _as_rows(spots, ndim)
    if clusters is None:
        clusters = np.zeros((0, ndim + 2))
    clusters = _as_rows(clusters, ndim)

    spot_cell_id = assign_spots(spots, masks, ndim)
    cluster_cell_id = assign_clusters(clusters, masks, ndim)

    if spots.shape[1] > ndim:
        spot_in_cluster = spots[:, ndim] >= 0
    else:
        spot_in_cluster = np.zeros(len(spots), dtype=bool)
    cluster_sizes = clusters[:, ndim].astype(float) if len(clusters) else np.zeros(0)

    cells = _cell_shapes(masks, voxel_size_yx)
    on_border = border_labels(masks)
    cells["touches_border"] = cells["cell_id"].isin(on_border)

    if drop_border_cells:
        spot_cell_id[np.isin(spot_cell_id, on_border)] = -1
        cluster_cell_id[np.isin(cluster_cell_id, on_border)] = -1
        cells = cells[~cells["touches_border"]].reset_index(drop=True)

    n_spots, n_in, n_clusters, mean_size = [], [], [], []
    for cell_id in cells["cell_id"]:
        in_cell = spot_cell_id == cell_id
        n_spots.append(int(in_cell.sum()))
        n_in.append(int((in_cell & spot_in_cluster).sum()))
        sizes = cluster_sizes[cluster_cell_id == cell_id]
        n_clusters.append(len(sizes))
        mean_size.append(float(sizes.mean()) if len(sizes) else np.nan)

    cells["n_spots"] = np.array(n_spots, dtype=np.int64)
    cells["n_spots_in_clusters"] = np.array(n_in, dtype=np.int64)
    cells["n_spots_outside_clusters"] = cells["n_spots"] - cells["n_spots_in_clusters"]
    cells["n_clusters"] = np.array(n_clusters, dtype=np.int64)
    cells["mean_spots_per_cluster"] = np.array(mean_size, dtype=float)

    return spot_cell_id, cluster_cell_id, cells[CELL_COLUMNS]


def _cell_shapes(masks, voxel_size_yx):
    """cell_id, area and centroid of every label in masks, sorted by cell_id."""
    flat = masks.ravel().astype(np.int64)
    labels = np.unique(flat)
    labels = labels[labels != 0]

    yy, xx = np.indices(masks.shape)
    index = np.searchsorted(labels, flat)
    inside = flat != 0
    area = np.bincount(index[inside], minlength=len(labels))
    sum_y = np.bincount(index[inside], weights=yy.ravel()[inside], minlength=len(labels))
    sum_x = np.bincount(index[inside], weights=xx.ravel()[inside], minlength=len(labels))

    pixel_um = voxel_size_yx / 1000
    return pd.DataFrame({
        "cell_id": labels,
        "area_px": area.astype(np.int64),
        "area_um2": area * pixel_um ** 2,
        "centroid_y_px": sum_y / area,
        "centroid_x_px": sum_x / area,
    })


def _as_rows(coord, ndim):
    """Coordinates as a 2D array with one row per object; an empty input gives zero rows."""
    coord = np.asarray(coord)
    if coord.size == 0:
        width = coord.shape[1] if coord.ndim == 2 else ndim
        return np.zeros((0, width))
    if coord.ndim != 2 or coord.shape[1] < ndim:
        raise ValueError(
            f"Coordinates must have one row per object and at least {ndim} columns; "
            f"got shape {coord.shape}."
        )
    return coord
