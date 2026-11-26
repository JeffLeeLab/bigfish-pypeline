"""Pre-treatment of the segmentation channel before Cellpose."""

import numpy as np
import pytest
from scipy import ndimage

from bigfish_pypeline import io
from bigfish_pypeline.background import subtract_background
from bigfish_pypeline.segmentation import describe_pretreatment, pretreat_channel
from synthetic import make_image

DAPI_CHANNEL = 0
ALL_OFF = dict(clip=False, background=False, median_px=None, gaussian_sigma_px=None)


@pytest.fixture
def stack():
    """Small uint16 stack (z, y, x) with known values."""
    rng = np.random.default_rng(1)
    return rng.integers(0, 300, size=(4, 40, 50)).astype(np.uint16)


# Projection

def test_max_projection(stack):
    got = pretreat_channel(stack, projection="max", **ALL_OFF)
    np.testing.assert_array_equal(got, stack.max(axis=0))
    assert got.dtype == np.uint16
    assert got.shape == (40, 50)


def test_mean_projection(stack):
    got = pretreat_channel(stack, projection="mean", **ALL_OFF)
    np.testing.assert_allclose(got, stack.astype(np.float64).mean(axis=0))
    assert got.dtype == np.float64


@pytest.mark.parametrize("projection", ["max", "mean"])
def test_2d_image_used_as_it_is(projection):
    image = make_image(shape=(64, 64), n_spots=5)[0]
    got = pretreat_channel(image, projection=projection, **ALL_OFF)
    np.testing.assert_array_equal(got, image)
    assert got.dtype == image.dtype


@pytest.mark.parametrize("projection", ["max", "mean"])
def test_every_step_off_returns_projection(stack, projection):
    expected = stack.max(axis=0) if projection == "max" else stack.mean(axis=0)
    got = pretreat_channel(stack, projection=projection, **ALL_OFF)
    np.testing.assert_array_equal(got, expected)
    assert got.dtype == expected.dtype


def test_3d_and_2d_give_the_same_result_for_one_plane():
    image = make_image(shape=(64, 64), n_spots=5)[0]
    settings = dict(clip=True, clip_value=500, bg_radius=10, median_px=3, gaussian_sigma_px=1.0)
    np.testing.assert_array_equal(
        pretreat_channel(image[None], **settings), pretreat_channel(image, **settings)
    )


# Clip

def test_clip_sets_values_above_clip_value():
    image = np.array([[0, 50, 100], [101, 200, 65535]], dtype=np.uint16)
    got = pretreat_channel(image, clip=True, clip_value=100, background=False)
    np.testing.assert_array_equal(got, [[0, 50, 100], [100, 100, 100]])
    assert got.dtype == np.uint16


def test_clip_on_mean_projection_keeps_decimals():
    stack = np.array([[[10, 300]], [[11, 300]]], dtype=np.uint16)
    got = pretreat_channel(stack, projection="mean", clip=True, clip_value=100.5,
                           background=False)
    np.testing.assert_array_equal(got, [[10.5, 100.5]])
    assert got.dtype == np.float64


def test_clip_value_with_decimals_on_whole_number_image():
    image = np.array([[99, 100, 101]], dtype=np.uint16)
    got = pretreat_channel(image, clip=True, clip_value=100.5, background=False)
    np.testing.assert_array_equal(got, [[99, 100, 100]])
    assert got.dtype == np.uint16


def test_clip_off_by_default():
    image = np.full((30, 30), 5000, dtype=np.uint16)
    got = pretreat_channel(image, background=False)
    np.testing.assert_array_equal(got, image)


# Background subtraction

@pytest.mark.parametrize("bg_method", ["rolling_ball", "tophat"])
def test_background_on_flat_image_gives_zero(bg_method):
    image = np.full((60, 60), 400, dtype=np.uint16)
    got = pretreat_channel(image, bg_method=bg_method, bg_radius=10)
    np.testing.assert_array_equal(got, 0)
    assert got.dtype == np.uint16


@pytest.mark.parametrize("bg_method", ["rolling_ball", "tophat"])
def test_background_matches_direct_call(bg_method):
    image = make_image(shape=(5, 96, 96), n_spots=15, background=300)[0]
    projected = image.max(axis=0)
    got = pretreat_channel(image, bg_method=bg_method, bg_radius=8)
    np.testing.assert_array_equal(got, subtract_background(projected, 8, method=bg_method))


