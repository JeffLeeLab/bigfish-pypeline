"""End-to-end tests of runs that segment the cells with Cellpose.

The first two tests start `bigfish-pypeline batch` as a separate process with the real
Cellpose model, the way a user would (marked `cellpose`: skipped when the model file
is missing; the model is never downloaded). The others run the batch runner in the
test process on generated images, with a stand-in for the Cellpose model and the
real pipeline for the spots. Everything is written under pytest's temporary folders.
"""

import re
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import pytest
import tifffile
import yaml

from bigfish_pypeline import batch, segmentation
from bigfish_pypeline.config import load_config
from cellpose_standin import StandInModel
from conftest import CROP_NAME, TEST_DATA
from synthetic import make_image
from test_batch_cellpose import (
    LABELS,
    TEMPORARY_LABELS,
    image_rows,
    label_files,
    qc_files as all_qc_files,
    run_cellpose,
    with_cellpose,
)
from test_batch_run import generated_image, local_config, log_text, progress, read_table, with_changes, write_image
from test_end_to_end import batch as start_batch
from test_end_to_end import sorted_tables_equal

def qc_files(run_folder):
    """The Cellpose QC figures in the run's `qc/` folder."""
    return [name for name in all_qc_files(run_folder) if name.endswith("_cellpose_qc.png")]


DEVICE_LINE = re.compile(r"Cellpose runs on (the Apple GPU \(mps\)|the NVIDIA GPU \(cuda\)|the CPU)")


# ---------------------------------------------------------------------------
# Checks used by several tests
# ---------------------------------------------------------------------------


def read_labels(run_folder, name):
    return tifffile.imread(run_folder / LABELS / f"{name}_seglabels.tif")


def check_label_image(labels, shape_yx):
    """A label image is 2D, holds whole numbers of 0 or more, and has the image's Y x X size."""
    assert labels.shape == tuple(shape_yx)
    assert labels.dtype.kind in "ui"
    assert labels.min() >= 0


def check_cells_agree_with_labels(run_folder, name, labels):
    """The tables of one image describe the cells of its label file."""
    ids = sorted(int(label) for label in np.unique(labels) if label > 0)
    images = read_table(run_folder, "images")
    assert (images.loc[images["image"] == name, "n_cells"] == len(ids)).all(), name
    cells = read_table(run_folder, "cells")
    cells = cells[cells["image"] == name]
    for _, rows in cells.groupby("channel"):
        assert sorted(rows["cell_id"]) == ids, name


def check_spots_agree_with_labels(run_folder, name, labels):
    """Every spot carries the label found at its pixel position, or -1 outside the cells."""
    spots = read_table(run_folder, "spots")
    spots = spots[spots["image"] == name]
    rows = np.clip(np.rint(spots["y_px"]).astype(int), 0, labels.shape[0] - 1)
    columns = np.clip(np.rint(spots["x_px"]).astype(int), 0, labels.shape[1] - 1)
    found = labels[rows, columns].astype(int)
    np.testing.assert_array_equal(spots["cell_id"], np.where(found > 0, found, -1), err_msg=name)


def worker_processes():
    """Worker processes of the batch runner that are still running."""
    found = []
    for child in psutil.Process().children(recursive=True):
        try:
            if "spawn_main" in " ".join(child.cmdline()) and child.status() != psutil.STATUS_ZOMBIE:
                found.append(child)
        except psutil.Error:
            pass
    return found


def check_no_worker_left():
    end = time.monotonic() + 15
    while worker_processes() and time.monotonic() < end:
        time.sleep(0.05)
    assert worker_processes() == []


# ---------------------------------------------------------------------------
# The real command with the real model
# ---------------------------------------------------------------------------


def kit_settings(tmp_path, device):
    """Settings of the test kit crop with Cellpose in place of its label file."""
    folder = tmp_path / "input"
    folder.mkdir()
    shutil.copy(TEST_DATA / f"{CROP_NAME}.tif", folder)
    data = yaml.safe_load((TEST_DATA / f"{CROP_NAME}_config.yaml").read_text(encoding="utf-8"))
    data["run"]["input"]["folder"] = str(folder)
    data["run"]["output_folder"] = str(tmp_path / "out")
    data["segmentation"].update(source="cellpose", label_folder="", device=device)
    data["outputs"]["qc"].update(elbow_plot=False, detection=False, reference_spot=False, final="none")
    settings = tmp_path / "settings.yaml"
    settings.write_text(yaml.safe_dump(data), encoding="utf-8")
    return settings


