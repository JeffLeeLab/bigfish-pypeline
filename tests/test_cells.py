"""Tests for cells.py: assigning spots and clusters to cells, and the cell table."""

import numpy as np
import pandas as pd
import pytest
import tifffile

from bigfish_pypeline.cells import (
    CELL_COLUMNS,
    assign_cells,
    assign_clusters,
    assign_spots,
    border_labels,
)

VOXEL_SIZE_YX = 65  # nm
NPZ_NAME = "sypN_DAPI_Phal_jim-exon_crop_ch2_bfoutput.npz"


def _masks():
    """
    10 x 12 label image:
    1 and 2 side by side in the middle; 3 on the top and right edges;
    4 away from the edges with no spots; 5 in the bottom-right corner.
    """
    masks = np.zeros((10, 12), dtype=np.uint32)
    masks[2:5, 2:5] = 1  # 3 x 3, centroid (3, 3)
    masks[2:5, 5:9] = 2  # 3 x 4, centroid (3, 6.5)
    masks[0:2, 9:12] = 3  # 2 x 3, centroid (0.5, 10)
    masks[6:9, 1:4] = 4  # 3 x 3, centroid (7, 2)
    masks[8:10, 10:12] = 5  # 2 x 2, centroid (8.5, 10.5)
    return masks


# (z, y, x, cluster_id)
SPOTS = np.array([
    [0, 3, 3, 0],  # cluster 0, in cell 1
    [0, 3, 4, 0],  # cluster 0, in cell 1
    [1, 3, 5, 0],  # cluster 0, in cell 2
    [0, 2, 6, 0],  # cluster 0, in cell 2
    [0, 4, 2, -1],  # cell 1
    [2, 4, 8, -1],  # cell 2
    [0, 6, 6, -1],  # background
    [0, 0, 0, -1],  # background, image corner
    [0, 1, 10, -1],  # cell 3
    [0, 9, 11, -1],  # cell 5, last row and column
    [0, 9, 10, 1],  # cluster 1, cell 5
    [0, 8, 11, 1],  # cluster 1, cell 5
])
SPOT_CELL_ID = [1, 1, 2, 2, 1, 2, -1, -1, 3, 5, 5, 5]

# (z, y, x, n_spots, cluster_id)
CLUSTERS = np.array([
    [0.25, 3.0, 4.5, 4, 0],  # across cells 1 and 2; centre rounds to (3, 4), in cell 1
    [0.0, 9.4, 11.6, 2, 1],  # centre on the image edge; rounds to x = 12, kept at 11
])
CLUSTER_CELL_ID = [1, 5]

EXPECTED = pd.DataFrame({
    "cell_id": [1, 2, 3, 4, 5],
    "area_px": [9, 12, 6, 9, 4],
    "centroid_y_px": [3.0, 3.0, 0.5, 7.0, 8.5],
    "centroid_x_px": [3.0, 6.5, 10.0, 2.0, 10.5],
    "touches_border": [False, False, True, False, True],
    "n_spots": [3, 3, 1, 0, 3],
    "n_spots_in_clusters": [2, 2, 0, 0, 2],
    "n_spots_outside_clusters": [1, 1, 1, 0, 1],
    "n_clusters": [1, 0, 0, 0, 1],
    "mean_spots_per_cluster": [4.0, np.nan, np.nan, np.nan, 2.0],
})


def _check_table(cells, expected):
    assert list(cells.columns) == CELL_COLUMNS
    for column in expected.columns:
        np.testing.assert_array_equal(
            cells[column].to_numpy(), expected[column].to_numpy(), err_msg=column
        )


def test_synthetic_3d():
    spot_ids, cluster_ids, cells = assign_cells(_masks(), SPOTS, 3, VOXEL_SIZE_YX, CLUSTERS)
    np.testing.assert_array_equal(spot_ids, SPOT_CELL_ID)
    np.testing.assert_array_equal(cluster_ids, CLUSTER_CELL_ID)
    _check_table(cells, EXPECTED)
    np.testing.assert_allclose(cells["area_um2"], EXPECTED["area_px"] * 0.065 ** 2)


def test_synthetic_2d():
    spots = SPOTS[:, 1:]
    clusters = CLUSTERS[:, 1:]
    spot_ids, cluster_ids, cells = assign_cells(_masks(), spots, 2, VOXEL_SIZE_YX, clusters)
    np.testing.assert_array_equal(spot_ids, SPOT_CELL_ID)
    np.testing.assert_array_equal(cluster_ids, CLUSTER_CELL_ID)
    _check_table(cells, EXPECTED)


def test_z_position_not_used():
    spots = SPOTS.copy()
    spots[:, 0] = 7
    spot_ids, _, _ = assign_cells(_masks(), spots, 3, VOXEL_SIZE_YX, CLUSTERS)
    np.testing.assert_array_equal(spot_ids, SPOT_CELL_ID)


