"""Tests for decomposition.py: the crop as v1, the seeded reference spot and the cases where decomposition is skipped."""

import os
import subprocess
import sys
import warnings

import numpy as np
import pytest
import tifffile
import bigfish.detection as bf_detection
import bigfish.detection.dense_decomposition as bf_dense_decomposition

from bigfish_pypeline import clusters, decomposition, detection, subpixel
from synthetic import make_image

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning", "ignore::FutureWarning")

FISH_CHANNEL = 2
VOXEL_SIZE = (200, 65, 65)
OPTICS = dict(ex=570, em=610, NA=1.45, RI=1.45, microscope="confocal")
SPOT_RADIUS_PX = detection.get_spot_radius_px(VOXEL_SIZE, **OPTICS)
SPOT_RADIUS_NM = detection.get_spot_radius_nm(VOXEL_SIZE, **OPTICS)
SPOT_RADIUS_PX_2D = detection.get_spot_radius_px(VOXEL_SIZE[1:], **OPTICS)
SPOT_RADIUS_NM_2D = detection.get_spot_radius_nm(VOXEL_SIZE[1:], **OPTICS)
THRESHOLDS = {
    "manual18": dict(threshold_mode="manual", threshold=18),
    "auto": dict(threshold_mode="auto"),
}


def _settings(ndim):
    if ndim == 3:
        return VOXEL_SIZE, SPOT_RADIUS_PX, SPOT_RADIUS_NM
    return VOXEL_SIZE[1:], SPOT_RADIUS_PX_2D, SPOT_RADIUS_NM_2D


def _detect(image, threshold=50):
    voxel_size, spot_radius_px, _ = _settings(image.ndim)
    filtered = detection.filter_channel(image, spot_radius_px)
    spots = detection.detect_spots(
        filtered["rna_log"], spot_radius_px, threshold_mode="manual",
        threshold=threshold, elbow=False,
    )["spots"]
    return filtered["rna"], spots


def _decompose(rna, spots, beta=1, seed=1):
    voxel_size, _, spot_radius_nm = _settings(rna.ndim)
    return decomposition.decompose_dense_regions(
        rna, spots, voxel_size, spot_radius_nm, alpha=0.5, beta=beta, seed=seed
    )


# --------------------------------------------------------------------------
# test kit crop against v1
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def crop_runs(crop_path):
    """Detection and decomposition on the crop for each v1 threshold."""
    image = tifffile.imread(crop_path)[:, FISH_CHANNEL]
    filtered = detection.filter_channel(image, SPOT_RADIUS_PX, bg_radius=5, bg_method="tophat")
    runs = {}
    for name, threshold in THRESHOLDS.items():
        spots = detection.detect_spots(
            filtered["rna_log"], SPOT_RADIUS_PX, elbow=False, **threshold
        )["spots"]
        seed = decomposition.get_seed(0, "sypN_DAPI_Phal_jim-exon_crop", FISH_CHANNEL)
        result = decomposition.decompose_dense_regions(
            filtered["rna"], spots, VOXEL_SIZE, SPOT_RADIUS_NM, alpha=0.5, beta=1, seed=seed
        )
        runs[name] = {"rna": filtered["rna"], "spots": spots, **result}
    return runs


def _v1_run(folder):
    reference = np.load(next(folder.glob("*_bfoutput.npz")))
    reference_spots = list(folder.glob("*_referencespot.tif"))
    reference_spot = tifffile.imread(reference_spots[0]) if reference_spots else None
    return reference["spots_post_clustering"], reference["clusters"], reference_spot


def _crop_chain(run, subpixel_on):
    spots = run["spots_post_decomposition"]
    if subpixel_on:
        spots = subpixel.fit_subpixel(run["rna"], spots, VOXEL_SIZE, SPOT_RADIUS_NM)
    return clusters.detect_clusters(spots, VOXEL_SIZE, radius=600, nb_min_spots=12)


