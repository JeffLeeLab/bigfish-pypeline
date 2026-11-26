"""Tests for batch.save_image_results: one image run as a batch runs it, in the
calling program, and its results saved in a run folder of the usual layout.

The results are compared with those of `batch.run_batch` (and of the command
`bigfish-pypeline batch`) with the same settings restricted to that image.
Cellpose is replaced by the stand-in model of tests/cellpose_standin.py, except
in the tests marked `cellpose`, which use the real model (skipped when the model
file is missing). OMERO is replaced by stand-ins; no server is contacted.
"""

import logging
import os
import shutil
import signal
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psutil
import pytest
import tifffile
import yaml

from bigfish_pypeline import batch, cli, io, segmentation, steps
from bigfish_pypeline.config import load_config
from cellpose_standin import StandInModel
from conftest import CROP_NAME, TEST_DATA
from synthetic import make_image
from test_batch_cellpose import cpu_device, loader_for, run_cellpose, with_cellpose
from test_batch_run import KEY, FakeConn, generated_image, local_config, log_text, with_changes, write_image

CROP = TEST_DATA / f"{CROP_NAME}.tif"
CULTURE_NAME = "culture_DAPI_cellmask_exon_crop"
CULTURE = TEST_DATA / f"{CULTURE_NAME}.tif"
QC_OFF = {"elbow_plot": False, "detection": False, "reference_spot": False, "cellpose": False,
          "final": "none"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def kit_config(output, change=None):
    """The tissue crop's settings, with its output folder set and its label file in the test kit."""
    def set_output(data):
        data["run"]["output_folder"] = str(output)
        if change is not None:
            change(data)

    return with_changes(load_config(TEST_DATA / f"{CROP_NAME}_config.yaml"), set_output)


def batch_of_one(config, image):
    """The same settings restricted to one image, for run_batch."""
    image = Path(image)
    thresholds = dict(config.resolved.thresholds) if config.resolved is not None else {}
    config = with_changes(config, lambda data: data["run"]["input"].update(folder=str(image.parent)))
    return config.with_resolved([image.name], thresholds)


def files_of(run_folder):
    """Every file of a run folder, by its path inside the folder."""
    return sorted(str(path.relative_to(run_folder)) for path in Path(run_folder).rglob("*") if path.is_file())


def without_runtime(path):
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    return table.drop(columns="runtime_s")


def assert_same_results(first, second, same_output_folder=True):
    """Two run folders hold the same files, with the same tables byte for byte apart
    from the run times, the same `.npz` files, label images and settings (apart from
    the output folder when `same_output_folder` is false)."""
    first, second = Path(first), Path(second)
    names = files_of(first)
    assert names == files_of(second)
    for name in names:
        one, two = first / name, second / name
        if name.endswith("images.csv"):
            pd.testing.assert_frame_equal(without_runtime(one), without_runtime(two))
        elif name.endswith(".csv"):
            assert one.read_bytes() == two.read_bytes(), name
        elif name.endswith(".npz"):
            with np.load(one) as a, np.load(two) as b:
                assert sorted(a.files) == sorted(b.files), name
                for key in a.files:
                    np.testing.assert_array_equal(a[key], b[key], err_msg=f"{name}: {key}")
        elif name.endswith("_seglabels.tif"):
            np.testing.assert_array_equal(tifffile.imread(one), tifffile.imread(two), err_msg=name)
    settings = [load_config(folder / "run_config.yaml") for folder in (first, second)]
    if not same_output_folder:
        settings = [with_changes(config, lambda data: data["run"].update(output_folder=""))
                    for config in settings]
    assert settings[0] == settings[1]


def compare_with_batch(config, image, **arguments):
    """Save one image's results, run the same settings as a batch of that image,
    check that both give the same results, and return both outcomes."""
    saved = batch.save_image_results(config, image, **arguments)
    assert saved.status == "finished", saved.message
    result = batch.run_batch(batch_of_one(config, image))
    assert result.status == "finished", result.message
    assert saved.run_folder != result.run_folder
    assert_same_results(saved.run_folder, result.run_folder)
    return saved, result


def run_folders(root):
    root = Path(root)
    return sorted(path.name for path in root.iterdir()) if root.is_dir() else []


def image_rows(run_folder):
    return pd.read_csv(Path(run_folder) / "images.csv", keep_default_na=False, dtype=str)


# ---------------------------------------------------------------------------
# Tissue crop: equal to run_batch and to the command
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def kit_saved(tmp_path_factory):
    """The tissue crop saved with save_image_results, run with run_batch, and run
    with the command `bigfish-pypeline batch` (through cli.main), with the QC
    files of the settings file."""
    base = tmp_path_factory.mktemp("save_kit")
    config = kit_config(base / "out")
    saved = batch.save_image_results(config, CROP, command="notebook test")
    result = batch.run_batch(config)

    data = yaml.safe_load((TEST_DATA / f"{CROP_NAME}_config.yaml").read_text(encoding="utf-8"))
    data["run"]["input"]["folder"] = str(TEST_DATA)
    data["segmentation"]["label_folder"] = str(TEST_DATA)
    settings = base / "settings.yaml"
    settings.write_text(yaml.safe_dump(data), encoding="utf-8")
    before = set(run_folders(base / "command"))
    code = cli.main(["batch", str(settings), "--output-folder", str(base / "command")])
    [name] = set(run_folders(base / "command")) - before
    return saved, result, code, base / "command" / name


def test_kit_equals_a_batch_run(kit_saved):
    saved, result, _, _ = kit_saved
    assert saved.status == result.status == "finished"
    assert saved.message == "The run finished: 1 image(s) processed."
    assert_same_results(saved.run_folder, result.run_folder)
    assert len(pd.read_csv(saved.run_folder / "spots.csv")) == 692


def test_kit_equals_the_command(kit_saved):
    saved, _, code, command_folder = kit_saved
    assert code == cli.EXIT_OK
    assert_same_results(saved.run_folder, command_folder, same_output_folder=False)


def test_kit_run_folder(kit_saved):
    saved, _, _, _ = kit_saved
    folder = saved.run_folder
    assert folder.parent.name == "out"
    assert files_of(folder) == [
        "cells.csv", "clusters.csv", "images.csv",
        f"per_image/{CROP_NAME}_cells.csv", f"per_image/{CROP_NAME}_clusters.csv",
        f"per_image/{CROP_NAME}_images.csv", f"per_image/{CROP_NAME}_spots.csv",
        "progress.json",
        f"qc/{CROP_NAME}_ch2_detection.png", f"qc/{CROP_NAME}_ch2_elbow.png",
        f"qc/{CROP_NAME}_ch2_final.png", f"qc/{CROP_NAME}_ch2_referencespot.tif",
        "run.log", "run_config.yaml", "run_info.yaml", "spots.csv",
    ]
    rows = saved.images
    assert list(rows["image"]) == [CROP_NAME]
    assert list(rows["status"]) == ["done"]
    assert list(rows["n_spots"]) == [692]
    pd.testing.assert_frame_equal(rows, pd.read_csv(folder / "images.csv"))

    run_config = load_config(folder / "run_config.yaml")
    assert run_config.resolved.images == [f"{CROP_NAME}.tif"]
    assert run_config.run.input.folder == str(TEST_DATA)

    from bigfish_pypeline import outputs
    info = outputs.read_run_info(folder)
    assert info["status"] == "finished"
    assert info["command"] == "notebook test"
    assert info["workers"] == 1
    assert info["workers_reason"] == batch.IN_PROCESS_WORKERS_REASON
    assert info["files_read"][0]["kind"] == "label file"

    text = log_text(folder)
    for line in ("1 image(s):", f"{CROP_NAME}: started", f"{CROP_NAME}: finished",
                 f"{CROP_NAME}, channel 2: done, threshold 18, 692 spots, 6 clusters, 44 cells",
                 f"Workers: {batch.IN_PROCESS_WORKERS_REASON}.", "Summary: 1 of 1 image(s) finished",
                 "Config file: none (the settings were passed from Python)"):
        assert line in text, line
    assert text.index(f"{CROP_NAME}: started") < text.index(f"{CROP_NAME}, channel 2: done")


def test_kit_run_config_repeats_the_run(kit_saved):
    saved, _, _, _ = kit_saved
    repeat = batch.run_batch(load_config(saved.run_folder / "run_config.yaml"))
    assert repeat.status == "finished", repeat.message
    assert_same_results(saved.run_folder, repeat.run_folder)


def test_default_command_text(tmp_path):
    saved = batch.save_image_results(kit_config(tmp_path / "out", lambda data: data["outputs"].update(
        qc=dict(QC_OFF))), CROP)
    from bigfish_pypeline import outputs
    assert outputs.read_run_info(saved.run_folder)["command"] == batch.SAVED_FROM_PYTHON


def test_default_output_folder_is_in_the_image_folder(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    image = generated_image(folder / "one.tif")
    config = local_config("", "")
    saved = batch.save_image_results(config, image)
    assert saved.run_folder.parent == folder / "bigfish_results"
    assert load_config(saved.run_folder / "run_config.yaml").run.input.folder == str(folder)


# ---------------------------------------------------------------------------
# Settings: QC files, .npz, cells, channels, 2D, threshold modes
# ---------------------------------------------------------------------------


def test_qc_off_npz_on_cells_off(tmp_path):
    def change(data):
        data["outputs"].update(qc=dict(QC_OFF), npz=True)
        data["segmentation"]["enabled"] = False

    saved, _ = compare_with_batch(kit_config(tmp_path / "out", change), CROP)
    names = files_of(saved.run_folder)
    assert f"npz/{CROP_NAME}_ch2.npz" in names
    assert not any(name.startswith("qc/") for name in names)
    assert "cells.csv" not in names
    assert list(saved.images["segmentation_status"].isna()) == [True]


def test_html_final_qc_and_second_channel_with_auto_threshold(tmp_path):
    def change(data):
        data["outputs"]["qc"].update(final="html", reference_spot=False)
        second = {
            "index": 1, "name": "phal", "background": {"method": "tophat", "radius_px": 5},
            "threshold": {"mode": "auto", "lower_limit": 30},
            "decomposition": {"enabled": False}, "clusters": {"enabled": False},
        }
        data["channels"].append(second)

    saved, _ = compare_with_batch(kit_config(tmp_path / "out", change), CROP)
    assert list(saved.images["channel"]) == [2, 1]
    assert list(saved.images["threshold_mode"]) == ["manual", "auto"]
    assert f"qc/{CROP_NAME}_ch1_final.html" in files_of(saved.run_folder)


def test_two_dimensional_image(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    planes = [make_image((96, 80), n_spots=12, seed=channel)[0] for channel in range(2)]
    image = write_image(folder / "flat.tif", np.stack(planes), axes="CYX")
    labels = np.zeros((96, 80), dtype=np.uint16)
    labels[4:44, 4:36], labels[52:92, 44:76] = 1, 2
    tifffile.imwrite(folder / "flat_seglabels.tif", labels)

    def change(data):
        data["image"] = {"axes": "CYX", "voxel_size_nm": {"yx": 65}}
        data["segmentation"] = {"enabled": True, "source": "label_files", "label_folder": str(folder)}
        data["outputs"]["npz"] = True

    config = with_changes(local_config(folder, tmp_path / "out", qc=True), change)
    saved, _ = compare_with_batch(config, image)
    spots = pd.read_csv(saved.run_folder / "spots.csv")
    assert len(spots) > 0 and "z_px" not in spots.columns
    assert list(saved.images["status"]) == ["done", "done"]


def calibrated(data, value=None):
    data["channels"][0]["threshold"].update(mode="calibrated", calibration_filter="crop")
    if value is not None:
        data["resolved"] = {"images": [], "thresholds": {2: value}}


def test_calibrated_threshold_from_the_settings(tmp_path):
    config = kit_config(tmp_path / "out", lambda data: (calibrated(data, 18.0),
                                                        data["outputs"].update(qc=dict(QC_OFF))))
    saved, result = compare_with_batch(config, CROP)
    assert list(saved.images["threshold"]) == [18.0]
    assert list(saved.images["n_spots"]) == [692]
    run_config = load_config(saved.run_folder / "run_config.yaml")
    assert run_config.resolved.thresholds == {2: 18.0}
    assert "Channel 2: calibrated threshold 18, from the config (not calibrated again)" in log_text(saved.run_folder)
    assert not (saved.run_folder / "calibration.csv").exists()


def test_calibrated_threshold_missing(tmp_path):
    config = kit_config(tmp_path / "out", calibrated)
    with pytest.raises(batch.BatchError) as error:
        batch.save_image_results(config, CROP)
    assert str(error.value) == (
        "Channel 2 uses a calibrated threshold (`threshold.mode: calibrated`), but the settings hold "
        "no calibrated value for it yet (`resolved.thresholds`). Run the calibration first, or set "
        "`threshold.mode` to `manual` with the threshold value shown in the notebook."
    )
    assert run_folders(tmp_path / "out") == []


def test_two_calibrated_thresholds_missing(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    image = generated_image(folder / "one.tif")
    threshold = {"mode": "calibrated", "calibration_filter": "one"}
    config = local_config(folder, tmp_path / "out", channels=[{"index": 0, "threshold": threshold},
                                                              {"index": 1, "threshold": threshold}])
    with pytest.raises(batch.BatchError, match=r"^Channels 0, 1 use a calibrated threshold .* value for them yet"):
        batch.save_image_results(config, image)


# ---------------------------------------------------------------------------
# Cellpose with the stand-in model
# ---------------------------------------------------------------------------


@pytest.fixture
def cellpose_image(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    image = generated_image(folder / "cells.tif", shape=(8, 64, 64), n_channels=2)
    config = with_cellpose(local_config(folder, tmp_path / "out", qc=True), channel=1)
    return config, image


def notebook_segmentation(config, image, model):
    """What the notebook does: read the segmentation channel, pre-treat it as the
    settings say, and segment it."""
    channel = io.read_channel(image, config.image.axes, config.segmentation.channel)
    prepared = segmentation.pretreat_channel(channel, **batch._pretreatment_settings(config))
    return segmentation.segment_cells(model, prepared,
                                      **segmentation.cellpose_eval_settings(config.segmentation.cellpose))


def test_cellpose_masks_passed_in_are_used(cellpose_image, tmp_path):
    config, image = cellpose_image
    found = notebook_segmentation(config, image, StandInModel(n_cells=2))
    model = StandInModel(n_cells=5)
    saved = batch.save_image_results(config, image, cellpose_result=found, cellpose_model=model)
    assert saved.status == "finished", saved.message
    assert model.calls == []
    run_folder = saved.run_folder
    labels = tifffile.imread(run_folder / "labels" / "cells_seglabels.tif")
    np.testing.assert_array_equal(labels, found["masks"])
    assert "qc/cells_cellpose_qc.png" in files_of(run_folder)
    assert list(saved.images["n_cells"]) == [2, 2]
    assert list(saved.images["segmentation_source"]) == ["cellpose", "cellpose"]
    assert list(saved.images["segmentation_status"]) == ["done", "done"]
    text = log_text(run_folder)
    assert "cells: 2 cell(s) found with Cellpose before saving, used as they are (Cellpose was not run again)" in text
    assert ("Cellpose: the cells found before saving on the CPU are used as they are; "
            "Cellpose is not run again.") in text
    assert "Cellpose ready in" not in text

    # the same results as a batch run whose model finds the same cells
    result = run_cellpose(batch_of_one(config, image), StandInModel(n_cells=2))
    assert_same_results(run_folder, result.run_folder)


def test_cellpose_masks_passed_in_without_a_model(cellpose_image):
    config, image = cellpose_image
    found = notebook_segmentation(config, image, StandInModel(n_cells=3))
    saved = batch.save_image_results(config, image, cellpose_result=found)
    assert list(saved.images["n_cells"]) == [3, 3]
    from bigfish_pypeline import outputs
    assert outputs.read_run_info(saved.run_folder)["cellpose_device"] == batch.CELLPOSE_DEVICE_NOT_KNOWN


def test_cellpose_run_here_with_the_model_passed_in(cellpose_image, monkeypatch):
    config, image = cellpose_image
    config = with_changes(config, lambda data: data["segmentation"].update(
        z_planes={"first": 2, "last": 5}, background={"enabled": False}, median_px=3))
    monkeypatch.setattr(segmentation, "load_cellpose_model", lambda *a, **k: pytest.fail("model loaded again"))
    model = StandInModel(n_cells=4)
    saved = batch.save_image_results(config, image, cellpose_model=model)
    assert len(model.calls) == 1
    expected = notebook_segmentation(config, image, StandInModel(n_cells=4))["model_input"]
    np.testing.assert_array_equal(model.calls[0]["x"], expected)
    assert list(saved.images["n_cells"]) == [4, 4]
    text = log_text(saved.run_folder)
    assert "Cellpose runs on the CPU, with the model loaded before saving." in text
    assert "segmented with Cellpose in" in text
    assert "max projection of planes 2–5" in text

    result = run_cellpose(batch_of_one(config, image), StandInModel(n_cells=4))
    assert_same_results(saved.run_folder, result.run_folder)


def test_cellpose_loaded_here_when_nothing_is_passed(cellpose_image, monkeypatch):
    config, image = cellpose_image
    model = StandInModel(n_cells=2)
    loads = []
    monkeypatch.setattr(segmentation, "choose_device", cpu_device)
    monkeypatch.setattr(segmentation, "load_cellpose_model", loader_for(model, loads))
    shown = []
    saved = batch.save_image_results(config, image, show=shown.append)
    assert len(loads) == 1 and len(model.calls) == 1
    assert shown[0] == "Getting Cellpose ready: testing the device and loading the model..."
    assert "Cellpose ready in" in log_text(saved.run_folder)
    assert list(saved.images["n_cells"]) == [2, 2]


def test_cellpose_without_label_images(cellpose_image):
    config, image = cellpose_image
    config = with_changes(config, lambda data: data["outputs"].update(label_images=False))
    found = notebook_segmentation(config, image, StandInModel(n_cells=2))
    saved = batch.save_image_results(config, image, cellpose_result=found)
    names = files_of(saved.run_folder)
    assert not any(name.startswith(("labels", "labels_temporary")) for name in names)
    assert list(saved.images["n_cells"]) == [2, 2]
    result = run_cellpose(batch_of_one(config, image), StandInModel(n_cells=2))
    assert_same_results(saved.run_folder, result.run_folder)


def test_cellpose_masks_of_another_size(cellpose_image, tmp_path):
    config, image = cellpose_image
    found = notebook_segmentation(config, image, StandInModel(n_cells=2))
    found["masks"] = found["masks"][:40]
    with pytest.raises(batch.BatchError) as error:
        batch.save_image_results(config, image, cellpose_result=found)
    assert str(error.value) == (
        "Cellpose masks passed in: labels are 40 x 64 px, but the image is 64 x 64 px. "
        "Pass the masks Cellpose made for this image."
    )
    assert run_folders(tmp_path / "out") == []


def test_cellpose_result_without_masks_or_qc_material(cellpose_image, tmp_path):
    config, image = cellpose_image
    found = notebook_segmentation(config, image, StandInModel(n_cells=2))
    with pytest.raises(batch.BatchError, match="holds no masks"):
        batch.save_image_results(config, image, cellpose_result={"n_cells": 2})
    with pytest.raises(batch.BatchError, match="lacks what the Cellpose QC figure is drawn from"):
        batch.save_image_results(config, image, cellpose_result={"masks": found["masks"]})
    # without the QC figure, the masks alone are enough
    config = with_changes(config, lambda data: data["outputs"]["qc"].update(cellpose=False))
    saved = batch.save_image_results(config, image, cellpose_result={"masks": found["masks"]})
    assert list(saved.images["n_cells"]) == [2, 2]


def test_cellpose_result_with_label_files_is_refused(tmp_path):
    found = {"masks": np.zeros((10, 10), dtype=np.uint32)}
    with pytest.raises(batch.BatchError, match="these settings do not use Cellpose"):
        batch.save_image_results(kit_config(tmp_path / "out"), CROP, cellpose_result=found)
    assert run_folders(tmp_path / "out") == []


# ---------------------------------------------------------------------------
# Cultured-cell crop with the real Cellpose model
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def culture_config(tmp_path_factory):
    base = tmp_path_factory.mktemp("save_culture")

    def change(data):
        data["run"]["output_folder"] = str(base / "out")
        data["outputs"]["qc"].update(elbow_plot=False, detection=False, reference_spot=False, final="none")

    return with_changes(load_config(TEST_DATA / f"{CULTURE_NAME}_config.yaml"), change)


@pytest.fixture(scope="module")
def culture_batch(culture_config):
    result = batch.run_batch(culture_config)
    assert result.status == "finished", result.message
    return result


@pytest.mark.cellpose
def test_culture_equals_a_batch_run(culture_config, culture_batch):
    saved = batch.save_image_results(culture_config, CULTURE)
    assert saved.status == "finished", saved.message
    assert_same_results(saved.run_folder, culture_batch.run_folder)
    assert int(saved.images["n_cells"].iloc[0]) > 0


@pytest.mark.cellpose
def test_culture_with_the_segmentation_made_first(culture_config, culture_batch):
    device, _, _ = segmentation.choose_device(culture_config.segmentation.device)
    threads = torch_threads()
    model = segmentation.load_cellpose_model(culture_config.segmentation.cellpose.model, device,
                                             threads=batch.cellpose_threads(os.cpu_count()))
    try:
        found = notebook_segmentation(culture_config, CULTURE, model)
        calls = []
        original = model.eval
        model.eval = lambda *a, **k: calls.append(1) or original(*a, **k)
        saved = batch.save_image_results(culture_config, CULTURE, cellpose_result=found, cellpose_model=model)
    finally:
        if threads is not None:
            import torch
            torch.set_num_threads(threads)
    assert calls == []
    assert saved.status == "finished", saved.message
    labels = tifffile.imread(saved.run_folder / "labels" / f"{CULTURE_NAME}_seglabels.tif")
    np.testing.assert_array_equal(labels, found["masks"])
    batch_labels = tifffile.imread(culture_batch.run_folder / "labels" / f"{CULTURE_NAME}_seglabels.tif")
    np.testing.assert_array_equal(labels, batch_labels)
    assert_same_results(saved.run_folder, culture_batch.run_folder)


# ---------------------------------------------------------------------------
# Problems found before the run
# ---------------------------------------------------------------------------


def test_image_that_cannot_be_used(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    image = generated_image(folder / "one_channel.tif", n_channels=1)
    with pytest.raises(batch.BatchError) as error:
        batch.save_image_results(local_config(folder, tmp_path / "out"), image)
    assert str(error.value).startswith("The image cannot be used with these settings: one_channel.tif")
    assert run_folders(tmp_path / "out") == []


def test_image_that_does_not_exist(tmp_path):
    missing = tmp_path / "input" / "missing.tif"
    with pytest.raises(batch.BatchError) as error:
        batch.save_image_results(local_config("", tmp_path / "out"), missing)
    assert str(error.value) == f"The image {missing} does not exist."
    assert run_folders(tmp_path / "out") == []


def test_image_given_as_something_else(tmp_path):
    with pytest.raises(batch.BatchError, match="the path of its file, or as an OMERO image ID"):
        batch.save_image_results(local_config("", tmp_path / "out"), 1.5)


def test_label_folder_that_does_not_exist(tmp_path):
    config = kit_config(tmp_path / "out", lambda data: data["segmentation"].update(
        label_folder=str(tmp_path / "no_labels")))
    with pytest.raises(batch.BatchError, match="The label folder .* does not exist"):
        batch.save_image_results(config, CROP)
    assert run_folders(tmp_path / "out") == []


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX permissions")
def test_output_folder_that_cannot_be_written(tmp_path):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("the root user can write to any folder")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(batch.BatchError, match="cannot be written to"):
            batch.save_image_results(kit_config(locked / "results"), CROP)
    finally:
        locked.chmod(0o700)
    assert list(locked.iterdir()) == []


# ---------------------------------------------------------------------------
# Failures during the run are recorded, not raised
# ---------------------------------------------------------------------------


def test_failing_channel_is_recorded(tmp_path, monkeypatch):
    folder = tmp_path / "input"
    folder.mkdir()
    image = generated_image(folder / "two.tif")
    original = steps.find_clusters

    def find_clusters(config, channel, *args, **kwargs):
        if channel.index == 1:
            raise RuntimeError("clusters went wrong")
        return original(config, channel, *args, **kwargs)

    monkeypatch.setattr(steps, "find_clusters", find_clusters)
    saved = batch.save_image_results(local_config(folder, tmp_path / "out"), image)
    assert saved.status == "finished"
    assert saved.message.startswith("The run finished: 1 image(s) processed; 1 channel(s) failed.")
    rows = image_rows(saved.run_folder)
    assert list(rows["status"]) == ["done", "failed"]
    assert list(rows["reason"]) == ["", "RuntimeError: clusters went wrong"]
    text = log_text(saved.run_folder)
    assert "two, channel 1: failed: RuntimeError: clusters went wrong" in text
    assert "Traceback" in text


def test_image_that_cannot_be_read_is_recorded(tmp_path, monkeypatch):
    folder = tmp_path / "input"
    folder.mkdir()
    image = generated_image(folder / "two.tif")

    def read_channel(*args, **kwargs):
        raise io.ImageReadError("two.tif: the file is damaged")

    monkeypatch.setattr(io, "read_channel", read_channel)
    saved = batch.save_image_results(local_config(folder, tmp_path / "out"), image)
    assert saved.status == "finished"
    assert list(saved.images["status"]) == ["failed", "failed"]
    assert "two: failed: two.tif: the file is damaged" in log_text(saved.run_folder)


# ---------------------------------------------------------------------------
# The calling program is left as it was
# ---------------------------------------------------------------------------


def torch_threads():
    torch = sys.modules.get("torch")
    return None if torch is None else torch.get_num_threads()


def program_state():
    root = logging.getLogger()
    return {
        "variables": {name: os.environ.get(name) for name in batch.THREAD_VARIABLES},
        "torch_threads": torch_threads(),
        "backend": matplotlib.get_backend(),
        "rc": dict(matplotlib.rcParams),
        "figures": plt.get_fignums(),
        "sigint": signal.getsignal(signal.SIGINT),
        "children": sorted(child.pid for child in psutil.Process().children(recursive=True)),
        "log_handlers": list(root.handlers),
        "log_level": root.level,
        "omero": dict(batch._omero),
    }


def test_program_left_as_it_was(cellpose_image, monkeypatch):
    import torch

    config, image = cellpose_image
    config = with_changes(config, lambda data: data["run"].update(keep_awake=True))
    monkeypatch.setenv("OMP_NUM_THREADS", "3")
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)
    threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        check_program_left_as_it_was(config, image, monkeypatch, torch)
    finally:
        torch.set_num_threads(threads)


def check_program_left_as_it_was(config, image, monkeypatch, torch):
    seen = []
    original = steps.spot_radius

    def spot_radius(*args, **kwargs):
        seen.append(({name: os.environ.get(name) for name in batch.THREAD_VARIABLES},
                     signal.getsignal(signal.SIGINT)))
        return original(*args, **kwargs)

    def load(model_name, device, threads=None):
        torch.set_num_threads(threads)
        return StandInModel(n_cells=2)

    monkeypatch.setattr(steps, "spot_radius", spot_radius)
    monkeypatch.setattr(segmentation, "choose_device", cpu_device)
    monkeypatch.setattr(segmentation, "load_cellpose_model", load)
    before = program_state()
    saved = batch.save_image_results(config, image)
    assert saved.status == "finished", saved.message
    assert program_state() == before
    # the image was processed with the program's own thread settings and Ctrl+C handling
    assert seen == [(before["variables"], before["sigint"])] * 2
    assert "Keep awake: " in log_text(saved.run_folder)


def test_program_left_as_it_was_after_a_problem(tmp_path):
    before = program_state()
    with pytest.raises(batch.BatchError):
        batch.save_image_results(kit_config(tmp_path / "out", calibrated), CROP)
    assert program_state() == before


# ---------------------------------------------------------------------------
# OMERO, with stand-ins for the server
# ---------------------------------------------------------------------------


@pytest.fixture
def omero_stand_ins(monkeypatch):
    """Stand-ins for reading OMERO images: a 2 × 2 × 16 × 16 image with one bright spot."""
    def get_omero_image_info(conn, image_id):
        return io.OmeroImageInfo(
            image_id=image_id, name="x", size_z=2, size_c=2, size_t=1, size_y=16, size_x=16,
            pixel_type="uint16", dtype=np.dtype("uint16"), voxel_size_z=200.0,
            voxel_size_y=65.0, voxel_size_x=65.0, channel_names=["a", "b"],
        )

    def read_omero_channels(conn, image_id, layout, channels):
        reads.append(conn)
        arrays = {}
        for channel in channels:
            array = np.full((2, 16, 16), 100, dtype=np.uint16)
            array[1, 8, 8] = 2000
            arrays[channel] = array
        return arrays

    def join_session(*args):
        pytest.fail("a second connection was made")

    reads = []
    monkeypatch.setattr(io, "get_omero_image_info", get_omero_image_info)
    monkeypatch.setattr(io, "read_omero_channels", read_omero_channels)
    monkeypatch.setattr(io, "join_session", join_session)
    return reads


def omero_settings(output):
    def change(data):
        data["run"]["input"].update(source="omero", folder="")
        data["run"]["input"]["omero"].update(host="omero.example", dataset_id=5)

    return with_changes(local_config("", output), change)


def test_omero_image(tmp_path, omero_stand_ins):
    conn = FakeConn([(123, "a.tif"), (124, "b.tif")])
    before = dict(batch._omero)
    saved = batch.save_image_results(omero_settings(tmp_path / "out"), 123, omero_conn=conn)
    assert saved.status == "finished", saved.message
    assert list(saved.images["image"]) == ["123_a", "123_a"]
    assert list(saved.images["status"]) == ["done", "done"]
    assert omero_stand_ins and all(read is conn for read in omero_stand_ins)
    assert not conn.closed
    assert batch._omero == before

    run_config = load_config(saved.run_folder / "run_config.yaml")
    assert run_config.resolved.images == ["123_a"]
    assert run_config.run.input.omero.image_ids == [123]
    assert run_config.run.input.omero.dataset_id is None
    for path in saved.run_folder.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes(), path.name
    from bigfish_pypeline import outputs
    assert outputs.read_run_info(saved.run_folder)["omero_server"] == "omero.example, port 4064"


def test_omero_image_needs_a_connection(tmp_path, omero_stand_ins):
    with pytest.raises(batch.BatchError, match="needs the OMERO connection that is already logged in"):
        batch.save_image_results(omero_settings(tmp_path / "out"), 123)
    assert run_folders(tmp_path / "out") == []


def test_omero_image_not_on_the_server(tmp_path, omero_stand_ins):
    with pytest.raises(batch.BatchError):
        batch.save_image_results(omero_settings(tmp_path / "out"), 999, omero_conn=FakeConn([(123, "a.tif")]))
    assert run_folders(tmp_path / "out") == []


def test_stopping_the_cell_raises_keyboard_interrupt(tmp_path, monkeypatch):
    """Ctrl+C, or stopping a notebook cell, stops the run at once and is passed on."""
    folder = tmp_path / "input"
    folder.mkdir()
    image = generated_image(folder / "two.tif")

    def spot_radius(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(steps, "spot_radius", spot_radius)
    before = program_state()
    with pytest.raises(KeyboardInterrupt):
        batch.save_image_results(local_config(folder, tmp_path / "out"), image)
    assert program_state() == before
    [name] = run_folders(tmp_path / "out")
    from bigfish_pypeline import outputs
    assert outputs.read_run_info(tmp_path / "out" / name)["status"] == "stopped"