def test_background_on_by_default_with_rolling_ball_200():
    image = make_image(shape=(3, 64, 64), n_spots=5)[0]
    got = pretreat_channel(image)
    np.testing.assert_array_equal(got, subtract_background(image.max(axis=0), 200))


@pytest.mark.parametrize("bg_method", ["rolling_ball", "tophat"])
def test_mean_projection_gives_no_negative_values(bg_method):
    image = make_image(shape=(3, 64, 64), n_spots=5, noise=20)[0]
    subtracted = subtract_background(image.mean(axis=0), 10, method=bg_method)
    if bg_method == "rolling_ball":
        # rolling ball on decimal numbers leaves values below the background negative
        assert subtracted.min() < 0
    got = pretreat_channel(image, projection="mean", bg_method=bg_method, bg_radius=10)
    assert got.dtype == np.float64
    assert got.min() >= 0
    np.testing.assert_array_equal(got, np.maximum(subtracted, 0))


@pytest.mark.parametrize("bg_method", ["rolling_ball", "tophat"])
def test_mean_projection_gives_no_negative_values_after_every_step(bg_method):
    image = make_image(shape=(3, 64, 64), n_spots=5, noise=20)[0]
    got = pretreat_channel(image, projection="mean", bg_method=bg_method, bg_radius=10,
                           median_px=3, gaussian_sigma_px=1.0)
    assert got.min() >= 0


def test_rolling_ball_on_crop_dapi(crop_path):
    dapi = io.read_channel(crop_path, "ZCYX", DAPI_CHANNEL)
    got = pretreat_channel(dapi, projection="max", bg_method="rolling_ball", bg_radius=200)
    expected = subtract_background(dapi.max(axis=0), 200, method="rolling_ball")
    np.testing.assert_array_equal(got, expected)
    assert got.dtype == expected.dtype


# Median and Gaussian filters

def test_median_removes_single_bright_pixel():
    image = np.full((21, 21), 10, dtype=np.uint16)
    image[10, 10] = 1000
    got = pretreat_channel(image, background=False, median_px=3)
    np.testing.assert_array_equal(got, 10)
    assert got.dtype == np.uint16


def test_median_matches_scipy():
    image = make_image(shape=(64, 64), n_spots=10)[0]
    got = pretreat_channel(image, background=False, median_px=5)
    np.testing.assert_array_equal(got, ndimage.median_filter(image, size=5))


def test_gaussian_spreads_single_bright_pixel():
    image = np.zeros((41, 41), dtype=np.uint16)
    image[20, 20] = 1000
    got = pretreat_channel(image, background=False, gaussian_sigma_px=2.0)
    assert got.dtype == np.float64
    assert got.sum() == pytest.approx(1000)
    assert np.unravel_index(got.argmax(), got.shape) == (20, 20)
    assert got[20, 20] == pytest.approx(1000 / (2 * np.pi * 2.0 ** 2), rel=0.02)
    np.testing.assert_allclose(got, ndimage.gaussian_filter(image.astype(np.float64), 2.0))


def test_gaussian_on_decimal_image_keeps_its_type():
    image = np.zeros((21, 21), dtype=np.float32)
    image[10, 10] = 1
    got = pretreat_channel(image, background=False, gaussian_sigma_px=1.5)
    assert got.dtype == np.float32


# All steps

@pytest.mark.parametrize("projection", ["max", "mean"])
@pytest.mark.parametrize("bg_method", ["rolling_ball", "tophat"])
def test_all_steps_in_order(projection, bg_method):
    image = make_image(shape=(5, 96, 96), n_spots=20, background=200, noise=15)[0]
    got = pretreat_channel(
        image, projection=projection, clip=True, clip_value=600,
        background=True, bg_method=bg_method, bg_radius=12,
        median_px=3, gaussian_sigma_px=1.5,
    )
    expected = image.max(axis=0) if projection == "max" else image.mean(axis=0)
    expected = subtract_background(expected, 12, method=bg_method)
    expected = np.maximum(expected, 0).astype(expected.dtype)
    expected = np.clip(expected, 0, 600).astype(expected.dtype)
    expected = ndimage.median_filter(expected, size=3)
    expected = ndimage.gaussian_filter(expected.astype(np.float64), 1.5)
    np.testing.assert_array_equal(got, expected)
    assert got.shape == (96, 96)
    assert got.dtype == np.float64