@pytest.mark.parametrize("name, n_spots", [("manual18", 692), ("auto", 869)])
def test_crop_subpixel_off_as_v1(crop_runs, crop_reference_folder, name, n_spots):
    run = crop_runs[name]
    assert run["warning"] is None
    assert run["skipped"] is False
    expected_spots, expected_clusters, expected_reference = _v1_run(
        crop_reference_folder / f"general_{name}_subpixel-off"
    )
    spots_post_clustering, clusters_found = _crop_chain(run, subpixel_on=False)
    assert expected_spots.shape == (n_spots, 4)
    assert expected_clusters.shape == (6, 5)
    assert np.array_equal(spots_post_clustering, expected_spots)
    assert np.array_equal(clusters_found, expected_clusters)
    assert run["reference_spot"].dtype == expected_reference.dtype
    assert np.array_equal(run["reference_spot"], expected_reference)


@pytest.fixture(scope="module")
def crop_subpixel_chains(crop_runs):
    return {name: _crop_chain(run, subpixel_on=True) for name, run in crop_runs.items()}


@pytest.mark.parametrize("name", ["manual18", "auto"])
def test_crop_subpixel_on_as_v1_new_env(crop_subpixel_chains, test_kit_folder, name):
    """Same as the v1 script run in the same env."""
    expected_spots, expected_clusters, _ = _v1_run(
        test_kit_folder / "reference_v1_new_env" / f"general_{name}_subpixel-on"
    )
    spots_post_clustering, clusters_found = crop_subpixel_chains[name]
    assert spots_post_clustering.shape == expected_spots.shape
    assert clusters_found.shape == expected_clusters.shape
    assert np.array_equal(spots_post_clustering[:, 3], expected_spots[:, 3])
    assert np.all(np.abs(spots_post_clustering - expected_spots) <= 1e-6)
    assert np.all(np.abs(clusters_found - expected_clusters) <= 1e-6)


@pytest.mark.parametrize("name, n_spots", [("manual18", 692), ("auto", 869)])
def test_crop_subpixel_on_as_v1_main_env(crop_runs, crop_subpixel_chains,
                                         crop_reference_folder, name, n_spots):
    """Close to v1 in the main env, whose older scipy fits slightly differently."""
    expected_spots, expected_clusters, expected_reference = _v1_run(
        crop_reference_folder / f"general_{name}_subpixel-on"
    )
    spots_post_clustering, clusters_found = crop_subpixel_chains[name]
    assert spots_post_clustering.shape == expected_spots.shape == (n_spots, 4)
    assert clusters_found.shape == expected_clusters.shape == (6, 5)
    assert np.array_equal(spots_post_clustering[:, 3], expected_spots[:, 3])
    assert np.array_equal(clusters_found[:, 3:], expected_clusters[:, 3:])
    assert np.all(np.abs(clusters_found[:, :3] - expected_clusters[:, :3]) <= 0.1)
    assert_close_positions(spots_post_clustering[:, :3], expected_spots[:, :3])
    assert np.array_equal(crop_runs[name]["reference_spot"], expected_reference)


def assert_close_positions(found, expected):
    """At least 90 % of spots within 0.01 px, 95 % within 0.1 px, all within 2 px."""
    difference = np.abs(found - expected).max(axis=1)
    assert np.mean(difference <= 0.01) >= 0.90
    assert np.mean(difference <= 0.1) >= 0.95
    assert np.all(difference <= 2)


# --------------------------------------------------------------------------
# synthetic images
# --------------------------------------------------------------------------


@pytest.mark.parametrize("shape, centre", [((10, 128, 128), (5, 64, 64)), ((128, 128), (64, 64))])
def test_dense_region_gains_spots(shape, centre):
    image, _, _ = make_image(
        shape=shape, n_spots=40, seed=1,
        dense_region={"centre": centre, "n_spots": 15, "spread": 2},
    )
    rna, spots = _detect(image)
    result = _decompose(rna, spots)
    spots_post_decomposition = result["spots_post_decomposition"]
    assert result["skipped"] is False
    assert result["warning"] is None
    assert len(spots_post_decomposition) > len(spots)
    assert spots_post_decomposition.shape[1] == len(shape)
    assert spots_post_decomposition.dtype == np.int64
    assert result["reference_spot"].shape == (5,) * len(shape)
    assert result["reference_spot"].dtype == rna.dtype


