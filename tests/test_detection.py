"""Tests for detection.py: spots on the test kit crop as v1, synthetic spots, thresholds, calibration and bailout."""

import numpy as np
import pytest
import tifffile
import bigfish.detection as bf_detection

from bigfish_pypeline import detection
from synthetic import make_image

FISH_CHANNEL = 2
VOXEL_SIZE = (200, 65, 65)
OPTICS = dict(ex=570, em=610, NA=1.45, RI=1.45, microscope="confocal")
SPOT_RADIUS_PX = detection.get_spot_radius_px(VOXEL_SIZE, **OPTICS)
SPOT_RADIUS_PX_2D = detection.get_spot_radius_px(VOXEL_SIZE[1:], **OPTICS)


def _reference_spots(folder):
    files = sorted(folder.rglob("*_bfoutput.npz"))
    assert len(files) == 1
    return np.load(files[0])["spots"]


def _all_found(expected, found, tolerance=1):
    """True when each expected spot has a detected spot within tolerance px on every axis."""
    for spot in expected:
        if not np.any(np.all(np.abs(found - spot) <= tolerance, axis=1)):
            return False
    return True


# --------------------------------------------------------------------------
# test kit crop against v1
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def crop_filtered(crop_path):
    image = tifffile.imread(crop_path)[:, FISH_CHANNEL]
    filtered = detection.filter_channel(image, SPOT_RADIUS_PX, bg_radius=5, bg_method="tophat")
    filtered["mask"] = detection.find_local_maxima(filtered["rna_log"], SPOT_RADIUS_PX)
    return filtered


def test_spot_radius_as_v1():
    from bigfish_pypeline.psf import calculate_psf

    psf_z, psf_yx = calculate_psf(200, 65, 570, 610, 1.45, 1.45, "confocal")
    expected = bf_detection.get_object_radius_pixel(
        voxel_size_nm=(200, 65, 65), object_radius_nm=(psf_z, psf_yx, psf_yx), ndim=3
    )
    assert SPOT_RADIUS_PX == expected
    assert SPOT_RADIUS_PX_2D == expected[1:]


def test_filter_channel_on_crop(crop_filtered):
    rna = crop_filtered["rna"]
    assert rna.shape == (11, 384, 384)
    assert rna.dtype == np.uint16
    assert np.array_equal(crop_filtered["rna_mip"], rna.max(axis=0))
    assert crop_filtered["rna_log"].shape == rna.shape


def test_crop_manual_18_as_v1(crop_filtered, crop_reference_folder):
    result = detection.detect_spots(
        crop_filtered["rna_log"], SPOT_RADIUS_PX, threshold_mode="manual", threshold=18
    )
    expected = _reference_spots(crop_reference_folder / "hcr_manual18_subpixel-off")
    assert expected.shape == (473, 3)
    assert result["threshold"] == 18
    assert result["warning"] is None
    assert np.array_equal(result["spots"], expected)


def test_crop_auto_as_v1(crop_filtered, crop_reference_folder):
    result = detection.detect_spots(
        crop_filtered["rna_log"], SPOT_RADIUS_PX, threshold_mode="auto"
    )
    expected = _reference_spots(crop_reference_folder / "hcr_auto_subpixel-off")
    assert expected.shape == (610, 3)
    assert result["threshold"] == 13.0
    assert result["auto_threshold"] == 13.0
    assert np.array_equal(result["spots"], expected)


def test_crop_elbow_values_as_bigfish(crop_filtered):
    spot_radius_nm = detection.get_spot_radius_nm(VOXEL_SIZE, **OPTICS)
    expected = bf_detection.get_elbow_values(
        crop_filtered["rna"], voxel_size=VOXEL_SIZE, spot_radius=spot_radius_nm
    )
    got = detection.get_elbow_values(crop_filtered["rna_log"], crop_filtered["mask"])
    assert np.array_equal(got[0], expected[0])
    assert np.array_equal(got[1], expected[1])
    assert got[2] == expected[2] == 13.0

    result = detection.detect_spots(
        crop_filtered["rna_log"], SPOT_RADIUS_PX, threshold_mode="manual", threshold=18
    )
    assert np.array_equal(result["elbow_thresholds"], expected[0])
    assert np.array_equal(result["elbow_counts"], expected[1])


# --------------------------------------------------------------------------
# synthetic images
# --------------------------------------------------------------------------


