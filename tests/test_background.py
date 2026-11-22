"""Tests for background.py: top-hat as image_utils and scikit-image, rolling ball as ImageJ."""

import json
from pathlib import Path

import numpy as np
import pytest
import tifffile
from skimage.morphology import black_tophat, disk, white_tophat

from bigfish_pypeline import image_utils, rolling_ball
from bigfish_pypeline.background import subtract_background

REFERENCE = Path(__file__).resolve().parent / "data" / "rolling_ball" / "imagej_reference.npz"
FISH_CHANNEL = 2


def _synthetic(shape=(40, 50), seed=0):
    """uint16 image: spots on a sloping background with noise."""
    rng = np.random.default_rng(seed)
    h, w = shape
    yy, xx = np.mgrid[:h, :w]
    image = 200.0 + 2.0 * xx + 1.0 * yy + rng.normal(0, 5, shape)
    for y, x in [(10, 10), (25, 30), (30, 12)]:
        image += 300.0 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / 4.0)
    return np.round(image).astype(np.uint16)


@pytest.fixture(scope="module")
def crop_rna(crop_path):
    """FISH channel of the test kit crop, (z, y, x)."""
    return tifffile.imread(crop_path)[:, FISH_CHANNEL]


# --------------------------------------------------------------------------
# top-hat
# --------------------------------------------------------------------------


@pytest.mark.parametrize("light_bg", [False, True])
def test_tophat_matches_image_utils_on_crop(crop_rna, light_bg):
    expected = np.array(
        [image_utils.subtract_background(z, 5, light_bg=light_bg) for z in crop_rna]
    )
    got = subtract_background(crop_rna, 5, light_bg=light_bg, method="tophat")
    assert got.dtype == expected.dtype == crop_rna.dtype
    assert np.array_equal(got, expected)


@pytest.mark.parametrize("light_bg", [False, True])
def test_tophat_2d_matches_image_utils(light_bg):
    image = _synthetic()
    expected = image_utils.subtract_background(image, 5, light_bg=light_bg)
    got = subtract_background(image, 5, light_bg=light_bg, method="tophat")
    assert got.dtype == image.dtype
    assert np.array_equal(got, expected)


def test_tophat_matches_scikit_image():
    image = _synthetic()
    assert np.array_equal(
        subtract_background(image, 4, method="tophat"), white_tophat(image, disk(4))
    )
    assert np.array_equal(
        subtract_background(image, 4, light_bg=True, method="tophat"),
        black_tophat(image, disk(4)),
    )


def test_tophat_3d_is_per_plane():
    stack = np.stack([_synthetic(seed=s) for s in range(3)])
    got = subtract_background(stack, 3, method="tophat")
    assert got.shape == stack.shape
    for z in range(3):
        assert np.array_equal(got[z], white_tophat(stack[z], disk(3)))


# --------------------------------------------------------------------------
# rolling ball
# --------------------------------------------------------------------------


def test_rolling_ball_is_default():
    image = _synthetic()
    assert np.array_equal(
        subtract_background(image, 5), subtract_background(image, 5, method="rolling_ball")
    )


@pytest.mark.parametrize("light_bg", [False, True])
def test_rolling_ball_3d_is_per_plane(light_bg):
    stack = np.stack([_synthetic(seed=s) for s in range(3)])
    got = subtract_background(stack, 5, light_bg=light_bg)
    assert got.shape == stack.shape
    assert got.dtype == np.uint16
    for z in range(3):
        expected = rolling_ball.subtract_background(stack[z], 5, light_background=light_bg)
        assert np.array_equal(got[z], expected)


def test_rolling_ball_2d():
    image = _synthetic()
    got = subtract_background(image, 5)
    assert got.shape == image.shape and got.dtype == np.uint16
    assert np.array_equal(got, rolling_ball.subtract_background(image, 5))


@pytest.mark.parametrize("dtype", [np.float32, np.float64, np.int32])
def test_rolling_ball_float_result(dtype):
    image = _synthetic().astype(dtype)
    got = subtract_background(image, 5)
    assert got.dtype == np.float64
    assert np.allclose(got, rolling_ball.subtract_background(image, 5))


@pytest.mark.parametrize("output", ["sub_u16_r50", "sub_u16_r50_light"])
def test_rolling_ball_matches_imagej(output):
    with np.load(REFERENCE) as ref:
        cases = {c["output"]: c for c in json.loads(str(ref["meta"]))["cases"]}
        case = cases[output]
        image = ref[case["input"]]
        expected = ref[output]
    assert case["presmooth"] and not case["create_background"]
    stack = np.stack([image, image])
    got = subtract_background(stack, case["radius"], light_bg=case["light_background"])
    assert got.dtype == np.uint16
    for plane in got:
        diff = np.abs(plane.astype(np.int64) - expected.astype(np.int64))
        assert diff.max() <= 1
        assert np.mean(diff > 0) < 0.005


# --------------------------------------------------------------------------
# bad input
# --------------------------------------------------------------------------


def test_unknown_method():
    with pytest.raises(ValueError, match="Unknown background subtraction method 'gaussian'"):
        subtract_background(_synthetic(), 5, method="gaussian")


@pytest.mark.parametrize("shape", [(10,), (2, 2, 10, 10)])
def test_wrong_dimensions(shape):
    with pytest.raises(ValueError, match="2D .* or 3D"):
        subtract_background(np.zeros(shape, dtype=np.uint16), 5, method="tophat")
