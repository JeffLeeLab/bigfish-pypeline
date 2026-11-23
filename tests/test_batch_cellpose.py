"""Tests for batch runs that segment the cells with Cellpose in the main process.

Most tests use stand-ins for the Cellpose model (tests/cellpose_standin.py), so
neither Cellpose's model file nor a GPU is needed. The test marked `cellpose`
uses the real model.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import tifffile

from batch_helpers import fake_process_image
from bigfish_pypeline import batch, cli, io, segmentation
from bigfish_pypeline.config import load_config, save_config
from cellpose_standin import BlockingModel, FailingModel, StandInModel
from conftest import CROP_NAME
from test_batch_run import (
    KEY,
    FakeConn,
    generated_image,
    local_config,
    log_text,
    omero_config,
    omero_info,  # noqa: F401  (fixture)
    progress,
    read_table,
    same_tables,
    tiny_images,
    with_changes,
)

LABELS = batch.LABEL_FOLDER_NAME
TEMPORARY_LABELS = batch.TEMPORARY_LABEL_FOLDER_NAME
CPU_REPORT = "Cellpose runs on the CPU, as set in the config."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cpu_device(setting):
    """Stand-in for segmentation.choose_device: always the CPU, with its warning."""
    return "cpu", CPU_REPORT, [segmentation.CPU_WARNING]


def loader_for(model, loads=None):
    """Stand-in for segmentation.load_cellpose_model that gives `model`."""
    def load(model_name, device, threads=None):
        if loads is not None:
            loads.append({"model_name": model_name, "device": device, "threads": threads})
        return model
    return load


def run_cellpose(config, model, loads=None, **arguments):
    return batch.run_batch(config, device_chooser=cpu_device, model_loader=loader_for(model, loads),
                           **arguments)


def with_cellpose(config, label_images=True, qc=True, **settings):
    """Copy of a config that segments with Cellpose."""
    def change(data):
        data["segmentation"].update(enabled=True, source="cellpose", label_folder="", **settings)
        data["outputs"]["label_images"] = label_images
        data["outputs"]["qc"]["cellpose"] = qc
    return with_changes(config, change)


def label_files(folder):
    folder = Path(folder)
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


def qc_files(run_folder):
    return label_files(run_folder / "qc")


def image_rows(run_folder, name):
    """Rows of the images table for one image, every value read as text."""
    images = pd.read_csv(run_folder / "images.csv", keep_default_na=False, dtype=str)
    return images[images["image"] == name]


# ---------------------------------------------------------------------------
# Test kit with a stand-in model, one and two workers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def kit(crop_config_path, test_kit_folder, tmp_path_factory):
    """The test kit crop and one generated image, set up for Cellpose."""
    folder = tmp_path_factory.mktemp("cellpose_kit_input")
    shutil.copy(test_kit_folder / f"{CROP_NAME}.tif", folder)
    generated_image(folder / "zz_generated.tif", n_channels=3)
    output = tmp_path_factory.mktemp("cellpose_kit_output")

    def change(data):
        data["run"]["input"].update(folder=str(folder), filter="")
        data["run"]["output_folder"] = str(output)

    return with_cellpose(with_changes(load_config(crop_config_path), change))


@pytest.fixture(scope="module")
def kit_runs(kit):
    runs = {}
    for workers in (1, 2):
        model = StandInModel(n_cells=3)
        loads = []
        config = with_changes(kit, lambda data: data["run"].update(workers=workers))
        runs[workers] = (run_cellpose(config, model, loads), model, loads)
    return runs


def test_kit_one_and_two_workers(kit_runs):
    (one, model, loads), (two, _, _) = kit_runs[1], kit_runs[2]
    for result in (one, two):
        assert result.status == "finished", result.message
        folder = result.run_folder
        for name in ("images.csv", "spots.csv", "clusters.csv", "cells.csv"):
            assert (folder / name).is_file(), name
        assert label_files(folder / LABELS) == [f"{CROP_NAME}_seglabels.tif", "zz_generated_seglabels.tif"]
        assert qc_files(folder) == [f"{CROP_NAME}_cellpose_qc.png", "zz_generated_cellpose_qc.png"]
        assert not (folder / TEMPORARY_LABELS).exists()
        assert progress(folder)["status"] == "finished"
        assert progress(folder)["segmenting"] is None
    same_tables(one.run_folder, two.run_folder)

    # the model is loaded once and every image is segmented once, with the config's settings
    assert loads == [{"model_name": "cpsam_v2", "device": "cpu",
                      "threads": batch.cellpose_threads(os.cpu_count())}]
    assert len(model.calls) == 2
    assert model.calls[0]["x"].shape == (384, 384)
    assert model.calls[0]["flow_threshold"] == 0.4 and model.calls[0]["do_3D"] is False

    labels = tifffile.imread(one.run_folder / LABELS / f"{CROP_NAME}_seglabels.tif")
    assert labels.shape == (384, 384) and labels.dtype == np.uint32

    images = read_table(one.run_folder, "images")
    assert list(images["segmentation_source"]) == ["cellpose", "cellpose"]
    assert list(images["segmentation_status"]) == ["done", "done"]
    assert list(images["n_cells"]) == [3, 3]
    cells = read_table(one.run_folder, "cells")
    assert sorted(cells.loc[cells["image"] == CROP_NAME, "cell_id"]) == [1, 2, 3]
    assert (read_table(one.run_folder, "spots")["cell_id"] > 0).any()


def test_kit_labels_reused_as_label_files(kit_runs, tmp_path):
    first = kit_runs[1][0].run_folder
    label_folder = first / LABELS
    config = load_config(first / "run_config.yaml").without_resolved()
    config = with_changes(config, lambda data: (
        data["segmentation"].update(source="label_files", label_folder=str(label_folder)),
        data["run"].update(output_folder=str(tmp_path / "out")),
    ))
    result = batch.run_batch(config)
    assert result.status == "finished", result.message
    second = result.run_folder

    for kind in ("spots", "clusters", "cells"):
        pd.testing.assert_frame_equal(read_table(first, kind), read_table(second, kind))
    images = read_table(second, "images")
    assert list(images["segmentation_source"]) == ["label_files", "label_files"]
    assert list(images["n_cells"]) == list(read_table(first, "images")["n_cells"])

    # label files given by the user are named, not copied
    assert not (second / LABELS).exists()
    assert f"Label folder: {label_folder}" in log_text(second)
    assert load_config(second / "run_config.yaml").segmentation.label_folder == str(label_folder)


def test_kit_without_label_images(kit, kit_runs):
    config = with_cellpose(with_changes(kit, lambda data: data["run"].update(workers=2)), label_images=False)
    result = run_cellpose(config, StandInModel(n_cells=3))
    assert result.status == "finished", result.message
    folder = result.run_folder
    assert not (folder / LABELS).exists()
    assert not (folder / TEMPORARY_LABELS).exists()
    first = kit_runs[1][0].run_folder
    for kind in ("spots", "clusters", "cells"):
        pd.testing.assert_frame_equal(read_table(first, kind), read_table(folder, kind))
    assert "Label images: not kept (`outputs.label_images` is off)" in log_text(folder)


def test_kit_log(kit_runs):
    text = log_text(kit_runs[1][0].run_folder)
    for expected in (
        "Segmentation: Cellpose model cpsam_v2 on channel 0 (max projection | rolling ball 200 px).",
        CPU_REPORT,
        f"Warning: {segmentation.CPU_WARNING}",
        f"it uses {batch.cellpose_threads(os.cpu_count())} processor thread(s).",
        f"Label images: saved in {kit_runs[1][0].run_folder / LABELS}",
        f"{CROP_NAME}: segmenting with Cellpose",
        f"{CROP_NAME}: segmented with Cellpose in ",
        "3 cell(s) (",
        f"{CROP_NAME}, channel 2: done, threshold 18, 692 spots, 6 clusters, 3 cells",
        "Summary: 2 of 2 image(s) finished",
    ):
        assert expected in text, expected
    # each image is segmented before its worker starts
    assert text.index(f"{CROP_NAME}: segmented with") < text.index(f"{CROP_NAME}: started")


# ---------------------------------------------------------------------------
# Cancel during a segmentation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("how, label_images", [("file", True), ("file", False), ("ctrl_c", False)])
def test_cancel_during_segmentation(tmp_path, how, label_images):
    folder = tiny_images(tmp_path / "input", ["a", "b", "c"])
    config = with_cellpose(local_config(folder, tmp_path / "out"), label_images=label_images)
    model = BlockingModel(block_from=2, n_cells=2)
    seen = {}

    # Once `a` has finished, `b` is being segmented and its `eval` is waiting.
    def show(text):
        if text.startswith("Run folder: "):
            seen["run_folder"] = Path(text[len("Run folder: "):])
        if text == "a: finished":
            assert model.waiting.wait(30)
            seen["progress"] = progress(seen["run_folder"])
            seen["cancelled_at"] = time.monotonic()
            if how == "file":
                (seen["run_folder"] / batch.CANCEL_NAME).write_text("", encoding="utf-8")
            else:
                signal.raise_signal(signal.SIGINT)

    try:
        result = run_cellpose(config, model, image_function=fake_process_image, show=show)
        took = time.monotonic() - seen["cancelled_at"]
        assert result.status == "cancelled"
        assert ("Ctrl+C" if how == "ctrl_c" else "cancel") in result.message
        assert took < 5
        assert not model.returned.is_set()  # Cellpose was still busy with `b`
        assert len(model.calls) == 1  # `b` has not returned; `c` was never started
    finally:
        model.release.set()

    run_folder = result.run_folder
    assert seen["progress"]["segmenting"] == "b"
    assert progress(run_folder)["status"] == "cancelled"
    assert progress(run_folder)["segmenting"] is None
    assert list(dict.fromkeys(read_table(run_folder, "images")["image"])) == ["a"]
    text = log_text(run_folder)
    assert "Discarded (in progress): b (being segmented)" in text
    assert "c: segmenting" not in text

    # once Cellpose has finished `b`, nothing of it is written
    assert model.returned.wait(10)
    time.sleep(0.5)
    if label_images:
        assert label_files(run_folder / LABELS) == ["a_seglabels.tif"]
    else:
        assert not (run_folder / LABELS).exists()
    assert not (run_folder / TEMPORARY_LABELS).exists()
    assert qc_files(run_folder) == ["a_cellpose_qc.png"]
    assert sorted(path.name for path in (run_folder / "per_image").iterdir()) == ["a_images.csv", "a_spots.csv"]


def test_progress_written_during_a_long_segmentation(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "PROGRESS_INTERVAL_S", 0.5)
    folder = tiny_images(tmp_path / "input", ["a", "b"])
    config = with_cellpose(local_config(folder, tmp_path / "out"), qc=False)
    model = BlockingModel(block_from=2, n_cells=2)
    seen = {"updates": set()}

    def show(text):
        if text.startswith("Run folder: "):
            seen["run_folder"] = Path(text[len("Run folder: "):])

    # While `b` is segmented, a second thread reads progress.json for 3.5 s, then lets Cellpose go on.
    def watch():
        assert model.waiting.wait(60)
        end = time.monotonic() + 3.5
        while time.monotonic() < end:
            try:
                state = progress(seen["run_folder"])
            except (OSError, json.JSONDecodeError):
                state = {}
            if state.get("segmenting") == "b":
                seen["updates"].add(state["updated"])
            time.sleep(0.1)
        model.release.set()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        result = run_cellpose(config, model, image_function=fake_process_image, show=show)
    finally:
        model.release.set()
        watcher.join(10)
    assert result.status == "finished", result.message
    assert len(seen["updates"]) >= 2  # renewed while `b` was segmented
    assert "b: segmented with Cellpose" in log_text(result.run_folder)
    assert "a: finished" in log_text(result.run_folder)


# ---------------------------------------------------------------------------
# Stopped worker, failures and no cells
# ---------------------------------------------------------------------------


def test_stopped_worker_is_retried_with_its_label_file(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a", "b_crash_once", "c"])
    config = with_cellpose(local_config(folder, tmp_path / "out", workers=2), label_images=False, qc=False)
    model = StandInModel(n_cells=2)
    result = run_cellpose(config, model, image_function=fake_process_image)
    assert result.status == "finished", result.message
    images = read_table(result.run_folder, "images")
    assert list(dict.fromkeys(images["image"])) == ["a", "b_crash_once", "c"]
    assert (images["segmentation_status"] == "done").all()
    assert (images["n_cells"] == 2).all()
    assert len(model.calls) == 3  # not segmented again for the retry
    assert "b_crash_once will be tried once more" in log_text(result.run_folder)
    assert not (result.run_folder / TEMPORARY_LABELS).exists()


@pytest.fixture
def generated_folder(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    for seed, name in enumerate(("a", "b", "c")):
        generated_image(folder / f"{name}.tif", seed=seed)
    return folder


def test_failed_segmentation_keeps_the_spots(generated_folder, tmp_path):
    config = with_cellpose(local_config(generated_folder, tmp_path / "out", workers=2), qc=False)
    model = FailingModel(fail_on=(2,), n_cells=2)
    result = run_cellpose(config, model)
    assert result.status == "finished", result.message
    run_folder = result.run_folder

    failed = image_rows(run_folder, "b")
    reason = "Cellpose could not segment the image (RuntimeError: the stand-in model failed)"
    assert list(failed["status"]) == ["done", "done"]
    assert list(failed["segmentation_source"]) == ["cellpose", "cellpose"]
    assert list(failed["segmentation_status"]) == ["failed", "failed"]
    assert list(failed["n_cells"]) == ["", ""]
    assert all(f"no cell results: segmentation failed: {reason}" in text for text in failed["warnings"])
    for name in ("a", "c"):
        rows = image_rows(run_folder, name)
        assert list(rows["segmentation_status"]) == ["done", "done"]
        assert list(rows["n_cells"]) == ["2", "2"]

    assert "b" in set(read_table(run_folder, "spots")["image"])
    assert "b" not in set(read_table(run_folder, "cells")["image"])
    assert label_files(run_folder / LABELS) == ["a_seglabels.tif", "c_seglabels.tif"]
    text = log_text(run_folder)
    assert f"b: segmentation failed: {reason}" in text
    assert "SegmentationError" not in text.split("Traceback")[0]
    assert "Traceback" in text  # the full details


def test_unreadable_segmentation_channel(generated_folder, tmp_path, monkeypatch):
    read_channel = io.read_channel

    def failing_read(path, layout, channel):
        if Path(path).stem == "c":
            raise io.ImageReadError("c.tif: the pixel data cannot be read (stand-in)")
        return read_channel(path, layout, channel)

    # only the main process is changed: the workers read the FISH channels as usual
    monkeypatch.setattr(batch.io, "read_channel", failing_read)
    config = with_cellpose(local_config(generated_folder, tmp_path / "out"), qc=False)
    result = run_cellpose(config, StandInModel(n_cells=2))
    assert result.status == "finished", result.message
    rows = image_rows(result.run_folder, "c")
    assert list(rows["status"]) == ["done", "done"]
    assert list(rows["segmentation_status"]) == ["failed", "failed"]
    assert "c: segmentation failed: c.tif: the pixel data cannot be read (stand-in)" in log_text(result.run_folder)


def test_no_cells(generated_folder, tmp_path):
    config = with_cellpose(local_config(generated_folder, tmp_path / "out"))
    result = run_cellpose(config, StandInModel(n_cells=0))
    assert result.status == "finished", result.message
    images = pd.read_csv(result.run_folder / "images.csv", keep_default_na=False)
    assert (images["status"] == "done").all()
    assert (images["segmentation_status"] == "done").all()
    assert (images["n_cells"] == 0).all()
    assert images["warnings"].str.contains(segmentation.NO_CELLS_WARNING, regex=False).all()
    assert (read_table(result.run_folder, "spots")["cell_id"] == -1).all()
    cells = result.run_folder / "cells.csv"
    assert not cells.exists() or len(pd.read_csv(cells)) == 0
    assert f"a: warning: {segmentation.NO_CELLS_WARNING}" in log_text(result.run_folder)
    assert "0 cell(s)" in log_text(result.run_folder)


def test_failed_qc_figure_does_not_fail_the_image(generated_folder, tmp_path, monkeypatch):
    from bigfish_pypeline import qc

    def broken(*args, **kwargs):
        raise ValueError("no figure today")

    monkeypatch.setattr(qc, "write_cellpose_qc", broken)
    config = with_cellpose(local_config(generated_folder, tmp_path / "out"))
    result = run_cellpose(config, StandInModel(n_cells=2))
    assert result.status == "finished", result.message
    images = read_table(result.run_folder, "images")
    assert (images["segmentation_status"] == "done").all()
    assert (images["n_cells"] == 2).all()
    warning = "the Cellpose QC figure could not be written: ValueError: no figure today"
    assert f"a: warning: {warning}" in log_text(result.run_folder)
    assert images["warnings"].str.contains(warning, regex=False).all()


# ---------------------------------------------------------------------------
# Problems before processing, `check` and loaded packages
# ---------------------------------------------------------------------------


def test_unknown_model_stops_before_processing(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a"])
    config = with_cellpose(local_config(folder, tmp_path / "out"))
    config = with_changes(config, lambda data: data["segmentation"]["cellpose"].update(model="cpsam_v9"))
    with pytest.raises(batch.BatchError) as raised:
        batch.run_batch(config, device_chooser=cpu_device, image_function=fake_process_image)
    message = str(raised.value)
    assert message.startswith("Unknown Cellpose model 'cpsam_v9'")
    assert "CellposeSetupError" not in message
    assert not (tmp_path / "out").exists()


def test_device_that_does_not_work_stops_before_processing(tmp_path, monkeypatch):
    monkeypatch.setattr(segmentation, "_device_available", lambda name: name == "cpu")
    folder = tiny_images(tmp_path / "input", ["a"])
    config = with_cellpose(local_config(folder, tmp_path / "out"), device="cuda")
    loads = []
    with pytest.raises(batch.BatchError) as raised:
        batch.run_batch(config, model_loader=loader_for(StandInModel(), loads),
                        image_function=fake_process_image)
    assert str(raised.value) == (
        "`device: cuda` is set in the config, but the NVIDIA GPU (cuda) is not available on "
        "this computer. Use `device: auto` or `device: cpu` instead."
    )
    assert loads == []
    assert not (tmp_path / "out").exists()


def test_check_does_not_load_the_model(tmp_path, monkeypatch, capsys):
    def must_not_run(*args, **kwargs):
        raise AssertionError("not to be called by `check`")

    monkeypatch.setattr(segmentation, "choose_device", must_not_run)
    monkeypatch.setattr(segmentation, "load_cellpose_model", must_not_run)
    folder = tiny_images(tmp_path / "input", ["a"])
    settings = tmp_path / "settings.yaml"
    save_config(with_cellpose(local_config(folder, tmp_path / "out")), settings)
    assert cli.main(["check", str(settings)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Cell results: yes, cells found by Cellpose (model cpsam_v2, channel 0, device: auto)" in out
    assert "Label images: saved in `labels/` in the run folder" in out
    assert not (tmp_path / "out").exists()


def test_check_stops_when_the_segmentation_channel_is_missing(tmp_path, capsys):
    folder = tiny_images(tmp_path / "input", ["a"])
    settings = tmp_path / "settings.yaml"
    save_config(with_cellpose(local_config(folder, tmp_path / "out"), channel=7), settings)
    assert cli.main(["check", str(settings)]) == cli.EXIT_PROBLEM
    assert "channel 7 does not exist" in capsys.readouterr().err


def run_script(tmp_path, source, *arguments, timeout=180):
    """Run a Python script in a fresh process; returns its printed output."""
    script = tmp_path / "script.py"
    script.write_text(textwrap.dedent(source), encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).parent)] + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [])
    )
    done = subprocess.run([sys.executable, str(script), *map(str, arguments)], capture_output=True,
                          text=True, timeout=timeout, env=environment, cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def test_cellpose_and_torch_not_loaded_without_cellpose(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    generated_image(folder / "a.tif")
    labels = tmp_path / "labels"
    labels.mkdir()
    tifffile.imwrite(labels / "a_seglabels.tif", np.ones((64, 64), dtype=np.uint16))
    base = local_config(folder, tmp_path / "out")
    save_config(with_cellpose(base), tmp_path / "cellpose.yaml")
    save_config(with_changes(base, lambda data: data["segmentation"].update(
        enabled=True, source="label_files", label_folder=str(labels))), tmp_path / "label_files.yaml")

    output = run_script(tmp_path, """
        import sys
        from bigfish_pypeline import batch, cli
        from bigfish_pypeline.config import load_config

        def loaded():
            return [name for name in ("cellpose", "torch") if name in sys.modules]

        if __name__ == "__main__":
            assert loaded() == [], loaded()
            assert cli.main(["check", "cellpose.yaml"]) == 0
            assert loaded() == [], loaded()
            result = batch.run_batch(load_config("label_files.yaml"))
            assert result.status == "finished", result.message
            assert loaded() == [], loaded()
            print("nothing loaded")
    """)
    assert "nothing loaded" in output


# ---------------------------------------------------------------------------
# Threads and memory
# ---------------------------------------------------------------------------

THREAD_SCRIPT = """
    import json, os, sys, threading, time
    from bigfish_pypeline import batch, segmentation
    from bigfish_pypeline.config import parse_config

    if sys.argv[1] == "variables_first":
        for name in batch.THREAD_VARIABLES:
            os.environ[name] = "1"

    config = parse_config({
        "config_version": 1,
        "image": {"axes": "ZCYX", "voxel_size_nm": {"z": 200, "yx": 65}},
        "channels": [{"index": 1}],
        "segmentation": {"enabled": True, "source": "cellpose", "device": "cpu"},
    })

    def loader(model_name, device, threads=None):
        # the real function, with Cellpose's model class replaced so that no model is read
        from cellpose import models
        models.CellposeModel = lambda **settings: "model"
        return segmentation.load_cellpose_model(model_name, device, threads=threads)

    setup = batch.prepare_cellpose(config, model_loader=loader)
    batch._set_thread_variables()  # as the run does before the workers start
    import torch

    found = {}

    def work():
        found["threads"] = torch.get_num_threads()
        image = torch.randn(1, 32, 512, 512)
        layer = torch.nn.Conv2d(32, 32, 3)
        with torch.no_grad():
            layer(image)
            wall, cpu = time.perf_counter(), time.process_time()
            for _ in range(6):
                layer(image)
            found["cpu_per_wall"] = (time.process_time() - cpu) / (time.perf_counter() - wall)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    found["variables"] = [os.environ[name] for name in batch.THREAD_VARIABLES]
    found["expected"] = setup.threads
    print(json.dumps(found))
