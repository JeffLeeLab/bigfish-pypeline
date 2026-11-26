"""Tests for batch.run_batch: whole batch runs in a pool of worker processes."""

import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import textwrap
import traceback
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import tifffile

from batch_helpers import fake_process_image, omero_process_image
from bigfish_pypeline import __version__, batch, io, outputs
from bigfish_pypeline.config import load_config, parse_config
from conftest import CROP_NAME
from synthetic import make_image

KEY = "1b2c3d4e-0000-1111-2222-333344445555"
QC_OFF = {"elbow_plot": False, "detection": False, "reference_spot": False, "cellpose": False,
          "final": "none"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_image(path, array, axes="ZCYX"):
    """Write an ImageJ TIFF with voxel sizes of 200 nm (Z) and 65 nm (Y, X)."""
    metadata = {"axes": axes, "unit": "um"}
    if "Z" in axes:
        metadata["spacing"] = 0.2
    tifffile.imwrite(path, array, imagej=True, metadata=metadata, resolution=(1 / 0.065, 1 / 0.065))
    return path


def generated_image(path, shape=(8, 64, 64), n_channels=2, seed=0, blank=False, amplitude=1000):
    channels = [
        make_image(shape, n_spots=8, seed=seed + channel, blank=blank, amplitude=amplitude)[0]
        for channel in range(n_channels)
    ]
    return write_image(path, np.stack(channels, axis=1))


def tiny_images(folder, names):
    """Small two-channel images, for runs with the stand-in image function."""
    folder.mkdir(parents=True, exist_ok=True)
    array = np.ones((2, 2, 16, 16), dtype=np.uint16)
    for name in names:
        write_image(folder / f"{name}.tif", array)
    return folder


def local_config(input_folder, output_folder, workers=1, channels=None, qc=False, **run_settings):
    """Config for generated images: top-hat background, manual threshold 50.

    No QC images are drawn, unless `qc` is true (the defaults of `outputs.qc`).
    """
    if channels is None:
        channels = [{"index": 0}, {"index": 1}]
    full_channels = []
    for channel in channels:
        full = {"background": {"method": "tophat", "radius_px": 5},
                "threshold": {"mode": "manual", "value": 50}}
        full.update(channel)
        full_channels.append(full)
    data = {
        "config_version": 1,
        "run": {"name": "test", "input": {"source": "local", "folder": str(input_folder)},
                "output_folder": str(output_folder), "workers": workers, "keep_awake": False},
        "image": {"axes": "ZCYX", "voxel_size_nm": {"z": 200, "yx": 65}},
        "channels": full_channels,
    }
    if not qc:
        data["outputs"] = {"qc": dict(QC_OFF)}
    data["run"].update(run_settings)
    return parse_config(data)


def with_changes(config, change):
    """Copy of a config after `change(data)` has edited its settings."""
    data = config.to_dict()
    change(data)
    return parse_config(data, config.config_folder)


def read_table(run_folder, kind):
    return pd.read_csv(run_folder / f"{kind}.csv")


def without_runtime(table):
    return table.drop(columns=["runtime_s"]).reset_index(drop=True)


def same_tables(first, second):
    for kind in ("images", "spots", "clusters", "cells"):
        if not (first / f"{kind}.csv").is_file():
            assert not (second / f"{kind}.csv").is_file()
            continue
        a, b = read_table(first, kind), read_table(second, kind)
        if kind == "images":
            a, b = without_runtime(a), without_runtime(b)
        pd.testing.assert_frame_equal(a, b)


def log_text(run_folder):
    return (run_folder / batch.LOG_NAME).read_text(encoding="utf-8")


def progress(run_folder):
    return json.loads((run_folder / batch.PROGRESS_NAME).read_text(encoding="utf-8"))


def run_fake(config, **arguments):
    return batch.run_batch(config, image_function=fake_process_image, **arguments)


def per_image_files(run_folder):
    return sorted(path.name for path in (run_folder / "per_image").iterdir())


RUN_INFO_KEYS = [
    "status", "message", "started", "ended", "duration", "command", "started_in_folder",
    "settings_file", "pipeline_version", "git_commit", "python_version", "package_versions",
    "operating_system", "processor_cores", "computer_memory", "cellpose_device", "workers",
    "workers_reason", "worker_restarts", "random_seed", "calibrated_thresholds", "omero_server",
    "files_read",
]
PACKAGES = ["big-fish", "cellpose", "torch", "numpy", "scipy", "scikit-image", "scikit-learn", "pandas",
            "tifffile", "pydantic", "plotly", "omero-py"]
FILE_RECORD_KEYS = ["kind", "path", "size_bytes", "last_changed", "sha256"]


def run_info(run_folder, status):
    """The run record of a run that has ended, after checking each item and the kind of its value."""
    assert not (run_folder / "run_info.yaml.tmp").exists()
    info = outputs.read_run_info(run_folder)
    assert list(info) == RUN_INFO_KEYS
    assert info["status"] == status
    assert isinstance(info["message"], str) and info["message"]
    started = datetime.fromisoformat(info["started"])
    ended = datetime.fromisoformat(info["ended"])
    assert started.tzinfo is not None and started <= ended
    assert re.fullmatch(r"\d+ s|\d+ min \d+ s|\d+ h \d+ min", info["duration"]), info["duration"]
    for key in ("command", "started_in_folder", "settings_file", "git_commit", "operating_system",
                "workers_reason", "omero_server"):
        assert isinstance(info[key], str) and info[key], key
    assert info["pipeline_version"] == __version__
    assert info["git_commit"] == "not available" or re.match(r"[0-9a-f]{40}", info["git_commit"])
    assert info["python_version"] == platform.python_version()
    assert list(info["package_versions"]) == PACKAGES
    assert all(isinstance(value, str) and value for value in info["package_versions"].values())
    assert info["package_versions"]["numpy"] == np.__version__
    assert info["processor_cores"] == os.cpu_count()
    assert re.fullmatch(r"\d+\.\d GB", info["computer_memory"])
    assert info["cellpose_device"] in ("not used", "cpu", "mps", "cuda")
    assert isinstance(info["workers"], int) and info["workers"] >= 1
    # the reason is the logged line; a lowered number is given at its end
    assert re.match(r"\d+ worker\(s\)", info["workers_reason"])
    restarts = info["worker_restarts"]
    assert restarts == "none" or (isinstance(restarts, list) and restarts)
    for restart in [] if restarts == "none" else restarts:
        assert list(restart) == ["time", "workers", "images_lost"]
        datetime.fromisoformat(restart["time"])
        assert isinstance(restart["workers"], int) and restart["workers"] >= 1
        # a worker that stopped while no image was in it lost none
        assert isinstance(restart["images_lost"], list)
        assert all(isinstance(name, str) for name in restart["images_lost"])
    assert isinstance(info["random_seed"], int)
    thresholds = info["calibrated_thresholds"]
    assert thresholds == "none" or all(
        re.fullmatch(r"channel \d+", name) and isinstance(value, float) for name, value in thresholds.items()
    )
    files = info["files_read"]
    assert files == "none" or (isinstance(files, list) and files)
    for record in [] if files == "none" else files:
        assert list(record) == FILE_RECORD_KEYS
        assert record["kind"] in ("label file", "Cellpose model")
        assert Path(record["path"]).is_absolute()
        assert isinstance(record["size_bytes"], int) and record["size_bytes"] > 0
        assert datetime.fromisoformat(record["last_changed"]).tzinfo is not None
        assert re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
    # the duration is the total time of the summary line of run.log
    if info["duration"] != "not ended" and (run_folder / "run.log").is_file():
        summaries = re.findall(r"Total time ([^.]+)\.", (run_folder / "run.log").read_text(encoding="utf-8"))
        assert summaries[-1:] == [info["duration"]] or not summaries
    return info


# ---------------------------------------------------------------------------
# Test kit, one and two workers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def kit_runs(crop_config_path, test_kit_folder, tmp_path_factory):
    """The test kit crop and one generated image, run with one and with two workers."""
    folder = tmp_path_factory.mktemp("kit_input")
    shutil.copy(test_kit_folder / f"{CROP_NAME}.tif", folder)
    shutil.copy(test_kit_folder / f"{CROP_NAME}_seglabels.tif", folder)
    generated_image(folder / "zz_generated.tif", n_channels=3)
    config = load_config(crop_config_path)
    output = tmp_path_factory.mktemp("kit_output")

    def change(data):
        data["run"]["input"]["folder"] = str(folder)
        data["run"]["input"]["filter"] = ""
        data["run"]["output_folder"] = str(output)
        data["segmentation"]["label_folder"] = str(folder)
        data["outputs"]["qc"].update(QC_OFF)

    config = with_changes(config, change)
    results = {}
    for workers in (1, 2):
        results[workers] = batch.run_batch(with_changes(config, lambda data: data["run"].update(workers=workers)))
    return results


def test_kit_one_and_two_workers(kit_runs, crop_reference_folder):
    one, two = kit_runs[1], kit_runs[2]
    for result in (one, two):
        assert result.status == "finished", result.message
        folder = result.run_folder
        for name in ("run_config.yaml", "run.log", "progress.json", "images.csv", "spots.csv",
                     "clusters.csv", "cells.csv", "per_image"):
            assert (folder / name).exists(), name
        assert progress(folder)["status"] == "finished"
        assert progress(folder)["n_finished"] == 2
        assert not list((folder / "per_image").glob("*.tmp"))
    assert "Workers: 2 worker(s), as set in the config" in log_text(two.run_folder)
    same_tables(one.run_folder, two.run_folder)

    reference = np.load(next((crop_reference_folder / "general_manual18_subpixel-off").glob("*_bfoutput.npz")))
    spots = read_table(one.run_folder, "spots")
    spots = spots[spots["image"] == CROP_NAME]
    assert len(spots) == 692
    np.testing.assert_array_equal(
        spots[["z_px", "y_px", "x_px", "cluster_id"]].to_numpy(), reference["spots_post_clustering"]
    )
    clusters = read_table(one.run_folder, "clusters")
    assert (clusters["image"] == CROP_NAME).sum() == 6
    cells = read_table(one.run_folder, "cells")
    assert (cells["image"] == CROP_NAME).sum() == 44
    images = read_table(one.run_folder, "images")
    assert list(images["image"]) == [CROP_NAME, "zz_generated"]
    assert list(images["status"]) == ["done", "done"]
    assert list(images["segmentation_status"]) == ["done", "no_labels"]

    run_config = load_config(one.run_folder / "run_config.yaml")
    assert run_config.resolved.images == [f"{CROP_NAME}.tif", "zz_generated.tif"]


def test_kit_run_info(kit_runs):
    for workers, result in kit_runs.items():
        info = run_info(result.run_folder, "finished")
        assert info["message"] == result.message
        assert info["command"] == batch.COMMAND_FROM_PYTHON
        assert info["settings_file"] == "not given"
        assert info["started_in_folder"] == os.getcwd()
        assert info["cellpose_device"] == "not used"
        assert info["workers"] == workers
        assert info["workers_reason"] == f"{workers} worker(s), as set in the config"
        assert info["worker_restarts"] == "none"
        assert info["random_seed"] == 0
        assert info["calibrated_thresholds"] == "none"
        assert info["omero_server"] == "not used"
        # the test kit's label file, read for the crop; the generated image has none
        [record] = info["files_read"]
        assert record == outputs.file_record(Path(record["path"]), "label file")
        assert Path(record["path"]).name == f"{CROP_NAME}_seglabels.tif"


def test_kit_log(kit_runs):
    text = log_text(kit_runs[1].run_folder)
    for expected in (
        "Input folder:",
        f"  {CROP_NAME}.tif",
        f"{CROP_NAME}: started",
        f"{CROP_NAME}, channel 2: done, threshold 18, 692 spots, 6 clusters, 44 cells",
        "FISH channel 2 (jim-exon): manual threshold 18; spot radius 1.12 px in Z, 0.99 px in Y and X",
        f"{CROP_NAME}: finished",
        "zz_generated: warning: no cell results",
        "Summary: 2 of 2 image(s) finished, 0 not processed; channels: 2 done, 0 failed, 0 skipped.",
        "The run finished: 2 image(s) processed.",
    ):
        assert expected in text, expected


def test_repeat_from_run_config(kit_runs):
    first = kit_runs[1].run_folder
    config = load_config(first / "run_config.yaml")
    result = batch.run_batch(config)
    assert result.status == "finished"
    assert result.run_folder != first
    same_tables(first, result.run_folder)


# ---------------------------------------------------------------------------
# Generated images, one of them corrupt
# ---------------------------------------------------------------------------


def test_corrupt_image_and_list_order(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    generated_image(folder / "a_large.tif", shape=(12, 256, 256), seed=1)
    for seed, name in enumerate(("b", "c_corrupt", "d", "e"), start=2):
        generated_image(folder / f"{name}.tif", seed=seed)
    corrupt = folder / "c_corrupt.tif"
    corrupt.write_bytes(corrupt.read_bytes()[:3000])

    result = batch.run_batch(local_config(folder, tmp_path / "out", workers=2))
    assert result.status == "finished"
    images = read_table(result.run_folder, "images")
    assert list(images["image"]) == ["a_large", "a_large", "b", "b", "c_corrupt", "c_corrupt",
                                     "d", "d", "e", "e"]
    assert list(images.loc[images["image"] == "c_corrupt", "status"]) == ["failed", "failed"]
    assert (images.loc[images["image"] != "c_corrupt", "status"] == "done").all()
    spots = read_table(result.run_folder, "spots")
    assert list(dict.fromkeys(spots["image"])) == ["a_large", "b", "d", "e"]
    text = log_text(result.run_folder)
    assert "c_corrupt: failed: c_corrupt.tif: the file is damaged or incomplete" in text
    assert "channels: 8 done, 2 failed, 0 skipped" in text
    message = ("The run finished: 5 image(s) processed; 2 channel(s) failed. "
               "See images.csv and run.log in the run folder.")
    assert result.message == message
    assert run_info(result.run_folder, "finished")["message"] == message


def test_file_stored_in_another_axis_order(tmp_path):
    """A file stored CZYX in a ZCYX run fails with both orders named; the others are processed."""
    folder = tmp_path / "input"
    folder.mkdir()
    # every channel and Z plane holds its own spots, so that the planes can be told apart
    channels = [make_image((8, 64, 64), n_spots=8, seed=seed)[0] for seed in (3, 4)]
    write_image(folder / "a_zcyx.tif", np.stack(channels, axis=1))
    tifffile.imwrite(folder / "b_czyx.tif", np.stack(channels), metadata={"axes": "CZYX"}, photometric="minisblack")
    write_image(folder / "c_zcyx.tif", np.stack(channels, axis=1))

    result = batch.run_batch(local_config(folder, tmp_path / "out"))
    assert result.status == "finished", result.message
    images = read_table(result.run_folder, "images")
    assert list(images["status"]) == ["done", "done", "failed", "failed", "done", "done"]
    reasons = set(images.loc[images["image"] == "b_czyx", "reason"])
    assert reasons == {
        "b_czyx.tif: the file's own information says its axes are stored in the order CZYX, which does not "
        "match the layout ZCYX of this run (`image.axes` in the settings). Save the image with its axes in "
        "the order ZCYX, or run it with the layout CZYX."
    }
    spots = read_table(result.run_folder, "spots")
    assert list(dict.fromkeys(spots["image"])) == ["a_zcyx", "c_zcyx"]


def test_other_pixel_types_in_a_run(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    array = np.stack([make_image((8, 64, 64), n_spots=8, seed=seed)[0] for seed in (5, 6)], axis=1)
    write_image(folder / "a_uint16.tif", array)
    write_image(folder / "b_uint8.tif", (array // 4).clip(0, 255).astype(np.uint8))
    refused = ("float32", "int16", "int32", "uint32")
    for name in refused:
        tifffile.imwrite(folder / f"c_{name}.tif", array.astype(name), metadata={"axes": "ZCYX"},
                         photometric="minisblack")

    result = batch.run_batch(local_config(folder, tmp_path / "out", workers=2))
    assert result.status == "finished", result.message
    images = read_table(result.run_folder, "images")
    for name in ("a_uint16", "b_uint8"):
        assert list(images.loc[images["image"] == name, "status"]) == ["done", "done"], name
    text = log_text(result.run_folder)
    for name in refused:
        rows = images[images["image"] == f"c_{name}"]
        assert list(rows["status"]) == ["failed", "failed"], name
        reason = rows["reason"].iloc[0]
        assert reason.startswith(f"c_{name}.tif: the pixel type is "), reason
        assert f"({name}), which cannot be used; only 8-bit, 12-bit and 16-bit images are accepted." in reason
        assert reason.endswith("(https://imagej.net/ij/docs/menus/image.html#type), then run it again. In Fiji, first untick \"Scale when converting\" under Edit › Options › Conversions, so that the pixel values are kept.")
        assert f"c_{name}: failed: {reason}" in text
    assert "channels: 4 done, 8 failed, 0 skipped" in text


# ---------------------------------------------------------------------------
# What run.log holds (spec 8.4)
# ---------------------------------------------------------------------------


def test_log_holds_every_item(tmp_path):
    """A run with a finished, a failed and a skipped channel, a missing label file,
    a voxel size that differs from the file, and an image that cannot be read."""
    folder = tmp_path / "input"
    folder.mkdir()
    few = make_image((8, 64, 64), n_spots=8, seed=2)[0]
    many = make_image((8, 64, 64), n_spots=30, min_spacing=5, seed=1)[0]
    array = np.stack([few, few, many], axis=1)
    mixed = folder / "a_mixed.tif"
    tifffile.imwrite(mixed, array, imagej=True, metadata={"axes": "ZCYX", "unit": "um", "spacing": 0.3},
                     resolution=(1 / 0.065, 1 / 0.065), compression="zlib")
    # channel 1 cannot be read: the data of its first plane are overwritten
    with tifffile.TiffFile(mixed) as tif:
        start, length = tif.pages[1].dataoffsets[0], tif.pages[1].databytecounts[0]
    data = bytearray(mixed.read_bytes())
    data[start:start + length] = bytes(length)
    mixed.write_bytes(bytes(data))
    generated_image(folder / "b_corrupt.tif", n_channels=3)
    corrupt = folder / "b_corrupt.tif"
    corrupt.write_bytes(corrupt.read_bytes()[:3000])
    labels = tmp_path / "labels"
    labels.mkdir()
    channels = [
        {"index": 0, "name": "exon"},
        {"index": 1},
        {"index": 2, "bailout": {"enabled": True, "max_spots": 20},
         "threshold": {"mode": "auto", "lower_limit": 30}},
    ]
    config = with_changes(local_config(folder, tmp_path / "out", channels=channels), lambda data: data[
        "segmentation"].update(enabled=True, source="label_files", label_folder=str(labels)))
    settings = tmp_path / "settings.yaml"
    result = batch.run_batch(config, config_file=settings)
    assert result.status == "finished", result.message
    text = log_text(result.run_folder)
    images = read_table(result.run_folder, "images")
    threshold_2 = images.loc[(images["image"] == "a_mixed") & (images["channel"] == 2), "threshold"].iloc[0]

    for expected in (
        # config file used and image list
        f"Config file: {settings}",
        "2 image(s):\n",
        "  a_mixed.tif\n",
        "  b_corrupt.tif\n",
        # settings of each channel, with the spot radius in pixels
        "FISH channel 0 (exon): manual threshold 50; spot radius 1.12 px in Z, 0.99 px in Y and X",
        "FISH channel 1: manual threshold 50; spot radius 1.12 px in Z, 0.99 px in Y and X",
        "FISH channel 2: automatic threshold, found for each image, never below 30; spot radius",
        # each image started, finished or failed, and each channel done, failed or skipped
        "a_mixed: started",
        "a_mixed: finished",
        "b_corrupt: started",
        "b_corrupt: failed: b_corrupt.tif: the file is damaged or incomplete",
        # threshold used for each image and channel
        "a_mixed, channel 0: done, threshold 50, 8 spots, 0 clusters",
        "a_mixed, channel 1: failed, threshold none (a_mixed.tif: the pixel data cannot be read (",
        f"a_mixed, channel 2: skipped, threshold {threshold_2:g} (bailout: 30 spots detected, above the limit of 20)",
        "b_corrupt, channel 0: failed, threshold none (b_corrupt.tif: the file is damaged or incomplete",
        # warnings, each naming its image
        "a_mixed: warning: a_mixed.tif: voxel sizes differ (Z 300 nm in the file, 200 nm in the config)",
        "a_mixed: warning: no cell results: Label file not found",
        # summary
        "Summary: 2 of 2 image(s) finished, 0 not processed; channels: 1 done, 4 failed, 1 skipped. Total time ",
        "Images in which every channel failed: b_corrupt",
        "The run finished: 2 image(s) processed; 4 channel(s) failed and 1 skipped. "
        "See images.csv and run.log in the run folder.",
    ):
        assert expected in text, expected
    assert "Images not processed" not in text
    # each line of the log starts with the date and time, apart from the lines that continue one
    for line in text.splitlines():
        assert re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d  \S| {21}", line), line
    # every warning line names its image
    for line in text.splitlines():
        if ": warning: " in line:
            assert re.match(r"\S+ \S+  (a_mixed|b_corrupt)(, channel \d)?: warning: ", line), line


def test_log_without_a_config_file(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a"])
    result = run_fake(local_config(folder, tmp_path / "out"))
    assert "Config file: none (the settings were passed from Python)" in log_text(result.run_folder)


# ---------------------------------------------------------------------------
# .npz files of cancelled and stopped runs
# ---------------------------------------------------------------------------


def npz_process_image(config, image_name, image_source, run_folder, **arguments):
    """`fake_process_image` that also leaves `.npz` files, finished and temporary,
    before the image's worker is stopped or the run cancelled, and writes the
    `.npz` files of a finished image."""
    folder = Path(run_folder) / outputs.NPZ_FOLDER_NAME
    folder.mkdir(exist_ok=True)
    if any(word in image_name for word in ("slow", "cancel", "crash")):
        for channel in config.channels:
            path = outputs.npz_path(run_folder, image_name, channel.index)
            np.savez(path, spots=np.zeros((1, 3), dtype=np.int64))
            path.with_name(path.name + ".tmp").write_bytes(b"")
    result = fake_process_image(config, image_name, image_source, run_folder, **arguments)
    for channel in config.channels:
        np.savez(outputs.npz_path(run_folder, image_name, channel.index), spots=np.ones((1, 3), dtype=np.int64))
    return result


def npz_files(run_folder):
    return sorted(path.name for path in (run_folder / "npz").iterdir())


@pytest.mark.parametrize("names, workers, status, kept", [
    (["a", "b_slow", "c_cancel", "d"], 2, "cancelled", ["a"]),
    (["a", "b_crash_always", "c"], 1, "stopped", ["a"]),
    (["a", "b_crash_once", "c", "d"], 2, "finished", ["a", "b_crash_once", "c", "d"]),
])
def test_npz_files_of_finished_images_only(tmp_path, names, workers, status, kept):
    folder = tiny_images(tmp_path / "input", names)
    config = with_changes(local_config(folder, tmp_path / "out", workers=workers),
                          lambda data: data["outputs"].update(npz=True))
    result = batch.run_batch(config, image_function=npz_process_image)
    assert result.status == status, result.message
    assert npz_files(result.run_folder) == [f"{name}_ch{channel}.npz" for name in kept for channel in (0, 1)]
    for name in kept:
        with np.load(result.run_folder / "npz" / f"{name}_ch0.npz") as saved:
            assert saved["spots"].tolist() == [[1, 1, 1]]
    if status == "cancelled":
        assert "Images not processed: b_slow, c_cancel, d" in log_text(result.run_folder)


# ---------------------------------------------------------------------------
# Unexpected problems during a run
# ---------------------------------------------------------------------------


def key_error(*args, **kwargs):
    raise RuntimeError(f"session {KEY} refused")


@pytest.mark.parametrize("where", ["run_config", "pool", "end"])
def test_unexpected_problem_hides_the_session_key(tmp_path, omero_info, monkeypatch, where):
    """An unexpected problem whose text holds the session key: the error raised,
    its printed form and every file of the run folder are free of the key."""
    if where == "run_config":
        monkeypatch.setattr(batch.outputs, "write_run_config", key_error)
    elif where == "pool":
        # before the run is set up, so before run.log has any line
        monkeypatch.setattr(batch._WorkerPool, "__init__", key_error)
    else:
        monkeypatch.setattr(batch.outputs, "combine_tables", key_error)
    conn = FakeConn([(123, "a.tif"), (124, "b.tif")])
    shown = []
    with pytest.raises(batch.RunStoppedError) as raised:
        run_fake(omero_config(tmp_path / "out", dataset_id=5), omero_conn=conn, show=shown.append)
    error = raised.value
    [run_folder] = (tmp_path / "out").iterdir()
    assert error.run_folder == run_folder
    assert error.reason == "RuntimeError: session [hidden] refused"
    assert str(error) == (
        "The run stopped because of an unexpected problem: RuntimeError: session [hidden] refused\n"
        f"The details are in run.log in the run folder: {run_folder}"
    )
    assert error.__context__ is None and error.__cause__ is None
    printed = "".join(traceback.format_exception(error))
    assert KEY not in printed
    assert KEY not in "\n".join(shown)
    for path in run_folder.rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text(encoding="utf-8"), path.name
    text = log_text(run_folder)
    assert "The run stopped because of an unexpected problem: RuntimeError: session [hidden] refused" in text
    assert "Traceback" in text
    info = run_info(run_folder, "stopped")
    assert info["message"] == "The run stopped because of an unexpected problem: RuntimeError: session [hidden] refused"


# ---------------------------------------------------------------------------
# Calibrated thresholds
# ---------------------------------------------------------------------------


def calibrated_config(folder, output, filter_text="cal"):
    return local_config(
        folder, output, workers=2, qc=True,
        channels=[{"index": 0, "threshold": {"mode": "calibrated", "calibration_filter": filter_text}},
                  {"index": 1}],
    )


@pytest.fixture(scope="module")
def calibrated_run(tmp_path_factory):
    folder = tmp_path_factory.mktemp("calibrated_input")
    generated_image(folder / "cal_1.tif", seed=10, amplitude=400)
    generated_image(folder / "cal_2.tif", seed=20, amplitude=800)
    generated_image(folder / "cal_3_blank.tif", blank=True)
    generated_image(folder / "other.tif", seed=30)
    config = calibrated_config(folder, tmp_path_factory.mktemp("calibrated_output"))
    return folder, config, batch.run_batch(config)


def test_calibrated_mode(calibrated_run):
    folder, config, result = calibrated_run
    assert result.status == "finished", result.message
    run_folder = result.run_folder

    calibration = pd.read_csv(run_folder / "calibration.csv", keep_default_na=False)
    assert list(calibration["image"]) == ["cal_1", "cal_2", "cal_3_blank"]
    assert list(calibration["channel"]) == [0, 0, 0]
    assert list(calibration["used"]) == [True, True, False]
    assert calibration["reason"].iloc[2] == batch.NO_AUTO_THRESHOLD_REASON

    expected = [batch.calibration_threshold(config, name, folder / f"{name}.tif", 0)["threshold"]
                for name in ("cal_1", "cal_2")]
    median = float(np.median(expected))
    assert list(calibration["auto_threshold"].iloc[:2].astype(float)) == expected

    run_config = load_config(run_folder / "run_config.yaml")
    assert run_config.resolved.thresholds == {0: median}
    assert run_config.resolved.images == ["cal_1.tif", "cal_2.tif", "cal_3_blank.tif", "other.tif"]

    images = read_table(run_folder, "images")
    channel_0 = images[images["channel"] == 0]
    assert len(channel_0) == 4
    assert (channel_0["threshold"] == median).all()
    assert (channel_0["threshold_mode"] == "calibrated").all()
    assert (images[images["channel"] == 1]["threshold"] == 50).all()
    assert f"Channel 0: calibrated threshold {median:g} (median of 2 image(s); 1 left out)" in log_text(run_folder)
    assert run_info(run_folder, "finished")["calibrated_thresholds"] == {"channel 0": median}


def test_repeat_calibrated_run(calibrated_run, tmp_path):
    folder, _, first = calibrated_run
    config = load_config(first.run_folder / "run_config.yaml")
    result = batch.run_batch(config)
    assert result.status == "finished"
    assert not (result.run_folder / "calibration.csv").exists()
    assert "from the config (not calibrated again)" in log_text(result.run_folder)
    assert "(calibration): started" not in log_text(result.run_folder)
    same_tables(first.run_folder, result.run_folder)
    thresholds = run_info(result.run_folder, "finished")["calibrated_thresholds"]
    assert thresholds == run_info(first.run_folder, "finished")["calibrated_thresholds"]

    # A listed image that has gone missing stops the run before processing.
    copy = tmp_path / "copy"
    shutil.copytree(folder, copy)
    (copy / "cal_2.tif").unlink()
    output = tmp_path / "out"

    def change(data):
        data["run"]["output_folder"] = str(output)
        data["run"]["input"]["folder"] = str(copy)

    moved = with_changes(config, change)
    with pytest.raises(batch.BatchError, match="cal_2.tif"):
        batch.run_batch(moved)
    assert not output.exists()


def test_calibration_without_usable_value(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    generated_image(folder / "cal_blank.tif", blank=True)
    generated_image(folder / "other.tif", seed=3)
    result = batch.run_batch(calibrated_config(folder, tmp_path / "out"))
    assert result.status == "stopped"
    assert "No calibrated threshold for channel 0" in result.message
    calibration = pd.read_csv(result.run_folder / "calibration.csv", keep_default_na=False)
    assert list(calibration["image"]) == ["cal_blank"]
    assert list(calibration["used"]) == [False]
    assert per_image_files(result.run_folder) == []
    assert not (result.run_folder / "images.csv").exists()
    assert progress(result.run_folder)["status"] == "stopped"
    info = run_info(result.run_folder, "stopped")
    assert info["message"] == result.message
    assert info["calibrated_thresholds"] == "none"


def test_calibration_filter_matches_nothing(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    generated_image(folder / "other.tif", seed=3)
    with pytest.raises(batch.BatchError, match="calibration filter of channel 0"):
        batch.run_batch(calibrated_config(folder, tmp_path / "out", filter_text="nothing"))
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# Number of workers
# ---------------------------------------------------------------------------

FULL_CHANNEL = 2048 * 2048 * 35  # voxels


def test_auto_workers():
    n, reason, warning = batch.choose_workers("auto", 10, FULL_CHANNEL, 8, 16e9)
    assert n == 2  # (16 − 2) GB ÷ 5.6 GB
    assert warning is None
    assert "chosen automatically" in reason and "5.6 GB per worker" in reason
    assert "8 processor cores (one left for the main process)" in reason
    assert batch.choose_workers("auto", 10, 100, 4, 64e9)[0] == 3  # cores − 1
    assert batch.choose_workers("auto", 2, 100, 16, 64e9)[0] == 2  # number of images
    assert batch.choose_workers("auto", 10, 100, 1, 64e9)[0] == 1  # one core
    assert batch.choose_workers("auto", 10, 100, None, 64e9)[0] == 1
    assert batch.choose_workers("auto", 10, 100, 16, 3.6e9)[0] == 3  # 0.5 GB floor
    assert batch.memory_per_worker(100) == batch.MIN_MEMORY_PER_WORKER
    assert batch.memory_per_worker(FULL_CHANNEL) == 38 * FULL_CHANNEL


def test_auto_workers_leave_cores_to_cellpose_on_the_cpu():
    # 10 cores: 9 for workers, or 6 beside the 4 threads of Cellpose on the CPU
    assert batch.choose_workers("auto", 20, 100, 10, 64e9, cellpose=True)[0] == 9
    n, reason, warning = batch.choose_workers("auto", 20, 100, 10, 64e9, cellpose=True, cellpose_on_cpu=True)
    assert n == 6
    assert warning is None
    assert "10 processor cores (4 left for Cellpose on the CPU)" in reason
    # a small computer keeps one worker
    assert batch.choose_workers("auto", 20, 100, 4, 64e9, cellpose=True, cellpose_on_cpu=True)[0] == 1
    assert batch.choose_workers("auto", 20, 100, 2, 64e9, cellpose=True, cellpose_on_cpu=True)[0] == 1
    assert batch.worker_cores(10) == 9
    assert batch.worker_cores(10, cellpose_on_cpu=True) == 6
    assert batch.worker_cores(None, cellpose_on_cpu=True) == 1
    # a number given in the config is used as it is
    assert batch.choose_workers(9, 20, 100, 10, 64e9, cellpose=True, cellpose_on_cpu=True)[0] == 9


def test_auto_workers_little_memory_available():
    """Short of available memory but enough in the computer: one worker and a warning."""
    n, reason, warning = batch.choose_workers("auto", 10, FULL_CHANNEL, 8, 4e9, total_memory=16e9)
    assert n == 1
    assert "room for 0" in reason
    assert warning.startswith("little memory is available at the moment")


def test_auto_workers_not_enough_memory():
    with pytest.raises(batch.BatchError, match="not enough memory for one worker"):
        batch.choose_workers("auto", 10, FULL_CHANNEL, 8, 4e9, total_memory=6e9)
    with pytest.raises(batch.BatchError, match="not enough memory"):
        batch.choose_workers("auto", 10, 100, 8, 1e9, total_memory=2.2e9)
    # without the computer's total, the available memory stands in for it
    with pytest.raises(batch.BatchError, match="not enough memory"):
        batch.choose_workers("auto", 10, FULL_CHANNEL, 8, 6e9)


def test_workers_from_config():
    assert batch.choose_workers(3, 10, 100, 8, 64e9) == (3, "3 worker(s), as set in the config", None)
    n, reason, warning = batch.choose_workers(4, 2, 100, 8, 64e9)
    assert n == 2 and "only 2 image(s)" in reason
    n, _, warning = batch.choose_workers(3, 10, FULL_CHANNEL, 8, 8e9)
    assert n == 3
    assert warning.startswith("memory may run short with 3 worker(s)")
    n, _, warning = batch.choose_workers(1, 10, FULL_CHANNEL, 8, 1e9)
    assert n == 1 and warning is not None


def test_not_enough_memory_stops_before_processing(tmp_path, monkeypatch):
    folder = tiny_images(tmp_path / "input", ["a"])
    monkeypatch.setattr(batch.psutil, "virtual_memory", lambda: SimpleNamespace(available=1e9, total=2e9))
    with pytest.raises(batch.BatchError, match="not enough memory"):
        run_fake(local_config(folder, tmp_path / "out", workers="auto"))
    assert not (tmp_path / "out").exists()


def test_thread_variables_in_worker(tmp_path):
    folder = tiny_images(tmp_path / "input", ["threads"])
    before = {name: os.environ.get(name) for name in batch.THREAD_VARIABLES}
    result = run_fake(local_config(folder, tmp_path / "out"))
    images = read_table(result.run_folder, "images")
    assert images["warnings"].iloc[0] == "OMP_NUM_THREADS=1; OPENBLAS_NUM_THREADS=1; MKL_NUM_THREADS=1"
    assert {name: os.environ.get(name) for name in batch.THREAD_VARIABLES} == before


# ---------------------------------------------------------------------------
# Cancel and stopped workers
# ---------------------------------------------------------------------------


def test_cancel_file(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a", "b_slow", "c_cancel", "d"])
    result = run_fake(local_config(folder, tmp_path / "out", workers=2))
    assert result.status == "cancelled"
    assert "cancel" in result.message
    run_folder = result.run_folder
    assert progress(run_folder)["status"] == "cancelled"
    assert list(read_table(run_folder, "images")["image"]) == ["a", "a"]
    assert list(dict.fromkeys(read_table(run_folder, "spots")["image"])) == ["a"]
    assert per_image_files(run_folder) == ["a_images.csv", "a_spots.csv"]
    text = log_text(run_folder)
    assert "Discarded (in progress): b_slow, c_cancel" in text
    assert "d: started" not in text
    assert "Summary: 1 of 4 image(s) finished, 3 not processed" in text
    info = run_info(run_folder, "cancelled")
    assert info["message"] == result.message
    assert info["worker_restarts"] == "none"


def test_ctrl_c_cancels(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a"])
    config = local_config(folder, tmp_path / "out")

    # Ctrl+C is sent to the main process once the image has started.
    def show(text):
        if text.startswith("a: started"):
            signal.raise_signal(signal.SIGINT)

    result = run_fake(config, show=show)
    assert result.status == "cancelled"
    assert "Ctrl+C" in result.message
    assert "Ctrl+C" in run_info(result.run_folder, "cancelled")["message"]


def test_worker_stopped_once_is_retried(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a", "b_crash_once", "c", "d"])
    result = run_fake(local_config(folder, tmp_path / "out", workers=2))
    assert result.status == "finished"
    images = read_table(result.run_folder, "images")
    assert list(dict.fromkeys(images["image"])) == ["a", "b_crash_once", "c", "d"]
    assert (images["status"] == "done").all()
    text = log_text(result.run_folder)
    assert "A worker process stopped unexpectedly" in text
    assert "Starting again with 1 worker(s); b_crash_once will be tried once more." in text
    info = run_info(result.run_folder, "finished")
    assert info["workers"] == 2
    [restart] = info["worker_restarts"]
    assert restart["workers"] == 1
    assert "b_crash_once" in restart["images_lost"]


def test_worker_stopped_twice_marks_image_failed(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a", "b_crash_always", "c", "d"])
    result = run_fake(local_config(folder, tmp_path / "out", workers=4))
    assert result.status == "finished"
    images = read_table(result.run_folder, "images")
    assert list(dict.fromkeys(images["image"])) == ["a", "b_crash_always", "c", "d"]
    failed = images[images["image"] == "b_crash_always"]
    assert list(failed["status"]) == ["failed", "failed"]
    assert (failed["reason"] == batch.WORKER_STOPPED_REASON).all()
    assert (images[images["image"] != "b_crash_always"]["status"] == "done").all()
    text = log_text(result.run_folder)
    assert text.count("A worker process stopped unexpectedly") == 2
    assert "Starting again with 2 worker(s)" in text
    info = run_info(result.run_folder, "finished")
    assert info["workers"] == 4
    assert [restart["workers"] for restart in info["worker_restarts"]] == [2, 1]
    assert all("b_crash_always" in restart["images_lost"] for restart in info["worker_restarts"])


def test_worker_stopped_with_one_worker(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a", "b_crash_always", "c"])
    result = run_fake(local_config(folder, tmp_path / "out", workers=1))
    assert result.status == "stopped"
    assert "only one worker" in result.message
    assert list(dict.fromkeys(read_table(result.run_folder, "images")["image"])) == ["a"]
    assert per_image_files(result.run_folder) == ["a_images.csv", "a_spots.csv"]
    assert progress(result.run_folder)["status"] == "stopped"
    assert "A worker process stopped unexpectedly" in log_text(result.run_folder)
    info = run_info(result.run_folder, "stopped")
    assert info["message"] == result.message
    assert info["worker_restarts"] == "none"


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------


def test_run_info_first_part_and_command(tmp_path):
    """While the run is going, the file is the valid first part and says the run has not ended."""
    folder = tiny_images(tmp_path / "input", ["a"])
    seen = {}

    def show(text):
        if text.startswith("a: started"):
            [run_folder] = (tmp_path / "out").iterdir()
            seen["first"] = outputs.read_run_info(run_folder)

    command = "Batch page of the app, settings my_settings.yaml"
    result = run_fake(local_config(folder, tmp_path / "out"), show=show, command=command)
    first = seen["first"]
    assert list(first) == RUN_INFO_KEYS
    for key in ("status", "ended", "duration"):
        assert first[key] == "not ended"
    assert "has not ended" in first["message"]
    assert first["worker_restarts"] == "none"
    final = run_info(result.run_folder, "finished")
    assert final["command"] == command
    for key in RUN_INFO_KEYS:
        if key not in ("status", "message", "ended", "duration"):
            assert first[key] == final[key], key


def test_run_info_after_an_error_in_the_run(tmp_path, monkeypatch):
    folder = tiny_images(tmp_path / "input", ["a"])

    def broken(*args, **kwargs):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(batch.outputs, "write_run_config", broken)
    with pytest.raises(batch.RunStoppedError, match="the disk is full"):
        run_fake(local_config(folder, tmp_path / "out"))
    [run_folder] = (tmp_path / "out").iterdir()
    info = run_info(run_folder, "stopped")
    assert info["message"] == "The run stopped because of an unexpected problem: RuntimeError: the disk is full"


def test_run_info_of_an_omero_run(tmp_path, omero_info, monkeypatch):
    """Only the server and the port of OMERO are in the file: no session key and no user name."""
    conn = FakeConn([(123, "a.tif"), (124, "b key_in_error.tif")])
    config = omero_config(tmp_path / "out", dataset_id=5, username="omero_user_name", port=4065)
    result = run_fake(config, omero_conn=conn)
    assert result.status == "finished"
    text = (result.run_folder / "run_info.yaml").read_text(encoding="utf-8")
    assert KEY not in text
    assert "omero_user_name" not in text
    assert run_info(result.run_folder, "finished")["omero_server"] == "omero.example, port 4065"

    # an unexpected problem whose message holds the session key
    def broken(*args, **kwargs):
        raise RuntimeError(f"session {KEY} refused")

    monkeypatch.setattr(batch.outputs, "write_run_config", broken)
    with pytest.raises(batch.RunStoppedError):
        run_fake(omero_config(tmp_path / "again", dataset_id=5, username="omero_user_name"), omero_conn=conn)
    [run_folder] = (tmp_path / "again").iterdir()
    text = (run_folder / "run_info.yaml").read_text(encoding="utf-8")
    assert KEY not in text and "omero_user_name" not in text
    assert run_info(run_folder, "stopped")["message"].endswith("session [hidden] refused")


# ---------------------------------------------------------------------------
# Stops before processing
# ---------------------------------------------------------------------------


def test_no_images(tmp_path):
    (tmp_path / "input").mkdir()
    with pytest.raises(batch.BatchError, match="No images"):
        batch.run_batch(local_config(tmp_path / "input", tmp_path / "out"))
    assert not (tmp_path / "out").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="folder permissions work differently on Windows")
def test_output_folder_not_writable(tmp_path):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("the administrator can write anywhere")
    folder = tiny_images(tmp_path / "input", ["a"])
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        with pytest.raises(batch.BatchError, match="cannot be written to"):
            batch.run_batch(local_config(folder, locked / "out"))
        assert list(locked.iterdir()) == []
    finally:
        locked.chmod(0o755)


def test_channel_not_in_first_image(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a"])
    config = local_config(folder, tmp_path / "out", channels=[{"index": 0}, {"index": 3}])
    with pytest.raises(batch.BatchError, match="channel 3 does not exist"):
        batch.run_batch(config)
    assert not (tmp_path / "out").exists()


def test_segmentation_channel_not_in_first_image(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a"])
    config = with_changes(local_config(folder, tmp_path / "out"), lambda data: data["segmentation"].update(
        enabled=True, source="cellpose", channel=4))
    with pytest.raises(batch.BatchError, match="channel 4 does not exist"):
        batch.run_batch(config)
    assert not (tmp_path / "out").exists()


def test_missing_label_folder(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a"])
    config = with_changes(local_config(folder, tmp_path / "out"), lambda data: data["segmentation"].update(
        enabled=True, source="label_files", label_folder=str(tmp_path / "nowhere")))
    with pytest.raises(batch.BatchError, match="label folder"):
        batch.run_batch(config)


def test_same_output_name(tmp_path, monkeypatch):
    folder = tiny_images(tmp_path / "input", ["a"])
    monkeypatch.setattr(batch.io, "list_images", lambda *args: [folder / "a.tif", folder / "A.tif"])
    with pytest.raises(batch.BatchError, match="same output name: a.tif, A.tif"):
        batch.run_batch(local_config(folder, tmp_path / "out"))
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# OMERO, with stand-ins for the server
# ---------------------------------------------------------------------------


class FakeImage:
    def __init__(self, image_id, name):
        self.image_id, self.name = image_id, name

    def getId(self):
        return self.image_id

    def getName(self):
        return self.name


class FakeConn:
    """Logged-in connection serving one dataset."""

    def __init__(self, names):
        self.c = SimpleNamespace(getSessionId=lambda: KEY)
        self.images = [FakeImage(image_id, name) for image_id, name in names]
        self.closed = False

    def getObject(self, kind, object_id):
        if kind == "Dataset" and object_id == 5:
            return SimpleNamespace(listChildren=lambda: list(self.images))
        if kind == "Image":
            for image in self.images:
                if image.image_id == object_id:
                    return image
        return None

    def close(self, hard=True):
        self.closed = True


@pytest.fixture
def omero_info(monkeypatch):
    def get_omero_image_info(conn, image_id):
        return io.OmeroImageInfo(
            image_id=image_id, name="x", size_z=2, size_c=2, size_t=1, size_y=16, size_x=16,
            pixel_type="uint16", dtype=np.dtype("uint16"), voxel_size_z=200.0,
            voxel_size_y=65.0, voxel_size_x=65.0, channel_names=["a", "b"],
        )

    monkeypatch.setattr(io, "get_omero_image_info", get_omero_image_info)


def omero_config(output, **omero_settings):
    config = local_config("", output, workers=2)

    def change(data):
        data["run"]["input"].update(source="omero", folder="")
        data["run"]["input"]["omero"].update(host="omero.example", **omero_settings)

    return with_changes(config, change)


def test_omero_dataset(tmp_path, omero_info):
    conn = FakeConn([(124, "b.tif"), (123, "a:1.tif"), (125, "c key_in_error.tif")])
    result = run_fake(omero_config(tmp_path / "out", dataset_id=5), omero_conn=conn)
    assert result.status == "finished"
    assert not conn.closed
    images = read_table(result.run_folder, "images")
    assert list(dict.fromkeys(images["image"])) == ["123_a_1", "124_b", "125_c key_in_error"]
    failed = images[images["image"] == "125_c key_in_error"]
    assert (failed["status"] == "failed").all()
    assert "[hidden]" in failed["reason"].iloc[0]
    assert "read with session [hidden] from omero.example" in log_text(result.run_folder)

    run_config = load_config(result.run_folder / "run_config.yaml")
    assert run_config.resolved.images == ["123_a_1", "124_b", "125_c key_in_error"]
    for path in result.run_folder.rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text(encoding="utf-8"), path.name
    assert KEY not in result.message


def test_omero_session_ended(tmp_path, omero_info):
    conn = FakeConn([(1, "a.tif"), (2, "b session_ended.tif"), (3, "c.tif")])
    config = with_changes(omero_config(tmp_path / "out", image_ids=[1, 2, 3]),
                          lambda data: data["run"].update(workers=1))
    result = run_fake(config, omero_conn=conn)
    assert result.status == "stopped"
    assert "Log in again" in result.message
    assert list(dict.fromkeys(read_table(result.run_folder, "images")["image"])) == ["1_a"]
    assert "3_c: started" not in log_text(result.run_folder)
    info = run_info(result.run_folder, "stopped")
    assert "Log in again" in info["message"]
    assert info["omero_server"] == "omero.example, port 4064"


def test_omero_needs_dataset_or_images(tmp_path):
    with pytest.raises(batch.BatchError, match="dataset ID or image IDs"):
        run_fake(omero_config(tmp_path / "out"), omero_conn=FakeConn([]))


def dropped_connection_images():
    return [(1, "a drop_once.tif"), (2, "b drop_twice.tif"), (3, "c.tif")]


def test_omero_dropped_connection_in_a_worker(tmp_path, omero_info):
    conn = FakeConn(dropped_connection_images())
    config = with_changes(omero_config(tmp_path / "out", image_ids=[1, 2, 3]),
                          lambda data: data["run"].update(workers=1))
    result = batch.run_batch(config, omero_conn=conn, image_function=omero_process_image)
    assert result.status == "finished", result.message
    images = read_table(result.run_folder, "images")
    status = images.groupby("image")["status"].agg(set).to_dict()
    assert status == {"1_a drop_once": {"done"}, "2_b drop_twice": {"failed"}, "3_c": {"done"}}
    reasons = set(images.loc[images["image"] == "2_b drop_twice", "reason"])
    assert reasons == {
        "OMERO image 2: lost the connection to OMERO twice "
        "(ConnectionLostException: Ice.ConnectionLostException: session [hidden])"
    }

    text = log_text(result.run_folder)
    assert ("1_a drop_once: OMERO image 1: lost the connection to OMERO (ConnectionLostException: "
            "Ice.ConnectionLostException: session [hidden]); rejoining the session and trying again") in text
    # image 1 joins, drops and rejoins (2 joins); image 2 rejoins once (3 joins);
    # image 3 goes on with the third connection without joining again
    assert "1_a drop_once: connection 2 after 2 join(s)" in text
    assert "2_b drop_twice: connection 3 after 3 join(s)" in text
    assert "3_c: connection 3 after 3 join(s)" in text
    for path in result.run_folder.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes(), path.name


def test_omero_messages_not_in_the_terminal(tmp_path):
    """omero-py's messages (with the session key) and the warnings of other packages
    are not printed, in the main process or in the workers; the run's own lines are."""
    script = tmp_path / "script.py"
    script.write_text(textwrap.dedent("""
        import logging

        import numpy as np

        from batch_helpers import log_like_omero, omero_process_image
        from bigfish_pypeline import batch, io
        from test_batch_run import KEY, FakeConn, omero_config, with_changes


        class LoggingConn(FakeConn):
            def getObject(self, kind, object_id):
                log_like_omero(KEY)
                return super().getObject(kind, object_id)


        def get_omero_image_info(conn, image_id):
            log_like_omero(KEY)
            return io.OmeroImageInfo(
                image_id=image_id, name="x", size_z=2, size_c=2, size_t=1, size_y=16, size_x=16,
                pixel_type="uint16", dtype=np.dtype("uint16"), voxel_size_z=200.0,
                voxel_size_y=65.0, voxel_size_x=65.0, channel_names=["a", "b"],
            )


        if __name__ == "__main__":
            io.get_omero_image_info = get_omero_image_info
            root = logging.getLogger()
            conn = LoggingConn([(1, "a drop_once.tif"), (2, "b drop_twice.tif"), (3, "c.tif")])
            config = with_changes(omero_config("out", image_ids=[1, 2, 3]),
                                  lambda data: data["run"].update(workers=1))
            plan = batch.plan_run(config, conn)
            plan.close()
            assert root.handlers == [], root.handlers
            result = batch.run_batch(config, omero_conn=conn, image_function=omero_process_image, show=print)
            assert result.status == "finished", result.message
            assert root.handlers == [], root.handlers
    """), encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).parent)] + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [])
    )
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                          timeout=300, env=environment, cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    terminal = done.stdout + done.stderr
    assert KEY not in terminal
    assert "Traceback" not in terminal
    assert "WARNING:" not in terminal and "ERROR:" not in terminal
    assert "CPDINO" not in terminal
    assert "killSession" not in terminal
    # the run's own message about the dropped connection is shown, in plain words
    assert "1_a drop_once: OMERO image 1: lost the connection to OMERO" in done.stdout
    assert "rejoining the session and trying again" in done.stdout


# ---------------------------------------------------------------------------
# QC files
# ---------------------------------------------------------------------------

QC_ON = {"elbow_plot": True, "detection": True, "reference_spot": True, "cellpose": True}


def qc_files(run_folder):
    folder = run_folder / "qc"
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


def no_qc_leftovers(run_folder):
    assert not (run_folder / batch.QC_TEMPORARY_FOLDER_NAME).exists()
    assert not [name for name in qc_files(run_folder) if name.endswith(".tmp")]


@pytest.fixture(scope="module")
def qc_kit_runs(crop_config_path, test_kit_folder, tmp_path_factory):
    """The test kit run with every output on (final QC as PNG and as HTML) and with every QC file off."""
    folder = tmp_path_factory.mktemp("qc_kit_input")
    shutil.copy(test_kit_folder / f"{CROP_NAME}.tif", folder)
    shutil.copy(test_kit_folder / f"{CROP_NAME}_seglabels.tif", folder)
    generated_image(folder / "zz_generated.tif", n_channels=3)
    output = tmp_path_factory.mktemp("qc_kit_output")

    def change(data):
        data["run"]["input"].update(folder=str(folder), filter="")
        data["run"].update(output_folder=str(output), workers=2)
        data["segmentation"]["label_folder"] = str(folder)
        data["outputs"].update(npz=True, label_images=True)

    config = with_changes(load_config(crop_config_path), change)
    runs = {}
    for name, qc in (("png", {**QC_ON, "final": "png"}), ("html", {**QC_ON, "final": "html"}),
                     ("off", QC_OFF)):
        runs[name] = batch.run_batch(with_changes(config, lambda data: data["outputs"]["qc"].update(qc)))
    return runs


def expected_kit_qc_files(final):
    files = []
    for image in (CROP_NAME, "zz_generated"):
        files += [f"{image}_ch2_{kind}" for kind in
                  ("detection.png", "elbow.png", f"final.{final}", "referencespot.tif")]
    return sorted(files)


def test_kit_every_output(qc_kit_runs):
    for final in ("png", "html"):
        result = qc_kit_runs[final]
        assert result.status == "finished", result.message
        folder = result.run_folder
        # spec 8.1, apart from `labels/` (made by Cellpose runs only) and
        # `calibration.csv` (calibrated thresholds only)
        for name in ("run_config.yaml", "run_info.yaml", "run.log", "progress.json", "images.csv",
                     "spots.csv", "clusters.csv", "cells.csv", "per_image", "qc", "npz"):
            assert (folder / name).exists(), name
        assert sorted(path.name for path in (folder / "npz").iterdir()) == [
            f"{CROP_NAME}_ch2.npz", "zz_generated_ch2.npz"]
        assert qc_files(folder) == expected_kit_qc_files(final), final
        no_qc_leftovers(folder)
        images = read_table(folder, "images")
        assert not images["warnings"].fillna("").str.contains("QC file").any()
        text = log_text(folder)
        assert f"QC images: elbow plot, detection plot, reference spot, final QC ({final.upper()})" in text
        assert text.index("QC images:") < text.index(f"{CROP_NAME}: started")
    page = (qc_kit_runs["html"].run_folder / "qc" / f"{CROP_NAME}_ch2_final.html").read_text(encoding="utf-8")
    assert "44 cells" in page and "692 spots" in page and "6 clusters" in page
    # plotly's script is inside the page, so that it opens on its own
    assert 'src="plotly.min.js"' not in page and "plotly.js v" in page


def test_kit_tables_equal_with_qc_on_and_off(qc_kit_runs, crop_reference_folder):
    off = qc_kit_runs["off"]
    assert off.status == "finished", off.message
    assert not (off.run_folder / "qc").exists()
    no_qc_leftovers(off.run_folder)
    assert "QC images: none" in log_text(off.run_folder)
    for final in ("png", "html"):
        same_tables(qc_kit_runs[final].run_folder, off.run_folder)
    reference = np.load(next((crop_reference_folder / "general_manual18_subpixel-off").glob("*_bfoutput.npz")))
    spots = read_table(qc_kit_runs["html"].run_folder, "spots")
    spots = spots[spots["image"] == CROP_NAME]
    np.testing.assert_array_equal(
        spots[["z_px", "y_px", "x_px", "cluster_id"]].to_numpy(), reference["spots_post_clustering"]
    )


def test_kit_repeat_with_qc_off(qc_kit_runs):
    """`run_config.yaml` of a run with the QC files on, repeated with them off, gives the same tables."""
    first = qc_kit_runs["html"].run_folder
    config = with_changes(load_config(first / "run_config.yaml"),
                          lambda data: data["outputs"]["qc"].update(QC_OFF))
    result = batch.run_batch(config)
    assert result.status == "finished", result.message
    same_tables(first, result.run_folder)
    assert not (result.run_folder / "qc").exists()


def test_calibration_plot(calibrated_run, tmp_path):
    _, _, first = calibrated_run
    assert (first.run_folder / "qc" / "calibration.png").is_file()
    assert "QC images: elbow plot, calibration plot, detection plot" in log_text(first.run_folder)
    no_qc_leftovers(first.run_folder)

    # the repeated run takes its thresholds from run_config.yaml and does not calibrate
    result = batch.run_batch(load_config(first.run_folder / "run_config.yaml"))
    assert result.status == "finished", result.message
    files = qc_files(result.run_folder)
    assert "calibration.png" not in files
    assert "cal_1_ch0_elbow.png" in files
    assert "calibration plot" not in log_text(result.run_folder)


def test_calibration_plot_switched_off_with_the_elbow_plot(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    generated_image(folder / "cal_1.tif", seed=10, amplitude=400)
    config = with_changes(calibrated_config(folder, tmp_path / "out"),
                          lambda data: data["outputs"]["qc"].update(QC_OFF, detection=True))
    result = batch.run_batch(config)
    assert result.status == "finished", result.message
    assert (result.run_folder / "calibration.csv").is_file()
    assert qc_files(result.run_folder) == ["cal_1_ch0_detection.png", "cal_1_ch1_detection.png"]


def test_calibration_plot_that_fails(tmp_path, monkeypatch):
    from bigfish_pypeline import qc

    def broken(*args, **kwargs):
        raise OSError("no space left on the disk")

    monkeypatch.setattr(qc, "write_calibration_plot", broken)
    folder = tmp_path / "input"
    folder.mkdir()
    generated_image(folder / "cal_1.tif", seed=10, amplitude=400)
    result = batch.run_batch(calibrated_config(folder, tmp_path / "out"))
    assert result.status == "finished", result.message
    assert ("Warning: the QC file calibration.png could not be written: OSError: no space left on the disk"
            in log_text(result.run_folder))
    assert "calibration.png" not in qc_files(result.run_folder)


def failing_qc_process_image(config, image_name, image_source, run_folder, **arguments):
    """`process_image` in which every elbow plot fails to be written."""
    from bigfish_pypeline import qc

    def broken(*args, **kwargs):
        raise OSError("no space left on the disk")

    qc.write_elbow_plot = broken
    return batch.process_image(config, image_name, image_source, run_folder, **arguments)


def test_qc_file_that_fails_in_a_run(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    generated_image(folder / "a.tif")
    result = batch.run_batch(local_config(folder, tmp_path / "out", qc=True), image_function=failing_qc_process_image)
    assert result.status == "finished", result.message
    images = read_table(result.run_folder, "images")
    assert list(images["status"]) == ["done", "done"]
    text = log_text(result.run_folder)
    for channel in (0, 1):
        warning = f"the QC file a_ch{channel}_elbow.png could not be written: OSError: no space left on the disk"
        assert images["warnings"][channel].endswith(warning)
        assert f"a, channel {channel}: warning: {warning}" in text
    assert qc_files(result.run_folder) == [
        f"a_ch{channel}_{kind}" for channel in (0, 1)
        for kind in ("detection.png", "final.png", "referencespot.tif")
    ]


def qc_process_image(config, image_name, image_source, run_folder, **arguments):
    """`fake_process_image` that also leaves QC files, with their final names, in
    the folder they are drawn in and under temporary names, before the image's
    worker is stopped or the run cancelled, and writes the QC files of a
    finished image (with a final QC page when its name holds `page`)."""
    run_folder = Path(run_folder)
    qc_folder = run_folder / "qc"
    qc_folder.mkdir(exist_ok=True)
    stops = any(word in image_name for word in ("slow", "cancel", "crash_always"))
    if "crash_once" in image_name and not (run_folder.parent / f"{image_name}.crashed").exists():
        stops = True
    if stops:
        staging = run_folder / batch.QC_TEMPORARY_FOLDER_NAME / image_name / "qc"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / f"{image_name}_ch0_detection.png").write_bytes(b"png")
        (qc_folder / f"{image_name}_ch0_elbow.png").write_bytes(b"png")
        (qc_folder / f"{image_name}_ch1_final.html").write_text("page", encoding="utf-8")
        (qc_folder / f"{image_name}_ch1_detection.png.tmp").write_bytes(b"")
    result = fake_process_image(config, image_name, image_source, run_folder, **arguments)
    for channel in config.channels:
        (qc_folder / f"{image_name}_ch{channel.index}_elbow.png").write_bytes(b"png")
    if "page" in image_name:
        (qc_folder / f"{image_name}_ch0_final.html").write_text("page", encoding="utf-8")
    return result


@pytest.mark.parametrize("names, workers, status, kept", [
    (["a", "b_slow", "c_cancel", "d"], 2, "cancelled", ["a"]),
    (["a_page", "b_slow", "c_cancel"], 2, "cancelled", ["a_page"]),
    (["a", "b_crash_always", "c"], 1, "stopped", ["a"]),
    (["a", "b_crash_once", "c", "d"], 2, "finished", ["a", "b_crash_once", "c", "d"]),
])
def test_qc_files_of_finished_images_only(tmp_path, names, workers, status, kept):
    folder = tiny_images(tmp_path / "input", names)
    result = batch.run_batch(local_config(folder, tmp_path / "out", workers=workers, qc=True),
                             image_function=qc_process_image)
    assert result.status == status, result.message
    expected = [f"{name}_ch{channel}_elbow.png" for name in kept for channel in (0, 1)]
    expected += [f"{name}_ch0_final.html" for name in kept if "page" in name]
    assert qc_files(result.run_folder) == sorted(expected)
    no_qc_leftovers(result.run_folder)


# ---------------------------------------------------------------------------
# Stops, stopped workers and the end of a run
# ---------------------------------------------------------------------------


class InProcessPool:
    """Stand-in for batch._WorkerPool that runs each image in this process at once.

    Words in the image name: `lost` writes a file, then the image's worker stops;
    `hang` writes a file and never ends; `session_ended` is as in
    fake_process_image. Images are handed out in one pass when there are workers
    enough, so their results come back together.
    """

    def __init__(self, n_workers):
        self.n_workers = n_workers
        self.handed_out = []

    def submit(self, function, **arguments):
        from concurrent.futures import Future
        from concurrent.futures.process import BrokenProcessPool

        future = Future()
        name = arguments["image_name"]
        self.handed_out.append(name)
        per_image = Path(arguments["run_folder"]) / "per_image"
        if "lost" in name or "hang" in name:
            (per_image / f"{name}_spots.csv").write_text("image\n", encoding="utf-8")
            (per_image / f"{name}_images.csv.tmp").write_text("image\n", encoding="utf-8")
            if "lost" in name:
                future.set_exception(BrokenProcessPool("a worker stopped"))
            return future
        try:
            future.set_result(function(**arguments))
        except BaseException as error:
            future.set_exception(error)
        return future

    def stop_now(self):
        pass

    def close(self):
        pass


def test_stop_takes_no_further_result(tmp_path, monkeypatch):
    """A stop found in the same pass as a stopped worker and other results: the
    message is shown once, at the end; no further result is taken, and the files
    of every image not finished are removed, the lost image's included."""
    monkeypatch.setattr(batch, "_WorkerPool", InProcessPool)
    folder = tiny_images(tmp_path / "input", ["a", "b_lost", "c_session_ended", "d", "e_hang", "f"])
    config = local_config(folder, tmp_path / "out", workers=5)
    shown = []
    started = __import__("time").monotonic()
    result = run_fake(config, show=shown.append)
    assert __import__("time").monotonic() - started < batch.CHECK_INTERVAL_S * 5
    assert result.status == "stopped"
    message = batch.OMERO_SESSION_ENDED_MESSAGE
    assert result.message == message
    run_folder = result.run_folder
    # a to e are handed out in one pass; the result of `a` comes before the stop
    assert list(dict.fromkeys(read_table(run_folder, "images")["image"])) == ["a"]
    assert per_image_files(run_folder) == ["a_images.csv", "a_spots.csv"]
    text = log_text(run_folder)
    assert "Discarded (in progress): b_lost, c_session_ended, d, e_hang" in text
    assert "d: finished" not in text and "f: started" not in text
    assert "A worker process stopped unexpectedly" not in text
    # the message once in the terminal, as its last line, and once in run.log
    assert sum(message in line for line in shown) == 1
    assert shown[-1] == message
    assert text.count(message) == 1
    info = run_info(run_folder, "stopped")
    assert info["message"] == message


def test_worker_stopped_before_an_image_is_handed_out(tmp_path, monkeypatch):
    """The pool is found broken when the next image is handed out: the run starts
    again with fewer workers, and that image stays in the queue and is processed."""
    from concurrent.futures.process import BrokenProcessPool

    handed = {"count": 0}

    class BreaksOnce(batch._WorkerPool):
        def submit(self, function, **arguments):
            handed["count"] += 1
            if handed["count"] == 2:
                raise BrokenProcessPool("a worker stopped")
            return super().submit(function, **arguments)

    monkeypatch.setattr(batch, "_WorkerPool", BreaksOnce)
    folder = tiny_images(tmp_path / "input", ["a", "b", "c"])
    result = run_fake(local_config(folder, tmp_path / "out", workers=2))
    assert result.status == "finished", result.message
    images = read_table(result.run_folder, "images")
    assert list(dict.fromkeys(images["image"])) == ["a", "b", "c"]
    assert (images["status"] == "done").all()
    text = log_text(result.run_folder)
    assert "A worker process stopped unexpectedly" in text
    assert text.count("b: started") == 1
    info = run_info(result.run_folder, "finished")
    [restart] = info["worker_restarts"]
    assert restart["workers"] == 1
    assert "b" not in restart["images_lost"]


def bare_run(tmp_path, names, workers=2):
    """A _Run of small images whose folder is made, and one task per image, each in progress."""
    folder = tiny_images(tmp_path / "input", names)
    config = local_config(folder, tmp_path / "out", workers=workers)
    run_folder = tmp_path / "run"
    (run_folder / "per_image").mkdir(parents=True)
    images = [batch.RunImage(name, f"{name}.tif", folder / f"{name}.tif") for name in names]
    run = batch._Run(config, run_folder, images, None, {}, {}, workers,
                     {"host": None, "port": None, "key": None}, None, fake_process_image, None)
    tasks = [batch._Task(order=order, image=image, label=image.name, function=fake_process_image,
                         arguments={}) for order, image in enumerate(images)]
    for task in tasks:
        (run_folder / "per_image" / f"{task.label}_spots.csv").write_text("image\n", encoding="utf-8")
        run.in_progress.append(task.label)
    return run, tasks


def finished_future(result=None, error=None):
    from concurrent.futures import Future

    future = Future()
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(result)
    return future


class Taken:
    """What restart_pool hands on: results, errors and tasks lost twice, by image."""

    def __init__(self):
        self.results, self.errors, self.lost_twice = [], [], []

    def on_result(self, task, result):
        self.results.append(task.label)

    def on_error(self, task, error):
        self.errors.append((task.label, str(error)))

    def on_lost_twice(self, task):
        self.lost_twice.append(task.label)


@pytest.mark.parametrize("error, message", [
    (outputs.OutputError("disk full"), "Results cannot be written: disk full"),
    (io.OmeroSessionEnded("The OMERO session has ended."), batch.OMERO_SESSION_ENDED_MESSAGE),
])
def test_stop_found_after_a_worker_stopped(tmp_path, error, message):
    """A worker stopped, and a result that came in after the pass was taken says the
    run must stop: the run stops, nothing is tried again and no further result is
    kept; the files of every image not finished are removed."""
    run, (a, b, c, d) = bare_run(tmp_path, ["a", "b", "c", "d"])
    running = {finished_future(error=error): b, finished_future(result={"rows": []}): c}
    taken = Taken()
    pending, stopped = run.restart_pool(running, [a], [d], set(), taken.on_result, taken.on_error,
                                        taken.on_lost_twice)
    assert stopped
    assert run.message == message
    assert (taken.results, taken.errors, taken.lost_twice) == ([], [], [])
    assert run.restarts == []
    assert per_image_files(run.run_folder) == ["d_spots.csv"]
    text = log_text(run.run_folder)
    assert "Discarded (in progress): a, b, c" in text
    assert "A worker process stopped unexpectedly" not in text
    assert "tried once more" not in text


def test_results_that_came_in_after_a_worker_stopped(tmp_path):
    """Results that came in after the pass was taken: a result is kept, an error goes
    to on_error as in the pass and is not tried again; only the lost image is."""
    run, (a, b, c, d) = bare_run(tmp_path, ["a", "b", "c", "d"])
    running = {finished_future(error=RuntimeError("bad pixels")): b,
               finished_future(result={"rows": []}): c}
    taken = Taken()
    pending, stopped = run.restart_pool(running, [a], [d], set(), taken.on_result, taken.on_error,
                                        taken.on_lost_twice)
    assert not stopped
    assert taken.results == ["c"]
    assert taken.errors == [("b", "bad pixels")]
    assert [task.label for task in pending] == ["a", "d"]
    [restart] = run.restarts
    assert restart["images_lost"] == ["a"]
    assert "Lost: a." in log_text(run.run_folder)


def test_worker_numbers_leave_out_images_that_will_be_refused(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    small = np.ones((2, 2, 16, 16), dtype=np.uint16)
    write_image(folder / "a_small.tif", small)
    # larger files that the run will refuse: several time points, and a pixel type
    tifffile.imwrite(folder / "b_timelapse.tif", np.ones((3, 4, 2, 64, 64), dtype=np.uint16), imagej=True,
                     metadata={"axes": "TZCYX"})
    tifffile.imwrite(folder / "c_float.tif", np.ones((4, 2, 64, 64), dtype=np.float32),
                     metadata={"axes": "ZCYX"}, photometric="minisblack")
    config = local_config(folder, tmp_path / "out")
    plan = batch.plan_run(config)
    assert [header is not None for header in plan.headers] == [True, True, True]
    assert batch._largest_channel(config, plan.headers) == 2 * 16 * 16
    assert batch._largest_channel(config, plan.headers, plan.problems) == 2 * 16 * 16
    assert [problem is None for problem in plan.problems] == [True, False, False]
    assert [batch._will_be_refused(config, header) for header in plan.headers] == [False, True, True]
    # an image with more channels or another layout than the run is refused too
    write_image(folder / "d_zyx.tif", np.ones((4, 64, 64), dtype=np.uint16), axes="ZYX")
    assert batch._will_be_refused(config, io.get_image_info(folder / "d_zyx.tif"))
    one_channel = local_config(folder, tmp_path / "out", channels=[{"index": 5}])
    assert batch._will_be_refused(one_channel, io.get_image_info(folder / "a_small.tif"))


def test_worker_numbers_leave_out_colour_images(tmp_path):
    """A colour (RGB) file is refused by the reader, so it does not count when the
    number of workers is worked out, although its shape has as many axes as the layout."""
    folder = tmp_path / "input"
    folder.mkdir()
    write_image(folder / "a_small.tif", np.ones((2, 2, 16, 16), dtype=np.uint16))
    tifffile.imwrite(folder / "b_rgb.tif", np.ones((4, 64, 64, 3), dtype=np.uint8), photometric="rgb")
    config = local_config(folder, tmp_path / "out")
    headers = [io.get_image_info(folder / name) for name in ("a_small.tif", "b_rgb.tif")]
    with pytest.raises(io.ImageReadError, match="colour"):
        io.check_image(folder / "b_rgb.tif", config.image.axes, [0, 1])
    assert [batch._will_be_refused(config, header) for header in headers] == [False, True]
    assert batch._largest_channel(config, headers) == 2 * 16 * 16


def test_total_time_and_duration_are_the_same(tmp_path, monkeypatch):
    """The end steps of a run take time after the summary line; the run record gives
    the same figures as the log."""
    stop = batch._KeepAwake.stop

    def slow_stop(self):
        __import__("time").sleep(2.5)
        stop(self)

    monkeypatch.setattr(batch._KeepAwake, "stop", slow_stop)
    folder = tiny_images(tmp_path / "input", ["a"])
    result = run_fake(local_config(folder, tmp_path / "out"))
    info = run_info(result.run_folder, "finished")
    assert f"Total time {info['duration']}." in log_text(result.run_folder)
    ended = datetime.fromisoformat(info["ended"])
    assert (datetime.now().astimezone() - ended).total_seconds() >= 2


def test_calibration_with_a_lower_limit_marks_raised_images(tmp_path, monkeypatch):
    """From the run to the calibration plot: images whose elbow value is below the
    lower limit are listed with both values and marked as raised in the plot."""
    from bigfish_pypeline import qc

    legends = []
    original = qc.draw_calibration_plot

    def keep(*args, **kwargs):
        figure = original(*args, **kwargs)
        legends.append([text.get_text() for text in figure.axes[0].get_legend().get_texts()])
        return figure

    monkeypatch.setattr(qc, "draw_calibration_plot", keep)
    folder = tmp_path / "input"
    folder.mkdir()
    generated_image(folder / "cal_1.tif", seed=10, amplitude=400)
    generated_image(folder / "cal_2.tif", seed=20, amplitude=800)
    generated_image(folder / "cal_3_blank.tif", blank=True)
    config = local_config(
        folder, tmp_path / "out", workers=2, qc=True,
        channels=[{"index": 0, "threshold": {"mode": "calibrated", "calibration_filter": "cal",
                                             "lower_limit": 5000}},
                  {"index": 1}],
    )
    result = batch.run_batch(config)
    assert result.status == "finished", result.message
    calibration = pd.read_csv(result.run_folder / "calibration.csv", keep_default_na=False)
    assert list(calibration.columns) == outputs.CALIBRATION_COLUMNS
    raised = calibration.iloc[:2]
    assert (raised["auto_threshold"].astype(float) == 5000).all()
    elbow = [batch.calibration_threshold(config, name, folder / f"{name}.tif", 0)["elbow_threshold"]
             for name in ("cal_1", "cal_2")]
    assert list(raised["elbow_threshold"].astype(float)) == elbow
    assert all(value < 5000 for value in elbow)
    assert calibration.loc[2, "elbow_threshold"] == "" and calibration.loc[2, "auto_threshold"] == ""
    [legend] = legends
    assert "Raised to the lower limit (2 images)" in legend
    assert "Value before the lower limit was applied" in legend


def test_label_files_in_the_run_record_and_log(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    for seed, name in enumerate(("a", "b")):
        generated_image(folder / f"{name}.tif", seed=seed)
    labels = tmp_path / "labels"
    labels.mkdir()
    label_image = np.zeros((64, 64), dtype=np.uint16)
    label_image[:10, :10] = 1
    label_image[20:40, 20:40] = 2
    tifffile.imwrite(labels / "a_seglabels.tif", label_image)
    config = with_changes(local_config(folder, tmp_path / "out", workers=2), lambda data: data[
        "segmentation"].update(enabled=True, source="label_files", label_folder=str(labels),
                               drop_border_cells=True))
    result = batch.run_batch(config)
    assert result.status == "finished", result.message
    text = log_text(result.run_folder)
    assert ("a: 2 cells in the label image, 1 kept (1 touching the image border left out, "
            "as `segmentation.drop_border_cells` is on)") in text
    assert "a, channel 0: done, threshold 50, 8 spots, 0 clusters, 1 cell\n" in text
    info = run_info(result.run_folder, "finished")
    [record] = info["files_read"]
    assert record == outputs.file_record(labels / "a_seglabels.tif", "label file")

    # without label files there is nothing to record
    result = run_fake(local_config(folder, tmp_path / "out2"))
    assert run_info(result.run_folder, "finished")["files_read"] == "none"


def test_custom_cellpose_model_in_the_run_record(tmp_path):
    from cellpose_standin import StandInModel

    model_file = tmp_path / "my_model"
    model_file.write_bytes(b"model weights" * 1000)
    folder = tiny_images(tmp_path / "input", ["a"])
    config = with_changes(local_config(folder, tmp_path / "out"), lambda data: data["segmentation"].update(
        enabled=True, source="cellpose", label_folder="", cellpose={"model": str(model_file)}))

    def device(setting):
        return "cpu", "Cellpose runs on the CPU.", []

    def loader(model_name, device, threads=None):
        return StandInModel(n_cells=2)

    result = batch.run_batch(config, image_function=fake_process_image, device_chooser=device,
                             model_loader=loader)
    assert result.status == "finished", result.message
    info = run_info(result.run_folder, "finished")
    assert info["files_read"] == [outputs.file_record(model_file, "Cellpose model")]

    # one of Cellpose's own models gets no entry
    config = with_changes(config, lambda data: data["segmentation"]["cellpose"].update(model="cpsam_v2"))
    result = batch.run_batch(config, image_function=fake_process_image, device_chooser=device,
                             model_loader=loader)
    assert run_info(result.run_folder, "finished")["files_read"] == "none"


def test_custom_cellpose_model_recorded_before_it_is_loaded(tmp_path):
    from cellpose_standin import StandInModel

    model_file = tmp_path / "my_model"
    model_file.write_bytes(b"model weights" * 1000)
    before = outputs.file_record(model_file, "Cellpose model")
    config = with_changes(local_config(tmp_path, tmp_path / "out"), lambda data: data["segmentation"].update(
        enabled=True, source="cellpose", label_folder="", cellpose={"model": str(model_file)}))

    def device(setting):
        return "cpu", "Cellpose runs on the CPU.", []

    def loader(model_name, device, threads=None):
        return StandInModel(n_cells=2)

    # the file is read before the model is loaded: a file that goes while loading is still recorded
    def removing_loader(model_name, device, threads=None):
        model_file.unlink()
        return StandInModel(n_cells=2)

    setup = batch.prepare_cellpose(config, device, removing_loader)
    assert setup.model_file == before
    assert setup.warnings == [
        f"The Cellpose model file {model_file} changed while it was being loaded and can no longer "
        "be read. run_info.yaml records it as it was before loading."
    ]
    model_file.write_bytes(b"model weights" * 1000)

    # an unchanged file gives no warning
    setup = batch.prepare_cellpose(config, device, loader)
    assert setup.model_file == outputs.file_record(model_file, "Cellpose model")
    assert setup.warnings == []

    # a file that changes while it is loaded is recorded again, with a warning
    def changing_loader(model_name, device, threads=None):
        model_file.write_bytes(b"other weights" * 2000)
        return StandInModel(n_cells=2)

    setup = batch.prepare_cellpose(config, device, changing_loader)
    assert setup.model_file == outputs.file_record(model_file, "Cellpose model")
    assert setup.warnings == [
        f"The Cellpose model file {model_file} changed while it was being loaded. run_info.yaml "
        "records it as it was after loading, which may not be the model used."
    ]


def test_images_that_cannot_be_used_fail_on_their_own(tmp_path):
    """Every image is checked from its header at planning. Images that cannot be
    used (another pixel type, a missing channel, a damaged file) fail one by one
    in the run, wherever they are in the list; the run stops before it starts
    only when no image can be used."""
    folder = tmp_path / "input"
    folder.mkdir()
    float_image = np.ones((2, 2, 16, 16), dtype=np.float32)
    tifffile.imwrite(folder / "a_float.tif", float_image, metadata={"axes": "ZCYX"}, photometric="minisblack")
    write_image(folder / "b_one_channel.tif", np.ones((2, 1, 16, 16), dtype=np.uint16))
    damaged = write_image(folder / "c_damaged.tif", np.ones((2, 2, 16, 16), dtype=np.uint16))
    damaged.write_bytes(damaged.read_bytes()[:100])
    write_image(folder / "d.tif", np.ones((2, 2, 16, 16), dtype=np.uint16))
    config = local_config(folder, tmp_path / "out")
    plan = batch.plan_run(config)
    assert [image.name for image in plan.images] == ["a_float", "b_one_channel", "c_damaged", "d"]
    assert plan.problems[0] == io.pixel_type_problem(plan.headers[0])
    assert plan.problems[1].startswith("b_one_channel.tif: ")
    assert plan.problems[2].startswith("c_damaged.tif: ")
    assert plan.problems[3] is None
    assert batch._largest_channel(config, plan.headers, plan.problems) == 2 * 16 * 16

    result = batch.run_batch(config)
    assert result.status == "finished", result.message
    images = read_table(result.run_folder, "images")
    for number, name in enumerate(["a_float", "b_one_channel"]):
        rows = images[images["image"] == name]
        assert list(rows["status"]) == ["failed", "failed"]
        assert set(rows["reason"]) == {plan.problems[number]}
    assert list(images[images["image"] == "c_damaged"]["status"]) == ["failed", "failed"]
    assert "failed" not in set(images[images["image"] == "d"]["status"])

    # settings that fit no image stop the run before it starts
    three = local_config(folder, tmp_path / "out3", channels=[{"index": 0}, {"index": 3}])
    with pytest.raises(batch.BatchError) as raised:
        batch.run_batch(three)
    assert str(raised.value) == (
        f"None of the images can be used with these settings. The first image: {plan.problems[0]}"
    )
    assert not (tmp_path / "out3").exists()

    # no image can be used
    (folder / "d.tif").unlink()
    with pytest.raises(batch.BatchError, match="None of the images can be used with these settings. "
                                               "The first image: a_float.tif: the pixel type is"):
        batch.run_batch(local_config(folder, tmp_path / "out4"))
    assert not (tmp_path / "out4").exists()


def test_each_header_checked_once_when_a_run_is_planned(tmp_path, monkeypatch):
    folder = tiny_images(tmp_path / "input", ["a", "b", "c"])
    checked = []
    check_image = io.check_image

    def counting(path, *arguments, **keywords):
        checked.append(Path(path).name)
        return check_image(path, *arguments, **keywords)

    monkeypatch.setattr(io, "check_image", counting)
    plan = batch.plan_run(local_config(folder, tmp_path / "out", workers="auto"))
    assert plan.problems == [None, None, None]
    assert sorted(checked) == ["a.tif", "b.tif", "c.tif"]


def test_counts_in_the_log(tmp_path):
    assert batch._count_text(1, "cluster") == "1 cluster"
    assert batch._count_text(6, "cluster") == "6 clusters"
    assert batch._count_text(0, "spot") == "0 spots"
    folder = tiny_images(tmp_path / "input", ["a"])
    result = run_fake(local_config(folder, tmp_path / "out"))
    assert "a, channel 0: done, threshold 10, 1 spot, 0 clusters\n" in log_text(result.run_folder)