@pytest.mark.parametrize("bg_method", ["rolling_ball", "tophat"])
def test_clip_runs_after_background_subtraction(bg_method):
    """A camera offset of 500 above a clip value of 150 does not flatten the image."""
    image = np.full((40, 40), 500, dtype=np.uint16)
    image[18:23, 18:23] = 800
    got = pretreat_channel(image, clip=True, clip_value=150, bg_method=bg_method, bg_radius=10)
    expected = np.zeros((40, 40), dtype=np.uint16)
    expected[18:23, 18:23] = 150
    np.testing.assert_array_equal(got, expected)
    # clipped before background subtraction, the same image would be flat
    clipped_first = np.clip(image, 0, 150).astype(np.uint16)
    np.testing.assert_array_equal(subtract_background(clipped_first, 10, method=bg_method), 0)


def test_input_is_not_changed(stack):
    before = stack.copy()
    pretreat_channel(stack, clip=True, clip_value=50, bg_radius=5, median_px=3,
                     gaussian_sigma_px=1.0)
    np.testing.assert_array_equal(stack, before)


# Messages

def test_unknown_projection():
    with pytest.raises(ValueError, match="Unknown Z projection 'sum'. Use one of: max, mean."):
        pretreat_channel(np.zeros((10, 10)), projection="sum")


def test_unknown_background_method():
    with pytest.raises(ValueError, match="Unknown background subtraction method 'ball'"):
        pretreat_channel(np.zeros((10, 10)), bg_method="ball")


def test_wrong_number_of_dimensions():
    with pytest.raises(ValueError, match="this one has 4 dimensions"):
        pretreat_channel(np.zeros((2, 2, 10, 10)))


@pytest.mark.parametrize("median_px", [0, -3, 2.5])
def test_bad_median_size(median_px):
    with pytest.raises(ValueError, match="median filter size"):
        pretreat_channel(np.zeros((10, 10)), median_px=median_px)


@pytest.mark.parametrize("sigma", [0, -1])
def test_bad_gaussian_sigma(sigma):
    with pytest.raises(ValueError, match="Gaussian filter sigma"):
        pretreat_channel(np.zeros((10, 10)), gaussian_sigma_px=sigma)


# Description for figure titles

def test_description_defaults():
    assert describe_pretreatment() == "max projection | rolling ball 200 px"


def test_description_every_step():
    text = describe_pretreatment(projection="mean", clip=True, clip_value=100,
                                 bg_method="tophat", bg_radius=50,
                                 median_px=5, gaussian_sigma_px=1.5)
    assert text == "mean projection | top-hat 50 px | clip 100 | median 5 px | Gaussian 1.5 px"


def test_description_clip_without_background_subtraction():
    text = describe_pretreatment(clip=True, clip_value=120, background=False)
    assert text == "max projection | no background subtraction | clip 120"


def test_description_background_off():
    text = describe_pretreatment(background=False)
    assert text == "max projection | no background subtraction"


def test_description_unknown_projection():
    with pytest.raises(ValueError, match="Unknown Z projection"):
        describe_pretreatment(projection="sum")


# Planes for the projection

@pytest.fixture
def planes_stack():
    """Six planes of 1 to 6 everywhere, with a bright pixel in plane 1 only."""
    stack = np.ones((6, 20, 20), dtype=np.uint16) * np.arange(1, 7, dtype=np.uint16)[:, None, None]
    stack[1, 5, 5] = 5000
    return stack


@pytest.mark.parametrize("projection", ["max", "mean"])
@pytest.mark.parametrize("z_planes, kept", [
    ((2, 4), slice(2, 5)),
    ((2, None), slice(2, None)),
    ((None, 3), slice(0, 4)),
    ((1, 1), slice(1, 2)),
    ((0, 5), slice(None)),
])
def test_projection_of_chosen_planes(planes_stack, projection, z_planes, kept):
    got = pretreat_channel(planes_stack, projection=projection, z_planes=z_planes, **ALL_OFF)
    chosen = planes_stack[kept]
    expected = chosen.max(axis=0) if projection == "max" else chosen.mean(axis=0)
    np.testing.assert_array_equal(got, expected)
    assert got.dtype == expected.dtype


