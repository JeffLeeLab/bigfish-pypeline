"""Tests for batch.run_batch: whole batch runs in a pool of worker processes."""

import json
import os
import shutil
import signal
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import tifffile

from batch_helpers import fake_process_image
from bigfish_pypeline import batch, io
from bigfish_pypeline.config import load_config, parse_config
from conftest import CROP_NAME
from synthetic import make_image

KEY = "1b2c3d4e-0000-1111-2222-333344445555"


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


def local_config(input_folder, output_folder, workers=1, channels=None, **run_settings):
    """Config for generated images: top-hat background, manual threshold 50."""
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


def test_kit_log(kit_runs):
    text = log_text(kit_runs[1].run_folder)
    for expected in (
        "Input folder:",
        f"  {CROP_NAME}.tif",
        f"{CROP_NAME}: started",
        f"{CROP_NAME}, channel 2: done, threshold 18, 692 spots, 6 clusters, 44 cells",
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


# ---------------------------------------------------------------------------
# Calibrated thresholds
# ---------------------------------------------------------------------------


def calibrated_config(folder, output, filter_text="cal"):
    return local_config(
        folder, output, workers=2,
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


def test_repeat_calibrated_run(calibrated_run, tmp_path):
    folder, _, first = calibrated_run
    config = load_config(first.run_folder / "run_config.yaml")
    result = batch.run_batch(config)
    assert result.status == "finished"
    assert not (result.run_folder / "calibration.csv").exists()
    assert "from the config (not calibrated again)" in log_text(result.run_folder)
    assert "(calibration): started" not in log_text(result.run_folder)
    same_tables(first.run_folder, result.run_folder)

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
    assert n == 2  # (16 − 2) GB ÷ 5.1 GB
    assert warning is None
    assert "chosen automatically" in reason and "5.1 GB per worker" in reason
    assert batch.choose_workers("auto", 10, 100, 4, 64e9)[0] == 3  # cores − 1
    assert batch.choose_workers("auto", 2, 100, 16, 64e9)[0] == 2  # number of images
    assert batch.choose_workers("auto", 10, 100, 1, 64e9)[0] == 1  # one core
    assert batch.choose_workers("auto", 10, 100, None, 64e9)[0] == 1
    assert batch.choose_workers("auto", 10, 100, 16, 3.6e9)[0] == 3  # 0.5 GB floor
    assert batch.memory_per_worker(100) == batch.MIN_MEMORY_PER_WORKER
    assert batch.memory_per_worker(FULL_CHANNEL) == 35 * FULL_CHANNEL


def test_auto_workers_not_enough_memory():
    with pytest.raises(batch.BatchError, match="not enough memory for one worker"):
        batch.choose_workers("auto", 10, FULL_CHANNEL, 8, 6e9)
    with pytest.raises(batch.BatchError, match="not enough memory"):
        batch.choose_workers("auto", 10, 100, 8, 2.2e9)


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
    monkeypatch.setattr(batch.psutil, "virtual_memory", lambda: SimpleNamespace(available=1e9))
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


def test_worker_stopped_with_one_worker(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a", "b_crash_always", "c"])
    result = run_fake(local_config(folder, tmp_path / "out", workers=1))
    assert result.status == "stopped"
    assert "only one worker" in result.message
    assert list(dict.fromkeys(read_table(result.run_folder, "images")["image"])) == ["a"]
    assert per_image_files(result.run_folder) == ["a_images.csv", "a_spots.csv"]
    assert progress(result.run_folder)["status"] == "stopped"
    assert "A worker process stopped unexpectedly" in log_text(result.run_folder)


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


def test_cellpose_not_available(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a"])
    config = with_changes(local_config(folder, tmp_path / "out"),
                          lambda data: data["segmentation"].update(enabled=True, source="cellpose"))
    with pytest.raises(batch.BatchError, match="Cellpose is not available yet"):
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
    assert list(dict.fromkeys(images["image"])) == ["123_a_1.tif", "124_b.tif", "125_c key_in_error.tif"]
    failed = images[images["image"] == "125_c key_in_error.tif"]
    assert (failed["status"] == "failed").all()
    assert "[hidden]" in failed["reason"].iloc[0]
    assert "read with session [hidden] from omero.example" in log_text(result.run_folder)

    run_config = load_config(result.run_folder / "run_config.yaml")
    assert run_config.resolved.images == ["123_a_1.tif", "124_b.tif", "125_c key_in_error.tif"]
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
    assert list(dict.fromkeys(read_table(result.run_folder, "images")["image"])) == ["1_a.tif"]
    assert "3_c.tif: started" not in log_text(result.run_folder)


def test_omero_needs_dataset_or_images(tmp_path):
    with pytest.raises(batch.BatchError, match="dataset ID or image IDs"):
        run_fake(omero_config(tmp_path / "out"), omero_conn=FakeConn([]))