@pytest.fixture(scope="module")
def many_spots():
    """An image with more than 2,000 detected spots and a dense region."""
    image, _, _ = make_image(
        shape=(10, 512, 512), n_spots=2500, min_spacing=5, seed=4,
        dense_region={"centre": (5, 256, 256), "n_spots": 40, "spread": 3},
    )
    rna, spots = _detect(image)
    assert len(spots) > 2000
    return rna, spots


def test_seeded_reference_spot(many_spots, monkeypatch):
    rna, spots = many_spots
    seed = decomposition.get_seed(0, "image", 1)

    # record the random state at each reference spot, including the one
    # built inside get_dense_region
    states = []
    build_reference_spot = bf_detection.build_reference_spot

    def spy(*args, **kwargs):
        states.append(np.random.get_state())
        return build_reference_spot(*args, **kwargs)

    monkeypatch.setattr(bf_detection, "build_reference_spot", spy)
    monkeypatch.setattr(bf_dense_decomposition, "build_reference_spot", spy)

    np.random.seed(123)
    state_before = np.random.get_state()
    first = _decompose(rna, spots, seed=seed)
    state_after = np.random.get_state()
    assert state_before[0] == state_after[0]
    assert np.array_equal(state_before[1], state_after[1])
    assert state_before[2:] == state_after[2:]

    # all three reference spots start from the seeded state, so use the same spots
    np.random.seed(seed)
    seeded = np.random.get_state()
    assert len(states) == 3
    for state in states:
        assert np.array_equal(state[1], seeded[1]) and state[2:] == seeded[2:]

    np.random.seed(456)
    second = _decompose(rna, spots, seed=seed)
    assert np.array_equal(first["reference_spot"], second["reference_spot"])
    assert np.array_equal(
        first["spots_post_decomposition"], second["spots_post_decomposition"]
    )
    assert len(first["spots_post_decomposition"]) > len(spots)
    assert first["warning"] is None

    # another seed picks other spots
    other = _decompose(rna, spots, seed=decomposition.get_seed(0, "image", 2))
    assert not np.array_equal(first["reference_spot"], other["reference_spot"])


def test_seed_values():
    seed = decomposition.get_seed(0, "image_é 1", 2)
    assert 0 <= seed < 2**32
    assert seed == decomposition.get_seed(0, "image_é 1", 2)
    assert seed != decomposition.get_seed(1, "image_é 1", 2)
    assert seed != decomposition.get_seed(0, "image_é 2", 2)
    assert seed != decomposition.get_seed(0, "image_é 1", 1)
    # the same name with the accent stored as two characters (as on macOS)
    assert seed == decomposition.get_seed(0, "image_é 1", 2)


def test_seed_same_in_new_process():
    code = (
        "from bigfish_pypeline import decomposition; "
        "print(decomposition.get_seed(0, 'image_é 1', 2))"
    )
    env = dict(os.environ, PYTHONHASHSEED="12345", PYTHONIOENCODING="utf-8")
    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        encoding="utf-8", env=env, check=True,
    ).stdout
    assert int(output.strip()) == decomposition.get_seed(0, "image_é 1", 2)


@pytest.mark.parametrize("shape", [(10, 64, 64), (64, 64)])
def test_no_spots(shape):
    image, _, _ = make_image(shape=shape, blank=True)
    rna, spots = _detect(image)
    assert len(spots) == 0
    result = _decompose(rna, spots)
    assert result["spots_post_decomposition"] is spots
    assert result["reference_spot"] is None
    assert result["skipped"] is True
    assert result["warning"] == decomposition.NO_SPOTS_WARNING


@pytest.mark.parametrize("n_spots", [1, 2, 3])
def test_very_few_spots(n_spots):
    """
    A reference spot is built from one to three spots, with a warning in the
    result in place of the big-fish warning; no dense region is found.
    """
    image, _, _ = make_image(shape=(10, 64, 64), n_spots=n_spots, seed=0)
    rna, spots = _detect(image)
    assert len(spots) == n_spots
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _decompose(rna, spots)
    assert not [w for w in caught if "reference spot" in str(w.message)]
    assert np.array_equal(result["spots_post_decomposition"], spots)
    assert result["reference_spot"].shape == (5, 5, 5)
    assert result["skipped"] is True
    assert result["warning"] == decomposition.FEW_SPOTS_WARNING