def check_real_run(command, code, run_folder):
    """What a run of the crop with the real model must show, whatever the cells found."""
    assert code == 0, command.describe()
    assert run_folder is not None, command.describe()
    for kind in ("images", "spots", "clusters", "cells"):
        assert (run_folder / f"{kind}.csv").is_file(), kind

    with tifffile.TiffFile(TEST_DATA / f"{CROP_NAME}.tif") as image:
        shape_yx = image.series[0].shape[-2:]
    labels = read_labels(run_folder, CROP_NAME)
    check_label_image(labels, shape_yx)
    check_cells_agree_with_labels(run_folder, CROP_NAME, labels)
    assert qc_files(run_folder) == [f"{CROP_NAME}_cellpose_qc.png"]
    assert not (run_folder / TEMPORARY_LABELS).exists()

    images = read_table(run_folder, "images")
    assert list(images["status"]) == ["done"]
    assert list(images["segmentation_source"]) == ["cellpose"]
    assert list(images["segmentation_status"]) == ["done"]
    assert progress(run_folder)["status"] == "finished"
    return log_text(run_folder)


@pytest.mark.cellpose
def test_command_on_the_test_kit_with_cellpose(tmp_path):
    command, code, run_folder = start_batch([kit_settings(tmp_path, "auto")], tmp_path)
    text = check_real_run(command, code, run_folder)
    assert "Cellpose model cpsam_v2" in text
    assert DEVICE_LINE.search(text), text
    assert command.out.splitlines()[-1] == f"Run folder: {run_folder}"


@pytest.mark.cellpose
def test_command_on_the_cpu_goes_on_with_a_warning(tmp_path):
    command, code, run_folder = start_batch([kit_settings(tmp_path, "cpu")], tmp_path)
    text = check_real_run(command, code, run_folder)
    assert "Cellpose runs on the CPU, as set in the config." in text
    assert f"Warning: {segmentation.CPU_WARNING}" in text


# ---------------------------------------------------------------------------
# Stand-in models
# ---------------------------------------------------------------------------


class ScriptedModel(StandInModel):
    """A stand-in model that treats its images in order as `script` says.

    Each step is a number of cells to find, or an error to raise.
    """

    def __init__(self, script):
        super().__init__()
        self.script = list(script)

    def eval(self, x, **settings):
        step = self.script[len(self.calls)]
        if isinstance(step, Exception):
            self.calls.append({"x": x, **settings})
            raise step
        self.n_cells = step
        return super().eval(x, **settings)


# ---------------------------------------------------------------------------
# Different image sizes in one batch, and repeating the run
# ---------------------------------------------------------------------------

SIZES = {"a_small": (8, 64, 64), "b_wide": (10, 80, 128), "c_tall": (12, 128, 72)}


@pytest.fixture(scope="module")
def sizes_run(tmp_path_factory):
    """Three images of different sizes, run with two workers and a model that finds three cells."""
    base = tmp_path_factory.mktemp("cellpose_sizes")
    folder = base / "input"
    folder.mkdir()
    for number, (name, shape) in enumerate(SIZES.items()):
        generated_image(folder / f"{name}.tif", shape=shape, seed=number)
    config = with_cellpose(local_config(folder, base / "out", workers=2))
    model = StandInModel(n_cells=3)
    return run_cellpose(config, model), model, base


def test_different_sizes_in_one_batch(sizes_run):
    result, model, _ = sizes_run
    assert result.status == "finished", result.message
    run_folder = result.run_folder
    assert label_files(run_folder / LABELS) == [f"{name}_seglabels.tif" for name in SIZES]
    assert qc_files(run_folder) == [f"{name}_cellpose_qc.png" for name in SIZES]
    assert [call["x"].shape for call in model.calls] == [shape[1:] for shape in SIZES.values()]

    images = read_table(run_folder, "images")
    assert list(images["status"]) == ["done"] * 6
    assert list(images["segmentation_status"]) == ["done"] * 6
    for name, shape in SIZES.items():
        labels = read_labels(run_folder, name)
        check_label_image(labels, shape[1:])
        assert len(np.unique(labels)) == 4
        check_cells_agree_with_labels(run_folder, name, labels)
        check_spots_agree_with_labels(run_folder, name, labels)
    spots = read_table(run_folder, "spots")
    assert set(spots["image"]) == set(SIZES)
    assert (spots["cell_id"] > 0).any()
    assert "Summary: 3 of 3 image(s) finished" in log_text(run_folder)


