"""Tests for clusters.py: grouped and scattered spots, row order, 2D and zero spots."""

import numpy as np
import pytest
import bigfish.detection as bigfish_detection

from bigfish_pypeline import clusters

VOXEL_SIZE = (200, 65, 65)


def _group_and_scattered(ndim, dtype=np.int64):
    """Ten spots within 2 px of (5, 50, 50) and ten spots 20 px apart."""
    rng = np.random.default_rng(0)
    group = np.array([5, 50, 50])[-ndim:] + rng.integers(-2, 3, size=(10, ndim))
    scattered = np.array([[2 + i % 6, 100 + 20 * i, 100 + 20 * (i % 3)] for i in range(10)])
    spots = np.concatenate([scattered[:5, -ndim:], group, scattered[5:, -ndim:]])
    return spots.astype(dtype)


@pytest.mark.parametrize("ndim", [3, 2])
@pytest.mark.parametrize("dtype", [np.int64, np.float64])
def test_group_and_scattered(ndim, dtype):
    spots = _group_and_scattered(ndim, dtype)
    voxel_size = VOXEL_SIZE[-ndim:]
    spots_post_clustering, clusters_found = clusters.detect_clusters(
        spots, voxel_size, radius=500, nb_min_spots=4
    )
    assert spots_post_clustering.shape == (20, ndim + 1)
    assert spots_post_clustering.dtype == dtype
    # same spots in the same rows
    assert np.array_equal(spots_post_clustering[:, :ndim], spots)
    in_group = np.zeros(20, dtype=bool)
    in_group[5:15] = True
    assert np.all(spots_post_clustering[in_group, ndim] == 0)
    assert np.all(spots_post_clustering[~in_group, ndim] == -1)

    assert clusters_found.shape == (1, ndim + 2)
    assert clusters_found.dtype == np.float64
    assert clusters_found[0, ndim] == 10
    assert clusters_found[0, ndim + 1] == 0
    np.testing.assert_allclose(clusters_found[0, :ndim], spots[in_group].mean(axis=0), rtol=1e-12)


def test_scattered_only():
    spots = _group_and_scattered(3)[np.r_[0:5, 15:20]]
    spots_post_clustering, clusters_found = clusters.detect_clusters(spots, VOXEL_SIZE)
    assert np.all(spots_post_clustering[:, 3] == -1)
    assert clusters_found.shape == (0, 5)


def test_defaults_and_minimum_spots():
    spots = _group_and_scattered(3)
    _, clusters_found = clusters.detect_clusters(spots, VOXEL_SIZE)
    assert len(clusters_found) == 1
    _, clusters_found = clusters.detect_clusters(spots, VOXEL_SIZE, nb_min_spots=12)
    assert len(clusters_found) == 0
    _, clusters_found = clusters.detect_clusters(spots, VOXEL_SIZE, radius=500.0, nb_min_spots=4.0)
    assert len(clusters_found) == 1
    with pytest.raises(ValueError, match="whole number"):
        clusters.detect_clusters(spots, VOXEL_SIZE, radius=500.5)


@pytest.mark.parametrize("ndim", [3, 2])
@pytest.mark.parametrize("dtype", [np.int64, np.float64])
def test_zero_spots(ndim, dtype):
    spots = np.zeros((0, ndim), dtype=dtype)
    spots_post_clustering, clusters_found = clusters.detect_clusters(spots, VOXEL_SIZE[-ndim:])
    assert spots_post_clustering.shape == (0, ndim + 1)
    assert clusters_found.shape == (0, ndim + 2)
    assert spots_post_clustering.dtype == dtype
    assert clusters_found.dtype == np.float64


def test_whole_pixel_spots_with_decimal_voxel_sizes():
    """Whole-pixel positions work with voxel sizes written as decimals."""
    spots = _group_and_scattered(3)
    expected_spots, expected_clusters = clusters.detect_clusters(spots, (200, 65, 65), radius=500)

    # whole voxel sizes given as decimals: the same result, still whole numbers
    spots_post_clustering, clusters_found = clusters.detect_clusters(spots, (200.0, 65.0, 65.0), radius=500)
    assert spots_post_clustering.dtype == np.int64
    assert np.array_equal(spots_post_clustering, expected_spots)
    assert np.array_equal(clusters_found, expected_clusters)

    # voxel sizes that are not whole: the same clusters, positions as decimals
    spots_post_clustering, clusters_found = clusters.detect_clusters(spots, (200.5, 64.5, 64.5), radius=500)
    assert np.array_equal(spots_post_clustering[:, :3], spots)
    assert np.array_equal(spots_post_clustering[:, 3], expected_spots[:, 3])
    assert clusters_found.shape == (1, 5)
    assert clusters_found[0, 3] == 10


@pytest.mark.parametrize("ndim", [3, 2])
def test_exact_centres_for_whole_pixel_spots(ndim):
    """Whole-pixel spots and whole voxel sizes: big-fish's clusters, with exact centres."""
    rng = np.random.default_rng(3)
    first = np.array([5, 50, 50])[-ndim:] + rng.integers(-2, 3, size=(9, ndim))
    second = np.array([3, 150, 90])[-ndim:] + rng.integers(-2, 3, size=(7, ndim))
    scattered = _group_and_scattered(ndim)[:5]
    spots = np.concatenate([first, scattered, second]).astype(np.int64)
    voxel_size = VOXEL_SIZE[-ndim:]
    spots_post_clustering, clusters_found = clusters.detect_clusters(spots, voxel_size)
    whole_spots, whole_clusters = bigfish_detection.detect_clusters(spots, voxel_size, 500, 4)

    # spots, cluster numbers and numbers of spots as big-fish gives them
    assert spots_post_clustering.dtype == np.int64
    np.testing.assert_array_equal(spots_post_clustering, whole_spots)
    assert clusters_found.dtype == np.float64
    np.testing.assert_array_equal(clusters_found[:, ndim:], whole_clusters[:, ndim:])
    assert len(clusters_found) == 2

    # each centre is the mean position of its spots, with its decimals
    for row in clusters_found:
        members = spots[spots_post_clustering[:, ndim] == row[ndim + 1]]
        np.testing.assert_allclose(row[:ndim], members.mean(axis=0), rtol=1e-12)
        assert len(members) == row[ndim]
    assert not np.array_equal(clusters_found[:, :ndim], np.round(clusters_found[:, :ndim]))
    # big-fish alone cuts the centres to whole pixels
    np.testing.assert_array_equal(whole_clusters[:, :ndim], np.trunc(clusters_found[:, :ndim]))