def test_other_warnings_passed_on(monkeypatch):
    build_reference_spot = bf_detection.build_reference_spot

    def noisy(*args, **kwargs):
        warnings.warn("another warning", RuntimeWarning)
        return build_reference_spot(*args, **kwargs)

    monkeypatch.setattr(bf_detection, "build_reference_spot", noisy)
    image, _, _ = make_image(shape=(10, 64, 64), n_spots=2, seed=0)
    rna, spots = _detect(image)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _decompose(rna, spots)
    messages = [str(w.message) for w in caught]
    assert messages.count("another warning") == 2
    assert not [m for m in messages if "reference spot" in m]
    assert result["warning"] == decomposition.FEW_SPOTS_WARNING


def test_spots_at_edge_give_no_reference_spot():
    image, _, _ = make_image(shape=(10, 64, 64), n_spots=0, seed=0)
    spots = np.array([[0, 30, 30], [5, 1, 30], [9, 30, 62]], dtype=np.int64)
    result = _decompose(image, spots)
    assert result["spots_post_decomposition"] is spots
    assert result["reference_spot"] is None
    assert result["skipped"] is True
    assert result["warning"] == decomposition.NO_REFERENCE_SPOT_WARNING


def test_spot_model_not_fitted():
    """Single bright voxels give a reference spot no Gaussian can be fitted to."""
    rng = np.random.default_rng(0)
    rna = np.zeros((10, 64, 64), dtype=np.uint16)
    spots = np.stack(
        [rng.integers(3, 7, 40), rng.integers(5, 59, 40), rng.integers(5, 59, 40)], axis=1
    )
    rna[tuple(spots.T)] = 1000
    result = _decompose(rna, spots)
    assert result["spots_post_decomposition"] is spots
    assert result["reference_spot"] is not None
    assert result["skipped"] is True
    assert result["warning"] == decomposition.NO_SPOT_MODEL_WARNING


@pytest.mark.parametrize("shape", [(10, 128, 128), (128, 128)])
def test_no_dense_regions(shape):
    image, _, _ = make_image(shape=shape, n_spots=80, min_spacing=8, seed=1)
    rna, spots = _detect(image)
    assert len(spots) > 30
    result = _decompose(rna, spots)
    assert result["spots_post_decomposition"] is spots
    assert result["reference_spot"].shape == (5,) * len(shape)
    assert result["skipped"] is True
    assert result["warning"] is None


def test_2d_through_every_step():
    image, _, _ = make_image(
        shape=(128, 128), n_spots=40, seed=1,
        dense_region={"centre": (64, 64), "n_spots": 15, "spread": 2},
    )
    rna, spots = _detect(image)
    result = _decompose(rna, spots)
    assert result["skipped"] is False
    spots_post_decomposition = result["spots_post_decomposition"]
    assert spots_post_decomposition.shape[1] == 2
    spots_subpixel = subpixel.fit_subpixel(
        rna, spots_post_decomposition, VOXEL_SIZE[1:], SPOT_RADIUS_NM_2D
    )
    assert spots_subpixel.shape == spots_post_decomposition.shape
    spots_post_clustering, clusters_found = clusters.detect_clusters(
        spots_subpixel, VOXEL_SIZE[1:], radius=300, nb_min_spots=4
    )
    assert spots_post_clustering.shape == (len(spots_subpixel), 3)
    assert clusters_found.shape[1] == 4
    assert len(clusters_found) >= 1


def test_wrong_number_of_values():
    rna = np.zeros((10, 64, 64), dtype=np.uint16)
    spots = np.array([[5, 30, 30]], dtype=np.int64)
    with pytest.raises(ValueError, match="dimensions"):
        decomposition.decompose_dense_regions(rna, spots, VOXEL_SIZE[1:], SPOT_RADIUS_NM)