def test_repeat_from_the_run_config(sizes_run, tmp_path):
    first, _, _ = sizes_run
    config = load_config(first.run_folder / "run_config.yaml")
    config = with_changes(config, lambda data: data["run"].update(output_folder=str(tmp_path / "again")))
    second = run_cellpose(config, StandInModel(n_cells=3))
    assert second.status == "finished", second.message
    assert second.run_folder != first.run_folder
    sorted_tables_equal(first.run_folder, second.run_folder)
    for name in SIZES:
        np.testing.assert_array_equal(read_labels(first.run_folder, name), read_labels(second.run_folder, name))


def test_labels_of_the_first_run_used_as_label_files(sizes_run, tmp_path):
    first, _, _ = sizes_run
    config = load_config(first.run_folder / "run_config.yaml").without_resolved()
    config = with_changes(config, lambda data: (
        data["segmentation"].update(source="label_files", label_folder=str(first.run_folder / LABELS)),
        data["run"].update(output_folder=str(tmp_path / "out")),
    ))
    second = batch.run_batch(config)
    assert second.status == "finished", second.message
    for kind in ("spots", "clusters", "cells"):
        pd.testing.assert_frame_equal(read_table(first.run_folder, kind), read_table(second.run_folder, kind))
    images = read_table(second.run_folder, "images")
    assert list(images["segmentation_source"]) == ["label_files"] * 6
    assert list(images["n_cells"]) == list(read_table(first.run_folder, "images")["n_cells"])
    assert not (second.run_folder / LABELS).exists()


# ---------------------------------------------------------------------------
# Two-dimensional images
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("axes", ["YX", "CYX"])
def test_two_dimensional_images(tmp_path, axes):
    folder = tmp_path / "input"
    folder.mkdir()
    shape = (96, 80)
    for number, name in enumerate(("flat_1", "flat_2")):
        planes = [make_image(shape, n_spots=12, seed=number + 10 * channel)[0] for channel in range(2)]
        write_image(folder / f"{name}.tif", planes[0] if axes == "YX" else np.stack(planes), axes)
    channels = [{"index": 0}] if axes == "YX" else [{"index": 0}, {"index": 1}]
    config = with_changes(
        with_cellpose(local_config(folder, tmp_path / "out", channels=channels)),
        lambda data: data["image"].update(axes=axes, voxel_size_nm={"yx": 65}),
    )
    model = StandInModel(n_cells=3)
    result = run_cellpose(config, model)
    assert result.status == "finished", result.message
    run_folder = result.run_folder

    assert [call["x"].shape for call in model.calls] == [shape, shape]
    images = read_table(run_folder, "images")
    assert list(images["status"]) == ["done"] * len(images)
    assert list(images["segmentation_status"]) == ["done"] * len(images)
    for name in ("flat_1", "flat_2"):
        labels = read_labels(run_folder, name)
        check_label_image(labels, shape)
        check_cells_agree_with_labels(run_folder, name, labels)
        check_spots_agree_with_labels(run_folder, name, labels)
    for kind in ("spots", "clusters", "cells", "images"):
        table = read_table(run_folder, kind)
        assert not [column for column in table.columns if column.startswith("z_")], kind
    assert len(read_table(run_folder, "spots")) > 0
    assert qc_files(run_folder) == ["flat_1_cellpose_qc.png", "flat_2_cellpose_qc.png"]