@pytest.mark.parametrize("projection", ["max", "mean"])
def test_bright_pixel_in_a_left_out_plane_is_not_projected(planes_stack, projection):
    got = pretreat_channel(planes_stack, projection=projection, z_planes=(2, 5), **ALL_OFF)
    assert got.max() < 10
    every = pretreat_channel(planes_stack, projection=projection, **ALL_OFF)
    assert every[5, 5] > 10


@pytest.mark.parametrize("z_planes", [None, (None, None)])
def test_every_plane_gives_the_same_result_as_before(z_planes):
    image = make_image(shape=(5, 96, 96), n_spots=20, background=200, noise=15)[0]
    settings = dict(clip=True, clip_value=600, bg_radius=12, median_px=3, gaussian_sigma_px=1.5)
    np.testing.assert_array_equal(
        pretreat_channel(image, z_planes=z_planes, **settings), pretreat_channel(image, **settings)
    )


def test_every_step_runs_after_the_projection_of_chosen_planes():
    image = make_image(shape=(5, 96, 96), n_spots=20, background=200, noise=15)[0]
    settings = dict(clip=True, clip_value=600, bg_radius=12, median_px=3, gaussian_sigma_px=1.5)
    np.testing.assert_array_equal(
        pretreat_channel(image, z_planes=(1, 3), **settings), pretreat_channel(image[1:4], **settings)
    )


@pytest.mark.parametrize("z_planes, plane", [((2, 6), "plane 6"), ((6, None), "plane 6"),
                                              ((None, 9), "plane 9"), ((7, 9), "planes 7 and 9")])
def test_plane_beyond_the_image(planes_stack, z_planes, plane):
    with pytest.raises(ValueError) as raised:
        pretreat_channel(planes_stack, z_planes=z_planes, **ALL_OFF)
    verb = "does" if plane.startswith("plane ") else "do"
    assert str(raised.value) == (
        f"Planes for the projection: the image has 6 planes (numbered 0 to 5), so {plane} {verb} not exist."
    )


def test_plane_beyond_an_image_of_one_plane():
    with pytest.raises(ValueError, match=r"the image has 1 plane \(plane 0\), so plane 1 does not exist"):
        pretreat_channel(np.zeros((1, 10, 10), dtype=np.uint16), z_planes=(1, None), **ALL_OFF)


@pytest.mark.parametrize("z_planes", [(0, None), (None, 0), (0, 0)])
def test_planes_given_for_a_2d_image(z_planes):
    with pytest.raises(ValueError) as raised:
        pretreat_channel(np.zeros((10, 10), dtype=np.uint16), z_planes=z_planes)
    assert str(raised.value) == (
        "Planes for the projection were given, but the segmentation channel is a 2D image without planes."
    )


@pytest.mark.parametrize("z_planes, problem", [
    ((3, 2), "The first plane for the projection (3) is after the last (2)."),
    ((-1, None), "Plane numbers for the projection must be whole numbers of 0 or more; got -1."),
    ((None, 2.5), "Plane numbers for the projection must be whole numbers of 0 or more; got 2.5."),
    ((True, None), "Plane numbers for the projection must be whole numbers of 0 or more; got True."),
])
def test_bad_planes(planes_stack, z_planes, problem):
    with pytest.raises(ValueError) as raised:
        pretreat_channel(planes_stack, z_planes=z_planes)
    assert str(raised.value) == problem
    with pytest.raises(ValueError):
        describe_pretreatment(z_planes=z_planes)


@pytest.mark.parametrize("z_planes, text", [
    (None, "max projection | rolling ball 200 px"),
    ((None, None), "max projection | rolling ball 200 px"),
    ((12, 30), "max projection of planes 12–30 | rolling ball 200 px"),
    ((12, None), "max projection from plane 12 | rolling ball 200 px"),
    ((None, 30), "max projection up to plane 30 | rolling ball 200 px"),
    ((12, 12), "max projection of plane 12 | rolling ball 200 px"),
])
def test_description_names_the_planes(z_planes, text):
    assert describe_pretreatment(z_planes=z_planes) == text


def test_description_of_mean_projection_with_planes():
    text = describe_pretreatment(projection="mean", z_planes=(0, 4), background=False)
    assert text == "mean projection of planes 0–4 | no background subtraction"