@pytest.mark.parametrize("shape", [(10, 128, 128), (128, 128)])
def test_synthetic_spots_found(shape):
    image, expected, _ = make_image(shape=shape, n_spots=30, seed=1)
    radius = SPOT_RADIUS_PX if len(shape) == 3 else SPOT_RADIUS_PX_2D
    filtered = detection.filter_channel(image, radius)
    if len(shape) == 2:
        assert filtered["rna_mip"] is filtered["rna"]
    result = detection.detect_spots(filtered["rna_log"], radius, threshold_mode="auto")
    spots = result["spots"]
    assert spots.shape == (30, len(shape))
    assert _all_found(expected, spots)
    assert result["warning"] is None


def test_auto_threshold_as_bigfish(crop_filtered):
    """The automatic threshold equals big-fish automated_threshold_setting."""
    expected = bf_detection.automated_threshold_setting(crop_filtered["rna_log"], crop_filtered["mask"])
    threshold, auto_threshold = detection.get_auto_threshold(crop_filtered["rna_log"], crop_filtered["mask"])
    assert threshold == auto_threshold == expected

    for shape, radius in (((10, 128, 128), SPOT_RADIUS_PX), ((128, 128), SPOT_RADIUS_PX_2D)):
        image, _, _ = make_image(shape=shape, n_spots=30, seed=3)
        rna_log = detection.filter_channel(image, radius)["rna_log"]
        mask = detection.find_local_maxima(rna_log, radius)
        expected = bf_detection.automated_threshold_setting(rna_log, mask)
        assert detection.get_auto_threshold(rna_log, mask)[1] == expected


@pytest.mark.parametrize("shape", [(10, 64, 64), (64, 64)])
def test_blank_image(shape):
    image, _, _ = make_image(shape=shape, blank=True)
    radius = SPOT_RADIUS_PX if len(shape) == 3 else SPOT_RADIUS_PX_2D
    rna_log = detection.filter_channel(image, radius)["rna_log"]

    manual = detection.detect_spots(rna_log, radius, threshold_mode="manual", threshold=18)
    assert manual["spots"].shape == (0, len(shape))
    assert manual["threshold"] == 18
    assert manual["warning"] is None

    for lower_limit in (None, 10):
        auto = detection.detect_spots(
            rna_log, radius, threshold_mode="auto", lower_limit=lower_limit
        )
        assert auto["spots"].shape == (0, len(shape))
        assert auto["spots"].dtype == np.int64
        assert auto["threshold"] is None
        assert auto["auto_threshold"] is None
        assert auto["warning"] == detection.NO_THRESHOLD_WARNING
        assert auto["elbow_thresholds"].size == 0
        assert auto["elbow_counts"].size == 0


def test_lower_limit():
    image, _, _ = make_image(n_spots=20, seed=2)
    rna_log = detection.filter_channel(image, SPOT_RADIUS_PX)["rna_log"]
    plain = detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode="auto")
    auto_value = plain["threshold"]
    assert auto_value is not None

    # a limit between the spot peak values keeps only the brighter spots
    peaks = rna_log[tuple(plain["spots"].T)]
    limit = float(np.median(peaks))
    assert limit > auto_value
    above = detection.detect_spots(
        rna_log, SPOT_RADIUS_PX, threshold_mode="auto", lower_limit=limit
    )
    assert above["threshold"] == limit
    assert above["auto_threshold"] == auto_value
    assert 0 < len(above["spots"]) < len(plain["spots"])
    manual = detection.detect_spots(
        rna_log, SPOT_RADIUS_PX, threshold_mode="manual", threshold=limit
    )
    assert np.array_equal(above["spots"], manual["spots"])

    below = detection.detect_spots(
        rna_log, SPOT_RADIUS_PX, threshold_mode="auto", lower_limit=auto_value - 5
    )
    assert below["threshold"] == auto_value
    assert np.array_equal(below["spots"], plain["spots"])