# ---------------------------------------------------------------------------
# No cells in one image and a failing segmentation in another
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label_images", [True, False])
def test_no_cells_and_a_failed_segmentation_in_one_batch(tmp_path, label_images):
    folder = tmp_path / "input"
    folder.mkdir()
    names = ["a_cells", "b_no_cells", "c_fails", "d_cells"]
    for number, name in enumerate(names):
        generated_image(folder / f"{name}.tif", seed=number)
    config = with_cellpose(local_config(folder, tmp_path / "out", workers=2), label_images=label_images)
    error = RuntimeError("the stand-in model failed")
    model = ScriptedModel([2, 0, error, 2])
    result = run_cellpose(config, model)
    assert result.status == "finished", result.message
    run_folder = result.run_folder
    assert len(model.calls) == 4

    # every image keeps its spots; only the segmentation status differs
    images = pd.read_csv(run_folder / "images.csv", keep_default_na=False, dtype=str)
    assert list(images["image"]) == [name for name in names for _ in range(2)]
    assert list(images["status"]) == ["done"] * 8
    for name, status, n_cells in (("a_cells", "done", "2"), ("b_no_cells", "done", "0"),
                                  ("c_fails", "failed", ""), ("d_cells", "done", "2")):
        rows = image_rows(run_folder, name)
        assert list(rows["segmentation_source"]) == ["cellpose"] * 2, name
        assert list(rows["segmentation_status"]) == [status] * 2, name
        assert list(rows["n_cells"]) == [n_cells] * 2, name
    no_cells = image_rows(run_folder, "b_no_cells")
    assert all(segmentation.NO_CELLS_WARNING in text for text in no_cells["warnings"])
    reason = "Cellpose could not segment the image (RuntimeError: the stand-in model failed)"
    failed = image_rows(run_folder, "c_fails")
    assert all(f"no cell results: segmentation failed: {reason}" in text for text in failed["warnings"])
    for name in ("a_cells", "d_cells"):
        assert not image_rows(run_folder, name)["warnings"].str.contains("no cell results").any(), name

    spots = read_table(run_folder, "spots")
    assert set(spots["image"]) == set(names)
    assert (spots.loc[spots["image"].isin(["b_no_cells", "c_fails"]), "cell_id"] == -1).all()
    assert (spots.loc[spots["image"].isin(["a_cells", "d_cells"]), "cell_id"] > 0).any()
    cells = read_table(run_folder, "cells")
    assert list(dict.fromkeys(cells["image"])) == ["a_cells", "d_cells"]
    assert (cells.groupby(["image", "channel"]).size() == 2).all()

    text = log_text(run_folder)
    assert f"b_no_cells: warning: {segmentation.NO_CELLS_WARNING}" in text
    assert f"c_fails: segmentation failed: {reason}" in text
    assert "Summary: 4 of 4 image(s) finished" in text

    # label files and figures: none for the image that failed, whether or not the labels are kept
    assert qc_files(run_folder) == ["a_cells_cellpose_qc.png", "b_no_cells_cellpose_qc.png", "d_cells_cellpose_qc.png"]
    assert not (run_folder / TEMPORARY_LABELS).exists()
    if label_images:
        assert label_files(run_folder / LABELS) == [
            "a_cells_seglabels.tif", "b_no_cells_seglabels.tif", "d_cells_seglabels.tif"]
        assert read_labels(run_folder, "b_no_cells").max() == 0
    else:
        assert not (run_folder / LABELS).exists()


# ---------------------------------------------------------------------------
# A cancelled run
# ---------------------------------------------------------------------------

N_SLOW_IMAGES = 6


@pytest.mark.parametrize("label_images", [True, False])
def test_cancelled_run_keeps_finished_images_only(tmp_path, label_images):
    folder = tmp_path / "input"
    folder.mkdir()
    for number in range(N_SLOW_IMAGES):
        generated_image(folder / f"img_{number:02d}.tif", shape=(16, 384, 384), seed=number)
    config = with_cellpose(local_config(folder, tmp_path / "out"), label_images=label_images)
    seen = {}

    # The first image has finished: cancel while the next ones are being worked on.
    def show(text):
        if text.startswith("Run folder: "):
            seen["run_folder"] = Path(text[len("Run folder: "):])
        if text == "img_00: finished":
            (seen["run_folder"] / batch.CANCEL_NAME).write_text("", encoding="utf-8")

    result = run_cellpose(config, StandInModel(n_cells=3), show=show)
    assert result.status == "cancelled", result.message
    run_folder = result.run_folder
    assert progress(run_folder)["status"] == "cancelled"

    done = sorted(path.name[: -len("_images.csv")] for path in (run_folder / "per_image").glob("*_images.csv"))
    assert 1 <= len(done) < N_SLOW_IMAGES
    assert done[0] == "img_00"
    for kind in ("images", "spots", "cells"):
        assert list(dict.fromkeys(read_table(run_folder, kind)["image"])) == done, kind

    assert not list(run_folder.rglob("*.tmp"))
    assert not (run_folder / TEMPORARY_LABELS).exists()
    assert qc_files(run_folder) == [f"{name}_cellpose_qc.png" for name in done]
    if label_images:
        assert label_files(run_folder / LABELS) == [f"{name}_seglabels.tif" for name in done]
    else:
        assert not (run_folder / LABELS).exists()
    per_image = {path.name for path in (run_folder / "per_image").iterdir()}
    assert {name for name in per_image if name.endswith("_images.csv")} == {f"{name}_images.csv" for name in done}
    assert all(name.split("_")[0] == "img" and name[:6] in done for name in per_image)
    check_no_worker_left()