"""


@pytest.mark.parametrize("order", ["torch_first", "variables_first"])
def test_cellpose_threads_with_the_worker_variables(tmp_path, order):
    """With the real PyTorch, Cellpose keeps its threads although the thread variables are 1."""
    found = json.loads(run_script(tmp_path, THREAD_SCRIPT, order).strip().splitlines()[-1])
    assert found["variables"] == ["1", "1", "1"]
    assert found["expected"] == batch.cellpose_threads(os.cpu_count())
    assert found["threads"] == found["expected"]
    if found["expected"] >= 2:
        assert found["cpu_per_wall"] > 1.4, found


def test_auto_workers_keep_more_memory_free_with_cellpose():
    channel = 2048 * 2048 * 35
    without = batch.choose_workers("auto", 10, channel, 8, 16e9)
    with_cellpose_on = batch.choose_workers("auto", 10, channel, 8, 16e9, cellpose=True)
    assert without[0] == 2  # (16 − 2) GB ÷ 5.1 GB
    assert with_cellpose_on[0] == 2  # (16 − 5) GB ÷ 5.1 GB
    assert batch.choose_workers("auto", 10, channel, 8, 14e9)[0] == 2
    assert batch.choose_workers("auto", 10, channel, 8, 14e9, cellpose=True)[0] == 1
    assert "for the Cellpose model" in with_cellpose_on[1]
    assert batch.memory_reserve(True) == batch.MEMORY_RESERVE + batch.CELLPOSE_MEMORY_RESERVE
    with pytest.raises(batch.BatchError, match="for the Cellpose model"):
        batch.choose_workers("auto", 10, channel, 8, 4e9, total_memory=9e9, cellpose=True)


def test_workers_auto_uses_the_cellpose_reserve_in_the_log(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(batch.psutil, "virtual_memory", lambda: SimpleNamespace(available=64e9, total=64e9))
    folder = tiny_images(tmp_path / "input", ["a"])
    config = with_cellpose(local_config(folder, tmp_path / "out", workers="auto"), qc=False)
    result = run_cellpose(config, StandInModel(), image_function=fake_process_image)
    assert "kept free (including 3.0 GB for the Cellpose model)" in log_text(result.run_folder)


# ---------------------------------------------------------------------------
# OMERO, with stand-ins for the server
# ---------------------------------------------------------------------------


def lost_connection(image_id):
    """The error io raises when the connection drops while an OMERO image is read."""
    reason = f"ConnectionLostException: session {KEY}"
    error = io.OmeroConnectionLost(f"OMERO image {image_id}: lost the connection to OMERO ({reason})")
    error.reason = reason
    return error


def segmentation_reads(monkeypatch, drops=(), ended_after=None, output=None):
    """Stand-ins for reading the segmentation channel in the main process.

    drops: image IDs whose first read finds the connection dropped.
    ended_after: an image ID; reading it waits for the image before it to finish,
        then finds that the session has ended.
    Returns (reads, joined, detached): the (connection, image ID) of each read, the
    connections made by rejoining, and the connections let go.
    """
    reads, joined, detached = [], [], []
    dropped = set()

    def read_omero_channels(conn, image_id, layout, channels):
        reads.append((conn, image_id))
        if image_id == ended_after:
            deadline = time.monotonic() + 60
            while not list(output.glob(f"*/per_image/{image_id - 1}_*_images.csv")) and time.monotonic() < deadline:
                time.sleep(0.05)
            raise io.OmeroSessionEnded("The OMERO session has ended.")
        if image_id in drops and image_id not in dropped:
            dropped.add(image_id)
            raise lost_connection(image_id)
        return {channels[0]: np.ones((2, 16, 16), dtype=np.uint16)}

    def join_session(host, port, key):
        joined.append(FakeConn([]))
        return joined[-1]

    monkeypatch.setattr(io, "read_omero_channels", read_omero_channels)
    monkeypatch.setattr(io, "join_session", join_session)
    monkeypatch.setattr(io, "detach_session", detached.append)
    return reads, joined, detached


def test_omero_segmentation_channel_read_by_the_main_process(tmp_path, omero_info, monkeypatch):  # noqa: F811
    conn = FakeConn([(1, "a.tif"), (2, "b.tif"), (3, "c.tif")])
    reads, joined, detached = segmentation_reads(monkeypatch, drops=[2])
    config = with_cellpose(omero_config(tmp_path / "out", image_ids=[1, 2, 3]))
    result = run_cellpose(config, StandInModel(n_cells=2), omero_conn=conn, image_function=fake_process_image)
    assert result.status == "finished", result.message
    # the connection drops while image 2 is read: the session is rejoined once,
    # and image 3 is read with the new connection
    [rejoined] = joined
    assert reads == [(conn, 1), (conn, 2), (rejoined, 2), (rejoined, 3)]
    assert detached == [conn, rejoined]
    assert not conn.closed and not rejoined.closed
    images = read_table(result.run_folder, "images")
    assert (images["segmentation_status"] == "done").all()
    assert label_files(result.run_folder / LABELS) == ["1_a_seglabels.tif", "2_b_seglabels.tif", "3_c_seglabels.tif"]
    assert ("2_b: OMERO image 2: lost the connection to OMERO (ConnectionLostException: session [hidden]); "
            "rejoining the session and trying again") in log_text(result.run_folder)
    for path in result.run_folder.rglob("*"):
        if path.is_file() and path.suffix in (".csv", ".log", ".json", ".yaml"):
            assert KEY not in path.read_text(encoding="utf-8"), path.name


def test_omero_session_of_the_run_ended_after_a_rejoin(tmp_path, omero_info, monkeypatch):  # noqa: F811
    conn = FakeConn([(1, "a.tif"), (2, "b.tif")])
    monkeypatch.setattr(batch, "_log_in_to_omero", lambda config: conn)
    _, joined, detached = segmentation_reads(monkeypatch, drops=[1])
    config = with_cellpose(omero_config(tmp_path / "out", image_ids=[1, 2]))
    result = run_cellpose(config, StandInModel(n_cells=2), image_function=fake_process_image)
    assert result.status == "finished", result.message
    [rejoined] = joined
    # the run logged in, so it ends the session, through the connection it rejoined with
    assert detached == [conn]
    assert rejoined.closed


def test_omero_segmentation_read_twice_lost(tmp_path, omero_info, monkeypatch):  # noqa: F811
    conn = FakeConn([(1, "a.tif"), (2, "b.tif")])
    _, joined, _ = segmentation_reads(monkeypatch, drops=[1])
    first_read = io.read_omero_channels

    def read_omero_channels(read_conn, image_id, layout, channels):
        # the rejoined connection drops too while image 1 is read
        if read_conn is not conn and image_id == 1:
            raise lost_connection(image_id)
        return first_read(read_conn, image_id, layout, channels)

    monkeypatch.setattr(io, "read_omero_channels", read_omero_channels)
    config = with_cellpose(omero_config(tmp_path / "out", image_ids=[1, 2]))
    result = run_cellpose(config, StandInModel(n_cells=2), omero_conn=conn, image_function=fake_process_image)
    assert result.status == "finished", result.message
    images = read_table(result.run_folder, "images")
    status = images.groupby("image")["segmentation_status"].agg(set).to_dict()
    assert status == {"1_a": {"failed"}, "2_b": {"done"}}
    assert len(joined) == 1
    text = log_text(result.run_folder)
    assert ("1_a: segmentation failed: OMERO image 1: lost the connection to OMERO twice "
            "(ConnectionLostException: session [hidden])") in text
    assert KEY not in text


def test_omero_session_ended_during_segmentation(tmp_path, omero_info, monkeypatch):  # noqa: F811
    conn = FakeConn([(1, "a.tif"), (2, "b.tif"), (3, "c.tif")])
    output = tmp_path / "out"
    segmentation_reads(monkeypatch, ended_after=2, output=output)
    config = with_changes(with_cellpose(omero_config(output, image_ids=[1, 2, 3])),
                          lambda data: data["run"].update(workers=1))
    result = run_cellpose(config, StandInModel(n_cells=2), omero_conn=conn, image_function=fake_process_image)
    assert result.status == "stopped"
    assert "Log in again" in result.message
    assert list(dict.fromkeys(read_table(result.run_folder, "images")["image"])) == ["1_a"]
    assert label_files(result.run_folder / LABELS) == ["1_a_seglabels.tif"]
    assert "3_c: segmenting" not in log_text(result.run_folder)


def test_omero_session_ended_when_rejoining_for_segmentation(tmp_path, omero_info, monkeypatch):  # noqa: F811
    conn = FakeConn([(1, "a.tif"), (2, "b.tif")])
    segmentation_reads(monkeypatch, drops=[1])

    def ended(host, port, key):
        raise io.OmeroSessionEnded("The OMERO session has ended.")

    monkeypatch.setattr(io, "join_session", ended)
    config = with_cellpose(omero_config(tmp_path / "out", image_ids=[1, 2]))
    result = run_cellpose(config, StandInModel(n_cells=2), omero_conn=conn, image_function=fake_process_image)
    assert result.status == "stopped"
    assert "Log in again" in result.message
    assert not (result.run_folder / "per_image" / "1_a_images.csv").exists()


# ---------------------------------------------------------------------------
# The real Cellpose model
# ---------------------------------------------------------------------------


@pytest.mark.cellpose
def test_kit_with_the_real_model(kit, tmp_path):
    config = with_changes(kit, lambda data: (
        data["run"]["input"].update(filter=CROP_NAME),
        data["run"].update(output_folder=str(tmp_path / "out")),
    ))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = batch.run_batch(config)
    assert result.status == "finished", result.message
    run_folder = result.run_folder

    labels = tifffile.imread(run_folder / LABELS / f"{CROP_NAME}_seglabels.tif")
    assert labels.shape == (384, 384)
    assert labels.dtype == np.uint32
    assert qc_files(run_folder) == [f"{CROP_NAME}_cellpose_qc.png"]
    for name in ("images.csv", "spots.csv", "clusters.csv", "cells.csv"):
        assert (run_folder / name).is_file(), name
    images = read_table(run_folder, "images")
    assert list(images["segmentation_source"]) == ["cellpose"]
    assert list(images["segmentation_status"]) == ["done"]

    text = log_text(run_folder)
    assert "Segmentation: Cellpose model cpsam_v2 on channel 0" in text
    assert "Cellpose runs on " in text
    assert f"{CROP_NAME}: segmented with Cellpose in " in text
    assert not [warning for warning in caught if "Sparse invariant checks" in str(warning.message)]