def test_clustering_off():
    spot_ids, cluster_ids, cells = assign_cells(_masks(), SPOTS[:, :3], 3, VOXEL_SIZE_YX)
    np.testing.assert_array_equal(spot_ids, SPOT_CELL_ID)
    assert len(cluster_ids) == 0
    expected = EXPECTED.copy()
    expected["n_spots_in_clusters"] = 0
    expected["n_spots_outside_clusters"] = expected["n_spots"]
    expected["n_clusters"] = 0
    expected["mean_spots_per_cluster"] = np.nan
    _check_table(cells, expected)


@pytest.mark.parametrize(
    "spots, clusters, ndim",
    [
        (np.zeros((0, 4)), np.zeros((0, 5)), 3),
        (np.zeros((0, 3)), None, 3),
        (np.zeros((0, 3)), np.zeros((0, 4)), 2),
        (np.array([]), np.array([]), 3),
    ],
)
def test_zero_spots(spots, clusters, ndim):
    spot_ids, cluster_ids, cells = assign_cells(_masks(), spots, ndim, VOXEL_SIZE_YX, clusters)
    assert len(spot_ids) == 0
    assert len(cluster_ids) == 0
    assert list(cells["cell_id"]) == [1, 2, 3, 4, 5]
    assert (cells["n_spots"] == 0).all()
    assert (cells["n_clusters"] == 0).all()
    assert cells["mean_spots_per_cluster"].isna().all()


def test_no_cells():
    masks = np.zeros((10, 12), dtype=np.uint32)
    spot_ids, cluster_ids, cells = assign_cells(masks, SPOTS, 3, VOXEL_SIZE_YX, CLUSTERS)
    assert (spot_ids == -1).all()
    assert (cluster_ids == -1).all()
    assert len(cells) == 0
    assert list(cells.columns) == CELL_COLUMNS


def test_drop_border_cells():
    spot_ids, cluster_ids, cells = assign_cells(
        _masks(), SPOTS, 3, VOXEL_SIZE_YX, CLUSTERS, drop_border_cells=True
    )
    expected_spots = [-1 if c in (3, 5) else c for c in SPOT_CELL_ID]
    np.testing.assert_array_equal(spot_ids, expected_spots)
    np.testing.assert_array_equal(cluster_ids, [1, -1])
    expected = EXPECTED[~EXPECTED["touches_border"]].reset_index(drop=True)
    _check_table(cells, expected)


def test_border_labels():
    np.testing.assert_array_equal(border_labels(_masks()), [3, 5])


def test_cluster_centre_outside_image_kept_on_edge():
    clusters = np.array([[0, -0.4, 11.4, 3, 0], [0, 9.6, -0.2, 3, 1]])
    masks = _masks()
    masks[9, 0] = 6
    np.testing.assert_array_equal(assign_clusters(clusters, masks, 3), [3, 6])


def test_spots_and_clusters_alone():
    np.testing.assert_array_equal(assign_spots(SPOTS, _masks(), 3), SPOT_CELL_ID)
    np.testing.assert_array_equal(assign_clusters(CLUSTERS, _masks(), 3), CLUSTER_CELL_ID)


def test_label_values_kept_as_cell_id():
    masks = _masks()
    masks[masks == 2] = 70000
    spot_ids, _, cells = assign_cells(masks, SPOTS, 3, VOXEL_SIZE_YX, CLUSTERS)
    assert 70000 in set(spot_ids)
    assert list(cells["cell_id"]) == [1, 3, 4, 5, 70000]


GENERAL_RUNS = ["general_manual18_subpixel-off", "general_auto_subpixel-off"]
HCR_RUNS = ["hcr_manual18_subpixel-off", "hcr_auto_subpixel-off"]


@pytest.mark.parametrize("run", GENERAL_RUNS + HCR_RUNS)
def test_crop_matches_v1_reference(run, crop_reference_folder, crop_labels_path):
    masks = tifffile.imread(crop_labels_path)
    data = np.load(crop_reference_folder / run / NPZ_NAME)
    if run in GENERAL_RUNS:
        spots, clusters = data["spots_post_clustering"], data["clusters"]
    else:
        spots, clusters = data["spots"], None

    _, _, cells = assign_cells(masks, spots, 3, VOXEL_SIZE_YX, clusters)
    reference = pd.read_csv(crop_reference_folder / run / "per_cell_counts.csv")

    assert len(cells) == 44
    assert list(cells["cell_id"]) == list(reference["label"])
    for column in reference.columns.drop("label"):
        np.testing.assert_array_equal(
            cells[column].to_numpy(), reference[column].to_numpy(), err_msg=column
        )
