"""Tests for subpixel.py: the crop as v1 (no decomposition), synthetic spots and zero spots."""

import numpy as np
import pytest
import tifffile

from bigfish_pypeline import detection, subpixel
from synthetic import make_image

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")

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


@pytest.fixture(scope="module")
def crop_subpixel(crop_path):
    """Subpixel positions of the detected spots on the crop, for each v1 threshold."""
    image = tifffile.imread(crop_path)[:, FISH_CHANNEL]
    filtered = detection.filter_channel(image, SPOT_RADIUS_PX, bg_radius=5, bg_method="tophat")
    positions = {}
    for name, threshold in THRESHOLDS.items():
        spots = detection.detect_spots(
            filtered["rna_log"], SPOT_RADIUS_PX, elbow=False, **threshold
        )["spots"]
        positions[name] = subpixel.fit_subpixel(filtered["rna"], spots, VOXEL_SIZE, SPOT_RADIUS_NM)
    return positions


def _v1_spots(folder):
    return np.load(next(folder.glob("*_bfoutput.npz")))["spots"]


@pytest.mark.parametrize("name", ["manual18", "auto"])
def test_crop_as_v1_new_env(crop_subpixel, test_kit_folder, name):
    """Same as the v1 script run in the same env."""
    expected = _v1_spots(test_kit_folder / "reference_v1_new_env" / f"hcr_{name}_subpixel-on")
    spots_subpixel = crop_subpixel[name]
    assert spots_subpixel.shape == expected.shape
    assert spots_subpixel.dtype == expected.dtype
    assert np.all(np.abs(spots_subpixel - expected) <= 1e-6)


@pytest.mark.parametrize("name, n_spots", [("manual18", 473), ("auto", 610)])
def test_crop_as_v1_main_env(crop_subpixel, crop_reference_folder, name, n_spots):
    """Close to v1 in the main env, whose older scipy fits slightly differently."""
    expected = _v1_spots(crop_reference_folder / f"hcr_{name}_subpixel-on")
    spots_subpixel = crop_subpixel[name]
    assert spots_subpixel.shape == expected.shape == (n_spots, 3)
    difference = np.abs(spots_subpixel - expected).max(axis=1)
    assert np.mean(difference <= 0.01) >= 0.90
    assert np.mean(difference <= 0.1) >= 0.95
    assert np.all(difference <= 2)


@pytest.mark.parametrize("shape", [(10, 128, 128), (128, 128)])
def test_synthetic_spots(shape):
    image, _, _ = make_image(shape=shape, n_spots=30, seed=1)
    voxel_size = VOXEL_SIZE if len(shape) == 3 else VOXEL_SIZE[1:]
    spot_radius_px = SPOT_RADIUS_PX if len(shape) == 3 else SPOT_RADIUS_PX_2D
    spot_radius_nm = SPOT_RADIUS_NM if len(shape) == 3 else SPOT_RADIUS_NM_2D
    filtered = detection.filter_channel(image, spot_radius_px)
    rna = filtered["rna"]
    spots = detection.detect_spots(
        filtered["rna_log"], spot_radius_px, threshold_mode="auto", elbow=False
    )["spots"]
    assert len(spots) == 30

    spots_subpixel = subpixel.fit_subpixel(rna, spots, voxel_size, spot_radius_nm)
    assert spots_subpixel.shape == spots.shape
    assert spots_subpixel.dtype == np.float64
    # row i is still spot i, moved by less than one pixel
    assert np.all(np.abs(spots_subpixel - spots) < 1)

    # the same spots in reverse order give the same positions in reverse order
    reverse = subpixel.fit_subpixel(rna, spots[::-1].copy(), voxel_size, spot_radius_nm)
    assert np.array_equal(reverse, spots_subpixel[::-1])


@pytest.mark.parametrize("shape", [(10, 32, 32), (32, 32)])
def test_zero_spots(shape, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("big-fish called with no spots")

    monkeypatch.setattr(subpixel.detection, "fit_subpixel", fail)
    rna = np.zeros(shape, dtype=np.uint16)
    voxel_size = VOXEL_SIZE if len(shape) == 3 else VOXEL_SIZE[1:]
    spot_radius_nm = SPOT_RADIUS_NM if len(shape) == 3 else SPOT_RADIUS_NM_2D
    spots = np.zeros((0, len(shape)), dtype=np.int64)
    spots_subpixel = subpixel.fit_subpixel(rna, spots, voxel_size, spot_radius_nm)
    assert spots_subpixel.shape == (0, len(shape))
    assert spots_subpixel.dtype == np.float64
