"""Tests for the steps of one channel (steps.py): each step alone on the tissue crop,
and the steps called one by one giving the tables of a batch run."""

import shutil

import numpy as np
import pytest
import tifffile

from bigfish_pypeline import batch, detection, io, outputs, steps
from bigfish_pypeline.cells import assign_cells
from bigfish_pypeline.clusters import detect_clusters
from bigfish_pypeline.config import load_config, parse_config
from bigfish_pypeline.decomposition import (
    NO_SPOT_MODEL_WARNING,
    NO_SPOTS_WARNING,
    decompose_dense_regions,
    get_seed,
)
from bigfish_pypeline.measurements import measure_spots
from bigfish_pypeline.segmentation import read_label_file_contents
from bigfish_pypeline.subpixel import fit_subpixel
from conftest import CROP_NAME, FISH_CHANNEL

VOXEL_SIZE = (200, 65, 65)  # nm: z, y, x
EX, EM, NA, RI = 570, 610, 1.45, 1.45
QC_OFF = {"elbow_plot": False, "detection": False, "reference_spot": False, "cellpose": False,
          "final": "none"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def kit_config(crop_config_path, changes=None, segmentation=None, npz=False, resolved=None):
    """The test kit config, with QC files off and some settings changed.

    changes: channel settings by dotted name, e.g. {"threshold__mode": "auto"}.
    segmentation: settings of the segmentation block to change.
    resolved: calibrated thresholds by channel index.
    """
    config = load_config(crop_config_path)
    data = config.to_dict()
    data["outputs"]["qc"] = dict(QC_OFF)
    data["outputs"]["npz"] = npz
    channel = data["channels"][0]
    for name, value in (changes or {}).items():
        group, setting = name.split("__")
        channel[group][setting] = value
    data["segmentation"].update(segmentation or {})
    config = parse_config(data, config.config_folder)
    if resolved is not None:
        config = config.with_resolved([f"{CROP_NAME}.tif"], resolved)
    return config


def run_steps(config, image_name, image, masks):
    """Every step of the config's first channel, one call at a time, as the notebook calls them."""
    channel = config.channels[0]
    radius = steps.spot_radius(config, channel)
    filtered = steps.filter_image(config, channel, image, radius["spot_radius_px"])
    detected = steps.detect(config, channel, filtered["rna_log"], radius["spot_radius_px"])
    assert steps.bailout_reason(config, channel, detected["spots"]) is None
    decomposed = steps.decompose(config, channel, image_name, filtered["rna"], detected["spots"],
                                 radius["spot_radius_nm"])
    spots = decomposed["spots_post_decomposition"]
    fitted = steps.fit_subpixel(config, channel, filtered["rna"], spots, radius["spot_radius_nm"])
    clustered = steps.find_clusters(config, channel, spots, fitted["spots_subpixel"])
    measured = steps.measure(config, channel, filtered["rna"], filtered["rna_log"], spots,
                             radius["spot_radius_px"])
    assigned = steps.assign_to_cells(config, channel, masks, spots, clustered)
    return steps.make_tables(config, channel, image_name, spots, fitted, clustered, measured, assigned)


def assert_as_batch(config, image_name, image_path, image, masks, label_folder, tmp_path):
    """The tables (and `.npz` arrays) of the steps called one by one are those
    `process_image` writes for the same image and config, byte for byte."""
    batch_folder = tmp_path / "batch"
    summary = batch.process_image(config, image_name, image_path, batch_folder, label_folder=label_folder)
    assert [row["status"] for row in summary["rows"]] == ["done"], summary["rows"]

    tables = run_steps(config, image_name, image, masks)
    channel = config.channels[0].index
    steps_folder = tmp_path / "steps"
    (steps_folder / outputs.PER_IMAGE_FOLDER_NAME).mkdir(parents=True)
    outputs.write_image_tables(
        steps_folder, image_name, outputs.make_images_table(summary["rows"]),
        spots=[tables["spots"]],
        clusters=[tables["clusters"]] if batch.run_has_clusters(config) else None,
        cells=[tables["cells"]] if masks is not None else None,
        arrays={channel: tables["arrays"]} if tables["arrays"] is not None else None,
    )
    for kind in ("spots", "clusters", "cells"):
        written = outputs.per_image_path(batch_folder, image_name, kind)
        from_steps = outputs.per_image_path(steps_folder, image_name, kind)
        assert written.is_file() == from_steps.is_file(), kind
        if written.is_file():
            assert from_steps.read_bytes() == written.read_bytes(), kind
    written = outputs.npz_path(batch_folder, image_name, channel)
    from_steps = outputs.npz_path(steps_folder, image_name, channel)
    assert written.is_file() == from_steps.is_file()
    if written.is_file():
        with np.load(written) as expected, np.load(from_steps) as found:
            assert sorted(found.files) == sorted(expected.files)
            for name in expected.files:
                np.testing.assert_array_equal(found[name], expected[name])
    return tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def config(crop_config_path):
    return kit_config(crop_config_path)


@pytest.fixture(scope="module")
def channel(config):
    return config.channels[0]


@pytest.fixture(scope="module")
def image(crop_path):
    return io.read_channel(crop_path, "ZCYX", FISH_CHANNEL)


@pytest.fixture(scope="module")
def masks(test_kit_folder):
    return read_label_file_contents(test_kit_folder, CROP_NAME, (384, 384))[0]


@pytest.fixture(scope="module")
def radius(config, channel):
    return steps.spot_radius(config, channel)


@pytest.fixture(scope="module")
def filtered(config, channel, image, radius):
    return steps.filter_image(config, channel, image, radius["spot_radius_px"])


@pytest.fixture(scope="module")
def detected(config, channel, filtered, radius):
    return steps.detect(config, channel, filtered["rna_log"], radius["spot_radius_px"])


@pytest.fixture(scope="module")
def decomposed(config, channel, filtered, detected, radius):
    return steps.decompose(config, channel, CROP_NAME, filtered["rna"], detected["spots"],
                           radius["spot_radius_nm"])


def with_changes(crop_config_path, **changes):
    """The test kit config and its channel, with channel settings changed (dotted names)."""
    config = kit_config(crop_config_path, changes)
    return config, config.channels[0]


# ---------------------------------------------------------------------------
# Step 2: spot radius
# ---------------------------------------------------------------------------


def test_spot_radius_from_the_microscope_and_wavelengths(config, channel, radius):
    assert radius["spot_radius_px"] == detection.get_spot_radius_px(VOXEL_SIZE, EX, EM, NA, RI, "confocal")
    assert radius["spot_radius_nm"] == detection.get_spot_radius_nm(VOXEL_SIZE, EX, EM, NA, RI, "confocal")
    assert len(radius["spot_radius_px"]) == 3


def test_spot_radius_in_2d(crop_config_path):
    data = kit_config(crop_config_path).to_dict()
    data["image"] = {"axes": "CYX", "voxel_size_nm": {"yx": 65}}
    config = parse_config(data)
    radius = steps.spot_radius(config, config.channels[0])
    assert radius["spot_radius_px"] == detection.get_spot_radius_px((65, 65), EX, EM, NA, RI, "confocal")
    assert len(radius["spot_radius_nm"]) == 2


def test_spot_radius_reads_the_wavelengths(crop_config_path, radius):
    config, channel = with_changes(crop_config_path)
    data = config.to_dict()
    data["channels"][0]["em"] = 700
    data["microscope"]["type"] = "widefield"
    config = parse_config(data)
    other = steps.spot_radius(config, config.channels[0])
    assert other["spot_radius_nm"] == detection.get_spot_radius_nm(VOXEL_SIZE, EX, 700, NA, RI, "widefield")
    assert other["spot_radius_nm"] != radius["spot_radius_nm"]


# ---------------------------------------------------------------------------
# Step 3: background and LoG filter
# ---------------------------------------------------------------------------


def test_filter_image_with_the_channels_background(image, radius, filtered):
    expected = detection.filter_channel(image, radius["spot_radius_px"], bg_radius=5, bg_method="tophat")
    assert sorted(filtered) == ["rna", "rna_log", "rna_mip"]
    for name in ("rna", "rna_log", "rna_mip"):
        np.testing.assert_array_equal(filtered[name], expected[name])


def test_filter_image_reads_the_background_method_and_radius(crop_config_path, image, radius, filtered):
    config, channel = with_changes(crop_config_path, background__method="rolling_ball",
                                   background__radius_px=8)
    found = steps.filter_image(config, channel, image, radius["spot_radius_px"])
    expected = detection.filter_channel(image, radius["spot_radius_px"], bg_radius=8,
                                        bg_method="rolling_ball")
    np.testing.assert_array_equal(found["rna_log"], expected["rna_log"])
    assert not np.array_equal(found["rna"], filtered["rna"])


# ---------------------------------------------------------------------------
# Step 4: detection
# ---------------------------------------------------------------------------


def test_threshold_settings_of_each_mode(crop_config_path):
    config, channel = with_changes(crop_config_path)
    assert steps.threshold_settings(config, channel) == (18, None)
    config, channel = with_changes(crop_config_path, threshold__mode="auto", threshold__value=None,
                                   threshold__lower_limit=12)
    assert steps.threshold_settings(config, channel) == (None, 12)
    config = kit_config(crop_config_path, {"threshold__mode": "calibrated", "threshold__value": None,
                                           "threshold__calibration_filter": "crop"}, resolved={2: 21.5})
    assert steps.threshold_settings(config, config.channels[0]) == (21.5, None)


def test_detect_with_a_manual_threshold(channel, config, filtered, radius, detected):
    expected = detection.detect_spots(filtered["rna_log"], radius["spot_radius_px"], "manual", 18, elbow=False)
    np.testing.assert_array_equal(detected["spots"], expected["spots"])
    assert detected["threshold"] == 18
    assert detected["auto_threshold"] is None
    assert detected["elbow_thresholds"] is None and detected["elbow_counts"] is None
    assert detected["warning"] is None


def test_detect_gives_the_elbow_values_when_asked(config, channel, filtered, radius, detected):
    found = steps.detect(config, channel, filtered["rna_log"], radius["spot_radius_px"], elbow=True)
    np.testing.assert_array_equal(found["spots"], detected["spots"])
    assert len(found["elbow_thresholds"]) == len(found["elbow_counts"]) > 0


def test_detect_with_an_automatic_threshold_and_lower_limit(crop_config_path, filtered, radius):
    config, channel = with_changes(crop_config_path, threshold__mode="auto", threshold__value=None)
    automatic = steps.detect(config, channel, filtered["rna_log"], radius["spot_radius_px"])
    assert automatic["threshold"] == automatic["auto_threshold"] is not None

    limit = automatic["auto_threshold"] + 5
    config, channel = with_changes(crop_config_path, threshold__mode="auto", threshold__value=None,
                                   threshold__lower_limit=limit)
    limited = steps.detect(config, channel, filtered["rna_log"], radius["spot_radius_px"])
    assert limited["threshold"] == limit
    assert limited["auto_threshold"] == automatic["auto_threshold"]
    expected = detection.detect_spots(filtered["rna_log"], radius["spot_radius_px"], "auto",
                                      lower_limit=limit, elbow=False)
    np.testing.assert_array_equal(limited["spots"], expected["spots"])
    assert len(limited["spots"]) < len(automatic["spots"])


def test_detect_with_a_calibrated_threshold(crop_config_path, filtered, radius):
    config = kit_config(crop_config_path, {"threshold__mode": "calibrated", "threshold__value": None,
                                           "threshold__calibration_filter": "crop"}, resolved={2: 25})
    found = steps.detect(config, config.channels[0], filtered["rna_log"], radius["spot_radius_px"])
    expected = detection.detect_spots(filtered["rna_log"], radius["spot_radius_px"], "manual", 25, elbow=False)
    assert found["threshold"] == 25
    np.testing.assert_array_equal(found["spots"], expected["spots"])


@pytest.mark.parametrize("resolved", [None, {}])
def test_missing_calibrated_threshold(crop_config_path, filtered, radius, resolved):
    config = kit_config(crop_config_path, {"threshold__mode": "calibrated", "threshold__value": None,
                                           "threshold__calibration_filter": "crop"}, resolved=resolved)
    channel = config.channels[0]
    message = ("no calibrated threshold for channel 2: the calibration has not been run or gave no value")
    with pytest.raises(steps.ChannelError, match=message):
        steps.threshold_settings(config, channel)
    with pytest.raises(steps.ChannelError, match=message):
        steps.detect(config, channel, filtered["rna_log"], radius["spot_radius_px"])


def test_channel_error_is_the_batchs():
    assert batch.ChannelError is steps.ChannelError


# ---------------------------------------------------------------------------
# Bailout
# ---------------------------------------------------------------------------


def test_bailout_off_never_skips(crop_config_path, detected):
    config, channel = with_changes(crop_config_path, bailout__enabled=False, bailout__max_spots=1)
    assert steps.bailout_reason(config, channel, detected["spots"]) is None


def test_bailout_on(crop_config_path, crop_path, detected, tmp_path):
    n_spots = len(detected["spots"])
    config, channel = with_changes(crop_config_path, bailout__enabled=True, bailout__max_spots=n_spots)
    assert steps.bailout_reason(config, channel, detected["spots"]) is None

    config, channel = with_changes(crop_config_path, bailout__enabled=True, bailout__max_spots=10)
    reason = steps.bailout_reason(config, channel, detected["spots"])
    assert reason == f"bailout: {n_spots} spots detected, above the limit of 10"
    summary = batch.process_image(config, CROP_NAME, crop_path, tmp_path / "run")
    assert summary["rows"][0]["status"] == "skipped"
    assert summary["rows"][0]["reason"] == reason


# ---------------------------------------------------------------------------
# Step 5: decomposition
# ---------------------------------------------------------------------------


def test_decompose_with_the_runs_seed(config, filtered, detected, radius, decomposed):
    expected = decompose_dense_regions(
        filtered["rna"], detected["spots"], VOXEL_SIZE, radius["spot_radius_nm"], alpha=0.5, beta=1,
        seed=get_seed(0, CROP_NAME, FISH_CHANNEL),
    )
    np.testing.assert_array_equal(decomposed["spots_post_decomposition"], expected["spots_post_decomposition"])
    np.testing.assert_array_equal(decomposed["reference_spot"], expected["reference_spot"])
    assert len(decomposed["spots_post_decomposition"]) > len(detected["spots"])
    assert decomposed["reference_spot_for_qc"] is True
    assert decomposed["warning"] == expected["warning"]


def test_decompose_reads_the_seed_and_the_image_name(crop_config_path, filtered, detected, radius, monkeypatch):
    seeds = []

    def record(*arguments, seed=None, **keywords):
        seeds.append(seed)
        return {"spots_post_decomposition": arguments[1], "reference_spot": None, "skipped": True,
                "warning": None}

    monkeypatch.setattr(steps, "decompose_dense_regions", record)
    data = kit_config(crop_config_path).to_dict()
    data["run"]["seed"] = 7
    config = parse_config(data)
    steps.decompose(config, config.channels[0], "other", filtered["rna"], detected["spots"],
                    radius["spot_radius_nm"])
    assert seeds == [get_seed(7, "other", FISH_CHANNEL)]


def test_decompose_off_passes_the_spots_on(crop_config_path, filtered, detected, radius):
    config, channel = with_changes(crop_config_path, decomposition__enabled=False)
    found = steps.decompose(config, channel, CROP_NAME, filtered["rna"], detected["spots"],
                            radius["spot_radius_nm"])
    assert found["spots_post_decomposition"] is detected["spots"]
    assert found["reference_spot"] is None
    assert found["reference_spot_for_qc"] is False
    assert found["warning"] is None


def test_decompose_without_spots(config, channel, filtered, radius):
    no_spots = np.zeros((0, 3), dtype=np.int64)
    found = steps.decompose(config, channel, CROP_NAME, filtered["rna"], no_spots, radius["spot_radius_nm"])
    assert len(found["spots_post_decomposition"]) == 0
    assert found["warning"] == NO_SPOTS_WARNING
    assert found["reference_spot"] is None


def test_no_reference_spot_in_the_qc_without_a_spot_model(config, channel, filtered, detected, radius,
                                                          monkeypatch):
    monkeypatch.setattr(steps, "decompose_dense_regions", lambda *arguments, **keywords: {
        "spots_post_decomposition": arguments[1], "reference_spot": np.ones((5, 5, 5)), "skipped": True,
        "warning": NO_SPOT_MODEL_WARNING,
    })
    found = steps.decompose(config, channel, CROP_NAME, filtered["rna"], detected["spots"],
                            radius["spot_radius_nm"])
    assert found["reference_spot_for_qc"] is False
    assert found["reference_spot"] is not None
    assert found["warning"] == NO_SPOT_MODEL_WARNING


# ---------------------------------------------------------------------------
# Steps 6 to 8: subpixel fitting, clusters and measurements
# ---------------------------------------------------------------------------


def test_fit_subpixel_off(config, channel, filtered, decomposed, radius):
    found = steps.fit_subpixel(config, channel, filtered["rna"], decomposed["spots_post_decomposition"],
                               radius["spot_radius_nm"])
    assert found == {"spots_subpixel": None}


def test_fit_subpixel_on(crop_config_path, filtered, decomposed, radius):
    config, channel = with_changes(crop_config_path, subpixel__enabled=True)
    spots = decomposed["spots_post_decomposition"]
    found = steps.fit_subpixel(config, channel, filtered["rna"], spots, radius["spot_radius_nm"])
    expected = fit_subpixel(filtered["rna"], spots, VOXEL_SIZE, radius["spot_radius_nm"])
    np.testing.assert_array_equal(found["spots_subpixel"], expected)
    assert found["spots_subpixel"].shape == spots.shape


def test_clusters_off(crop_config_path, decomposed):
    config, channel = with_changes(crop_config_path, clusters__enabled=False)
    spots = decomposed["spots_post_decomposition"]
    found = steps.find_clusters(config, channel, spots)
    assert found["clusters"] is None and found["spots_post_clustering"] is None
    np.testing.assert_array_equal(found["cluster_id"], np.full(len(spots), -1))


def test_clusters_on_the_pixel_positions(config, channel, decomposed):
    spots = decomposed["spots_post_decomposition"]
    found = steps.find_clusters(config, channel, spots)
    expected_spots, expected_clusters = detect_clusters(spots, VOXEL_SIZE, radius=600, nb_min_spots=12)
    np.testing.assert_array_equal(found["spots_post_clustering"], expected_spots)
    np.testing.assert_array_equal(found["clusters"], expected_clusters)
    np.testing.assert_array_equal(found["cluster_id"], expected_spots[:, 3])
    assert len(found["clusters"]) > 0


def test_clusters_on_the_subpixel_positions(crop_config_path, filtered, decomposed, radius):
    config, channel = with_changes(crop_config_path, subpixel__enabled=True)
    spots = decomposed["spots_post_decomposition"]
    subpixel = steps.fit_subpixel(config, channel, filtered["rna"], spots, radius["spot_radius_nm"])
    found = steps.find_clusters(config, channel, spots, subpixel["spots_subpixel"])
    expected_spots, expected_clusters = detect_clusters(subpixel["spots_subpixel"], VOXEL_SIZE,
                                                        radius=600, nb_min_spots=12)
    np.testing.assert_array_equal(found["spots_post_clustering"], expected_spots)
    np.testing.assert_array_equal(found["clusters"], expected_clusters)


@pytest.mark.parametrize("snr, intensity", [(False, False), (True, False), (False, True), (True, True)])
def test_measure(crop_config_path, filtered, decomposed, radius, snr, intensity):
    config, channel = with_changes(crop_config_path, measurements__snr=snr, measurements__intensity=intensity)
    spots = decomposed["spots_post_decomposition"]
    found = steps.measure(config, channel, filtered["rna"], filtered["rna_log"], spots,
                          radius["spot_radius_px"])
    names = [name for name, on in (("snr", snr), ("log_intensity", intensity)) if on]
    assert sorted(found) == sorted(names)
    if names:
        expected = measure_spots(filtered["rna"], filtered["rna_log"], spots, radius["spot_radius_px"],
                                 snr=snr, intensity=intensity)
        for name in names:
            np.testing.assert_array_equal(found[name], expected[name])
            assert len(found[name]) == len(spots)


# ---------------------------------------------------------------------------
# Step 10: cell assignment
# ---------------------------------------------------------------------------


def test_no_cells_without_a_label_image(config, channel, decomposed):
    spots = decomposed["spots_post_decomposition"]
    clustered = steps.find_clusters(config, channel, spots)
    assert steps.assign_to_cells(config, channel, None, spots, clustered) == {
        "spot_cell_id": None, "cluster_cell_id": None, "cells": None,
    }


@pytest.mark.parametrize("drop", [False, True])
def test_assign_to_cells(crop_config_path, masks, decomposed, drop):
    config = kit_config(crop_config_path, segmentation={"drop_border_cells": drop})
    channel = config.channels[0]
    spots = decomposed["spots_post_decomposition"]
    clustered = steps.find_clusters(config, channel, spots)
    found = steps.assign_to_cells(config, channel, masks, spots, clustered)
    expected = assign_cells(masks, np.column_stack([spots, clustered["cluster_id"]]), 3, 65,
                            clusters=clustered["clusters"], drop_border_cells=drop)
    np.testing.assert_array_equal(found["spot_cell_id"], expected[0])
    np.testing.assert_array_equal(found["cluster_cell_id"], expected[1])
    assert found["cells"].equals(expected[2])
    if drop:
        assert len(found["cells"]) < 44
    else:
        assert len(found["cells"]) == 44


def test_no_cluster_cells_with_clusters_off(crop_config_path, masks, decomposed):
    config, channel = with_changes(crop_config_path, clusters__enabled=False)
    spots = decomposed["spots_post_decomposition"]
    clustered = steps.find_clusters(config, channel, spots)
    found = steps.assign_to_cells(config, channel, masks, spots, clustered)
    assert found["cluster_cell_id"] is None
    assert len(found["spot_cell_id"]) == len(spots)


# ---------------------------------------------------------------------------
# Tables and .npz arrays
# ---------------------------------------------------------------------------


def test_every_step_off_still_gives_tables(crop_config_path, image):
    config = kit_config(crop_config_path, {"decomposition__enabled": False, "clusters__enabled": False},
                        segmentation={"enabled": False})
    tables = run_steps(config, CROP_NAME, image, None)
    assert tables["cells"] is None
    assert tables["arrays"] is None
    assert len(tables["clusters"]) == 0
    assert (tables["spots"]["cluster_id"] == -1).all()
    assert list(tables["spots"].columns) == steps.run_spot_columns(config)


@pytest.mark.parametrize("changes, names", [
    ({}, ["clusters", "spots_post_clustering"]),
    ({"clusters__enabled": False}, ["spots"]),
])
def test_npz_arrays(crop_config_path, image, changes, names):
    config = kit_config(crop_config_path, changes, npz=True)
    tables = run_steps(config, CROP_NAME, image, None)
    assert sorted(tables["arrays"]) == names


def test_npz_spots_are_the_subpixel_positions_when_fitted(crop_config_path, filtered, decomposed, radius):
    config = kit_config(crop_config_path, {"clusters__enabled": False, "subpixel__enabled": True}, npz=True)
    channel = config.channels[0]
    spots = decomposed["spots_post_decomposition"]
    fitted = steps.fit_subpixel(config, channel, filtered["rna"], spots, radius["spot_radius_nm"])
    clustered = steps.find_clusters(config, channel, spots, fitted["spots_subpixel"])
    assigned = steps.assign_to_cells(config, channel, None, spots, clustered)
    tables = steps.make_tables(config, channel, CROP_NAME, spots, fitted, clustered, {}, assigned)
    assert tables["arrays"]["spots"] is fitted["spots_subpixel"]
    assert steps.final_positions(spots, fitted) is fitted["spots_subpixel"]
    assert steps.final_positions(spots, {"spots_subpixel": None}) is spots


# ---------------------------------------------------------------------------
# The steps one by one give the batch's tables
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("changes, segmentation, npz", [
    ({}, {}, False),
    ({"decomposition__enabled": False}, {}, False),
    ({"subpixel__enabled": True}, {}, False),
    ({"clusters__enabled": False}, {}, False),
    ({"subpixel__enabled": True, "clusters__enabled": False, "decomposition__enabled": False}, {}, True),
    ({"measurements__snr": True, "measurements__intensity": True}, {}, False),
    ({"threshold__mode": "auto", "threshold__value": None, "threshold__lower_limit": 10}, {}, False),
    ({}, {"drop_border_cells": True}, True),
    ({"subpixel__enabled": True}, {"enabled": False}, False),
], ids=["as-configured", "decomposition-off", "subpixel-on", "clusters-off", "hcr-subpixel-npz",
        "measurements-on", "auto-threshold", "drop-border-cells", "no-cells"])
def test_steps_one_by_one_give_the_batch_tables(crop_config_path, crop_path, image, masks, tmp_path,
                                                changes, segmentation, npz):
    config = kit_config(crop_config_path, changes, segmentation=segmentation, npz=npz)
    cells = config.segmentation.enabled
    tables = assert_as_batch(config, CROP_NAME, crop_path, image, masks if cells else None,
                             config.full_label_folder() if cells else None, tmp_path)
    assert len(tables["spots"]) > 0


def test_steps_one_by_one_give_the_batch_tables_with_a_calibrated_threshold(
        crop_config_path, crop_path, image, masks, tmp_path):
    config = kit_config(crop_config_path, {"threshold__mode": "calibrated", "threshold__value": None,
                                           "threshold__calibration_filter": "crop"}, resolved={2: 20})
    assert_as_batch(config, CROP_NAME, crop_path, image, masks, config.full_label_folder(), tmp_path)


def test_steps_one_by_one_give_the_batch_tables_in_2d(crop_config_path, crop_path, test_kit_folder, tmp_path):
    name = "crop_2d"
    projection = io.read_channel(crop_path, "ZCYX", FISH_CHANNEL).max(axis=0)
    path = tmp_path / f"{name}.tif"
    tifffile.imwrite(path, projection, imagej=True, metadata={"axes": "YX", "unit": "um"},
                     resolution=(1 / 0.065, 1 / 0.065))
    label_folder = tmp_path / "labels"
    label_folder.mkdir()
    shutil.copy(test_kit_folder / f"{CROP_NAME}_seglabels.tif", label_folder / f"{name}_seglabels.tif")

    data = kit_config(crop_config_path, {"subpixel__enabled": True, "measurements__snr": True}).to_dict()
    data["image"] = {"axes": "YX", "voxel_size_nm": {"yx": 65}}
    data["channels"][0]["index"] = 0
    data["channels"][0]["threshold"]["value"] = 40
    data["segmentation"]["label_folder"] = str(label_folder)
    config = parse_config(data)
    image = io.read_channel(path, "YX", 0)
    masks = read_label_file_contents(label_folder, name, image.shape)[0]
    tables = assert_as_batch(config, name, path, image, masks, label_folder, tmp_path)
    assert "z_px" not in tables["spots"].columns
    assert len(tables["spots"]) > 0