def test_noise_only_with_lower_limit():
    spots_image, _, _ = make_image(n_spots=20, seed=3)
    noise_image, _, _ = make_image(n_spots=0, seed=3)
    limit = detection.detect_spots(
        detection.filter_channel(spots_image, SPOT_RADIUS_PX)["rna_log"],
        SPOT_RADIUS_PX, threshold_mode="auto", elbow=False,
    )["threshold"]
    rna_log = detection.filter_channel(noise_image, SPOT_RADIUS_PX)["rna_log"]

    plain = detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode="auto", elbow=False)
    assert len(plain["spots"]) > 100

    limited = detection.detect_spots(
        rna_log, SPOT_RADIUS_PX, threshold_mode="auto", lower_limit=limit, elbow=False
    )
    assert limited["threshold"] == limit
    assert len(limited["spots"]) <= 5


def one_point_elbow_image():
    """A generated channel whose elbow curve has a single point: after top-hat (5 px)
    and the LoG filter, eight local maxima at 3 and one at 147."""
    from synthetic import _add_spot

    image = np.full((8, 64, 64), 100.0)
    for i in range(8):
        _add_spot(image, (4, 8 + 14 * (i % 4), 10 + 40 * (i // 4)), (1.0, 1.5, 1.5), 6)
    _add_spot(image, (4, 32, 30), (1.0, 1.5, 1.5), 300)
    return image.round().astype(np.uint16)


def one_point_rna_log():
    return detection.filter_channel(one_point_elbow_image(), SPOT_RADIUS_PX, bg_method="tophat")["rna_log"]


def test_elbow_curve_of_one_point():
    rna_log = one_point_rna_log()
    mask = detection.find_local_maxima(rna_log, SPOT_RADIUS_PX)
    assert sorted(rna_log[mask & (rna_log > 0)].tolist()) == [3] * 8 + [147]
    # big-fish itself cannot find a bend in a curve of one point
    with pytest.raises(ValueError):
        bf_detection.get_breaking_point(np.array([0.0]), np.array([2.2]))
    thresholds, counts, threshold = detection.get_elbow_values(rna_log, mask)
    assert len(thresholds) == len(counts) == 1
    assert threshold is None

    # automatic mode: no threshold and the usual warning, no spots
    detected = detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode="auto", lower_limit=2)
    assert detected["threshold"] is None and detected["auto_threshold"] is None
    assert detected["warning"] == detection.NO_THRESHOLD_WARNING
    assert len(detected["spots"]) == 0
    assert len(detected["elbow_counts"]) == 1

    # manual mode: the same spots with the elbow values and without
    with_elbow = detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode="manual", threshold=2)
    without = detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode="manual", threshold=2,
                                     elbow=False)
    assert len(with_elbow["spots"]) == 9
    np.testing.assert_array_equal(with_elbow["spots"], without["spots"])
    assert with_elbow["warning"] is None and len(with_elbow["elbow_counts"]) == 1


def test_elbow_values_cannot_fail_a_given_threshold(monkeypatch):
    rna_log = one_point_rna_log()
    expected = detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode="manual", threshold=2,
                                      elbow=False)["spots"]

    def fail(*arguments):
        raise RuntimeError("no elbow values")

    monkeypatch.setattr(detection, "get_elbow_values", fail)
    for mode in ("manual", "calibrated"):
        detected = detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode=mode, threshold=2)
        np.testing.assert_array_equal(detected["spots"], expected)
        assert detected["warning"] is None
        assert len(detected["elbow_thresholds"]) == 0 and len(detected["elbow_counts"]) == 0
    # in automatic mode the threshold itself comes from the elbow values
    with pytest.raises(RuntimeError):
        detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode="auto")


def test_elbow_curve_without_an_automatic_threshold():
    # big-fish fails on a flat curve; a curve of one point or none is too short.
    assert detection._breaking_point(np.array([0.0, 1.0, 2.0]), np.array([3.0, 3.0, 3.0])) is None
    assert detection._breaking_point(np.array([0.0]), np.array([3.0])) is None
    assert detection._breaking_point(np.zeros(0), np.zeros(0)) is None


def test_elbow_straight_falling_line_gets_big_fish_value():
    # big-fish gives the last threshold for a straight falling line, as in v1.
    thresholds, counts = np.array([0.0, 1.0, 2.0]), np.array([5.0, 4.0, 3.0])
    assert detection._breaking_point(thresholds, counts) == 2.0
    assert detection._breaking_point(thresholds, counts) == bf_detection.get_breaking_point(thresholds, counts)[0]


def test_elbow_off_and_bad_arguments():
    image, _, _ = make_image(shape=(64, 64), n_spots=5)
    rna_log = detection.filter_channel(image, SPOT_RADIUS_PX_2D)["rna_log"]
    result = detection.detect_spots(
        rna_log, SPOT_RADIUS_PX_2D, threshold_mode="calibrated", threshold=20, elbow=False
    )
    assert result["elbow_thresholds"] is None and result["elbow_counts"] is None
    with pytest.raises(ValueError, match="threshold value is needed"):
        detection.detect_spots(rna_log, SPOT_RADIUS_PX_2D, threshold_mode="manual")
    with pytest.raises(ValueError, match="Unknown threshold mode"):
        detection.detect_spots(rna_log, SPOT_RADIUS_PX_2D, threshold_mode="elbow")
    with pytest.raises(ValueError, match="three values"):
        detection.get_spot_radius_px((65,), **OPTICS)
    with pytest.raises(ValueError, match="dimensions"):
        detection.filter_channel(image, SPOT_RADIUS_PX)


def test_synthetic_generator():
    a = make_image(shape=(8, 64, 64), n_spots=10, seed=5)
    b = make_image(shape=(8, 64, 64), n_spots=10, seed=5)
    assert a[0].dtype == np.uint16 and a[0].shape == (8, 64, 64)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])

    blank, spots, _ = make_image(shape=(32, 32), blank=True)
    assert np.all(blank == blank[0, 0]) and len(spots) == 0

    image, spots, dense = make_image(
        shape=(10, 512, 512), n_spots=2500, min_spacing=5,
        dense_region={"centre": (5, 256, 256), "n_spots": 40, "spread": 3},
    )
    assert spots.shape == (2500, 3) and dense.shape == (40, 3)
    assert image[5, 250:262, 250:262].mean() > image.mean()


# --------------------------------------------------------------------------
# calibration and bailout
# --------------------------------------------------------------------------


def test_calibrate_threshold():
    entries = [
        {"image": "a", "threshold": 12.0},
        {"image": "b", "threshold": None, "reason": "could not be read"},
        {"image": "c", "threshold": 15.0},
        {"image": "d", "threshold": None},
        {"image": "e", "threshold": 20.0},
        {"image": "f", "threshold": float("nan")},
    ]
    threshold, table = detection.calibrate_threshold(entries)
    assert threshold == 15.0
    assert [row["image"] for row in table] == ["a", "b", "c", "d", "e", "f"]
    assert [row["used"] for row in table] == [True, False, True, False, True, False]
    assert table[1]["reason"] == "could not be read"
    assert table[3]["reason"] == "no automatic threshold"
    assert table[0]["reason"] is None

    threshold, _ = detection.calibrate_threshold(
        [{"image": "a", "threshold": 12.0}, {"image": "b", "threshold": 13.0}]
    )
    assert threshold == 12.5


def test_calibrate_threshold_none_usable():
    entries = [
        {"image": "a", "threshold": None, "reason": "could not be read"},
        {"image": "b", "threshold": None},
    ]
    with pytest.raises(ValueError, match="None of the calibration images"):
        detection.calibrate_threshold(entries)
    with pytest.raises(ValueError):
        detection.calibrate_threshold([])


def test_bailout():
    assert detection.exceeds_bailout(101, 100)
    assert not detection.exceeds_bailout(100, 100)
    assert not detection.exceeds_bailout(0, 100)
    assert not detection.exceeds_bailout(10**6, None)


# --------------------------------------------------------------------------
# full-size image against v1
# --------------------------------------------------------------------------


@pytest.mark.full_image
def test_full_image_as_v1(full_image_path, full_reference_folder):
    image = tifffile.imread(full_image_path)[:, FISH_CHANNEL]
    rna_log = detection.filter_channel(
        image, SPOT_RADIUS_PX, bg_radius=5, bg_method="tophat"
    )["rna_log"]
    del image

    manual = detection.detect_spots(
        rna_log, SPOT_RADIUS_PX, threshold_mode="manual", threshold=18, elbow=False
    )
    expected = _reference_spots(full_reference_folder / "hcr_manual18_subpixel-off")
    assert expected.shape == (24631, 3)
    assert np.array_equal(manual["spots"], expected)

    auto = detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode="auto", elbow=False)
    expected = _reference_spots(full_reference_folder / "hcr_auto_subpixel-off")
    assert expected.shape == (27514, 3)
    assert auto["threshold"] == 15.0
    assert np.array_equal(auto["spots"], expected)
