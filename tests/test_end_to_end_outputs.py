"""End-to-end tests of the files a run writes: the run record, the `.npz` files, the QC images and keep-awake.

Most tests start `bigfish-pypeline batch` as a separate process, as a user would, with the
real pipeline, and look at the files of the run folder. The run with Cellpose uses a stand-in
for the model and so runs in the test process. Everything is written under pytest's
temporary folders, and no test leaves a worker or a `caffeinate` process behind.
"""

import copy
import re
import shutil
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import psutil
import pytest
import tifffile
import yaml
from PIL import Image

from bigfish_pypeline import cli
from bigfish_pypeline.config import load_config
from cellpose_standin import StandInModel
from conftest import CROP_NAME, TEST_DATA
from test_batch_cellpose import LABELS, run_cellpose, with_cellpose
from test_batch_run import generated_image, run_info, with_changes
from test_end_to_end import (
    batch as run_command_batch,
    channel_settings,
    check_last_lines,
    finished_images,
    image_names,
    log_text,
    progress,
    read_table,
    running,
    sorted_tables_equal,
    spots_stack,
    wait_until,
    wait_until_gone,
    write_settings,
    write_tif,
)
from test_end_to_end_cellpose import check_no_worker_left
from test_keep_awake import KEPT_AWAKE_LINE
from test_qc import _page_data

QC_KINDS = ("detection.png", "elbow.png", "final.png", "referencespot.tif")
ON = {"elbow_plot": True, "detection": True, "reference_spot": True, "cellpose": True}
OFF = {"elbow_plot": False, "detection": False, "reference_spot": False, "cellpose": False, "final": "none"}

# What a run with label files and no calibration leaves in its folder (spec 8.1).
RUN_FILES = {
    "run_config.yaml", "run_info.yaml", "run.log", "progress.json",
    "images.csv", "spots.csv", "clusters.csv", "cells.csv", "per_image", "qc", "npz",
}


# ---------------------------------------------------------------------------
# Settings and checks used by several tests
# ---------------------------------------------------------------------------


def every_output(final="png"):
    """The `outputs` block with the `.npz` files and every QC image on."""
    return {"label_images": True, "npz": True, "qc": {**ON, "final": final}}


def no_output():
    """The `outputs` block with the `.npz` files and every QC image off."""
    return {"label_images": True, "npz": False, "qc": dict(OFF)}


def kit_settings(path, outputs):
    """A copy of the test kit's config, with the kit's folder named in full, and the given `outputs`."""
    data = yaml.safe_load((TEST_DATA / f"{CROP_NAME}_config.yaml").read_text(encoding="utf-8"))
    data["run"]["input"]["folder"] = str(TEST_DATA)
    data["segmentation"]["label_folder"] = str(TEST_DATA)
    data["outputs"] = copy.deepcopy(outputs)
    path = Path(path)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def start_kit(base, outputs, name="settings.yaml"):
    """Run the command on the test kit; returns what the tests need to look at."""
    base = Path(base)
    settings = kit_settings(base / name, outputs)
    arguments = ["batch", settings, "--output-folder", base / "out"]
    command, code, folder = run_command_batch(arguments[1:], base)
    return SimpleNamespace(command=command, code=code, folder=folder, settings=settings, arguments=arguments)


def names_in(folder):
    folder = Path(folder)
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


def check_nothing_unfinished_is_left(run_folder):
    """No file under a temporary name and no folder in which QC files are drawn."""
    run_folder = Path(run_folder)
    assert not [path.name for path in run_folder.rglob("*") if ".tmp" in path.name]
    assert not (run_folder / "qc_temporary").exists()
    assert not (run_folder / "labels_temporary").exists()


def check_png(path):
    """The file opens as a PNG image of some size."""
    with Image.open(path) as picture:
        assert picture.format == "PNG", path
        width, height = picture.size
        picture.load()
    assert width > 100 and height > 100, path


class PageLinks(HTMLParser):
    """The addresses a page names in its tags."""

    def __init__(self):
        super().__init__()
        self.addresses = []
        self.tags = []
        self.n_inline_scripts = 0
        self._in_script = False

    def handle_starttag(self, tag, attributes):
        self.tags.append(tag)
        for name, value in attributes:
            if name in ("src", "href", "srcset", "data", "action", "poster") and value:
                self.addresses.append((tag, name, value))
        if tag == "script" and not any(name == "src" for name, _ in attributes):
            self.n_inline_scripts += 1


def check_page_needs_no_internet(path):
    """The page loads nothing from an address: its script and its picture are inside it."""
    text = Path(path).read_text(encoding="utf-8")
    parser = PageLinks()
    parser.feed(text)
    assert not parser.addresses, parser.addresses
    assert "link" not in parser.tags and "iframe" not in parser.tags
    assert parser.n_inline_scripts >= 1
    assert "plotly.js v" in text
    # the picture is held in the page as data, not as an address to fetch
    sources = [source.replace("\\u002f", "/") for source in re.findall(r'"source"\s*:\s*"([^"]{0,30})', text)]
    assert sources and all(source.startswith("data:image/") for source in sources), sources
    assert not re.search(r"@import|url\(\s*['\"]?https?:", text)
    return text


def expected_qc_files(images, channels, final="png"):
    """Names in `qc/` for finished images and their channels (no Cellpose figure, no calibration plot)."""
    kinds = [kind.replace("final.png", f"final.{final}") for kind in QC_KINDS]
    return sorted(f"{image}_ch{channel}_{kind}" for image in images for channel in channels for kind in kinds)


def expected_npz_files(images, channels):
    return sorted(f"{image}_ch{channel}.npz" for image in images for channel in channels)


def check_files_of_finished_images_only(run_folder, finished, channels=(0, 1)):
    """Tables, QC files and `.npz` files hold exactly the finished images, each with all its files."""
    run_folder = Path(run_folder)
    assert image_names(read_table(run_folder, "images")) == finished
    assert image_names(read_table(run_folder, "spots")) == finished
    assert names_in(run_folder / "qc") == expected_qc_files(finished, channels)
    assert names_in(run_folder / "npz") == expected_npz_files(finished, channels)
    per_image = names_in(run_folder / "per_image")
    assert [name[: -len("_images.csv")] for name in per_image if name.endswith("_images.csv")] == finished
    assert all(any(name.startswith(f"{image}_") for image in finished) for name in per_image)
    check_nothing_unfinished_is_left(run_folder)


# ---------------------------------------------------------------------------
# 1. Test kit with every output on
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def kit_runs(tmp_path_factory):
    """The test kit run with the final QC as PNG and, in another run, as HTML."""
    return {final: start_kit(tmp_path_factory.mktemp(f"kit_{final}"), every_output(final)) for final in ("png", "html")}


@pytest.mark.parametrize("final", ["png", "html"])
def test_kit_every_output(kit_runs, final):
    run = kit_runs[final]
    assert run.code == 0, run.command.describe()
    folder = run.folder
    check_last_lines(run.command, folder, "The run finished: 1 image(s) processed")

    assert set(names_in(folder)) == RUN_FILES
    assert names_in(folder / "per_image") == sorted(
        f"{CROP_NAME}_{kind}.csv" for kind in ("spots", "clusters", "cells", "images"))
    assert names_in(folder / "qc") == sorted(
        f"{CROP_NAME}_ch2_{kind}" for kind in ("detection.png", "elbow.png", f"final.{final}", "referencespot.tif"))
    assert names_in(folder / "npz") == [f"{CROP_NAME}_ch2.npz"]
    check_nothing_unfinished_is_left(folder)

    qc = folder / "qc"
    for name in names_in(qc):
        if name.endswith(".png"):
            check_png(qc / name)
    assert tifffile.imread(qc / f"{CROP_NAME}_ch2_referencespot.tif").ndim == 3
    if final == "html":
        check_page_needs_no_internet(qc / f"{CROP_NAME}_ch2_final.html")
    else:
        assert not [name for name in names_in(qc) if name.endswith(".html") or name.endswith(".js")]

    with np.load(folder / "npz" / f"{CROP_NAME}_ch2.npz") as arrays:
        assert sorted(arrays.files) == ["clusters", "spots_post_clustering"]
        assert len(arrays["spots_post_clustering"]) == len(read_table(folder, "spots")) == 692

    images = read_table(folder, "images")
    assert list(images["status"]) == ["done"]
    assert not images["warnings"].astype(str).str.contains("QC file").any()


@pytest.mark.parametrize("final", ["png", "html"])
def test_kit_run_record_and_log(kit_runs, final):
    run = kit_runs[final]
    folder = run.folder
    info = run_info(folder, "finished")
    assert info["command"] == cli.command_line([str(argument) for argument in run.arguments])
    assert info["settings_file"] == str(run.settings)
    assert info["ended"] != "not ended"
    assert progress(folder)["status"] == "finished"

    text = log_text(folder)
    assert f"QC images: elbow plot, detection plot, reference spot, final QC ({final.upper()})" in text
    assert "Keep awake: off" in text


# ---------------------------------------------------------------------------
# 2. Repeating the run from its run_config.yaml
# ---------------------------------------------------------------------------


def test_repeat_gives_the_same_tables_and_files(kit_runs, tmp_path):
    first = kit_runs["html"].folder
    command, code, again = run_command_batch([first / "run_config.yaml", "--output-folder", tmp_path / "again"], tmp_path)
    assert code == 0, command.describe()
    assert again != first
    sorted_tables_equal(first, again)

    assert set(names_in(again)) == RUN_FILES
    assert names_in(again / "qc") == names_in(first / "qc")
    assert names_in(again / "npz") == names_in(first / "npz")
    check_nothing_unfinished_is_left(again)
    with np.load(first / "npz" / f"{CROP_NAME}_ch2.npz") as one, np.load(again / "npz" / f"{CROP_NAME}_ch2.npz") as two:
        assert sorted(one.files) == sorted(two.files)
        for key in one.files:
            np.testing.assert_array_equal(one[key], two[key], err_msg=key)
    assert run_info(again, "finished")["settings_file"] == str(first / "run_config.yaml")


# ---------------------------------------------------------------------------
# 3. Calibrated thresholds
# ---------------------------------------------------------------------------

CALIBRATED_IMAGES = ["cal_1", "cal_2", "cal_3_blank", "other"]


@pytest.fixture(scope="module")
def calibrated_runs(tmp_path_factory):
    """Four generated images, the channel 0 threshold calibrated on those whose names hold `cal`; and the repeat."""
    base = tmp_path_factory.mktemp("calibrated")
    folder = base / "input"
    folder.mkdir()
    generated_image(folder / "cal_1.tif", seed=10, amplitude=400)
    generated_image(folder / "cal_2.tif", seed=20, amplitude=800)
    generated_image(folder / "cal_3_blank.tif", blank=True)
    generated_image(folder / "other.tif", seed=30)
    calibrated = {"index": 0, "name": "", "background": {"method": "tophat", "radius_px": 5},
                  "threshold": {"mode": "calibrated", "calibration_filter": "cal"}}
    settings = write_settings(base / "settings.yaml", folder, base / "out", channels=[calibrated, channel_settings(1)],
                              workers=2, outputs=every_output("png"))
    first_command, first_code, first = run_command_batch([settings], base)
    assert first is not None, first_command.describe()
    again = run_command_batch([first / "run_config.yaml", "--output-folder", base / "again"], base)
    return SimpleNamespace(first=(first_command, first_code, first), again=again)


def test_calibration_files_are_written(calibrated_runs):
    command, code, folder = calibrated_runs.first
    assert code == 0, command.describe()
    calibration = read_table(folder, "calibration")
    assert image_names(calibration) == ["cal_1", "cal_2", "cal_3_blank"]
    check_png(folder / "qc" / "calibration.png")
    assert "calibration.png" in names_in(folder / "qc")
    check_nothing_unfinished_is_left(folder)

    # every image is processed, with the threshold the calibration worked out
    images = read_table(folder, "images")
    assert image_names(images) == sorted(CALIBRATED_IMAGES)
    assert list(images["status"]) == ["done"] * 8
    threshold = images.loc[images["channel"] == 0, "threshold"]
    assert threshold.nunique() == 1
    assert run_info(folder, "finished")["calibrated_thresholds"] == {"channel 0": float(threshold.iloc[0])}
    resolved = yaml.safe_load((folder / "run_config.yaml").read_text(encoding="utf-8"))["resolved"]
    assert resolved["thresholds"] == {0: float(threshold.iloc[0])}
    assert "QC images: elbow plot, calibration plot, detection plot" in log_text(folder)


def test_repeat_does_not_calibrate_again(calibrated_runs):
    _, _, first = calibrated_runs.first
    command, code, again = calibrated_runs.again
    assert code == 0, command.describe()
    sorted_tables_equal(first, again)

    assert not (again / "calibration.csv").exists()
    assert "calibration.png" not in names_in(again / "qc")
    assert [name for name in names_in(first / "qc") if name != "calibration.png"] == names_in(again / "qc")
    assert "calibration plot" not in log_text(again)
    assert not re.search(r"^Channel 0: calibrated threshold", log_text(again), flags=re.M)
    assert run_info(again, "finished")["calibrated_thresholds"] == run_info(first, "finished")["calibrated_thresholds"]
    check_nothing_unfinished_is_left(again)


# ---------------------------------------------------------------------------
# 4. Every output off
# ---------------------------------------------------------------------------


def test_every_output_off_gives_the_same_tables(kit_runs, tmp_path):
    off = start_kit(tmp_path, no_output())
    assert off.code == 0, off.command.describe()
    assert set(names_in(off.folder)) == RUN_FILES - {"qc", "npz"}
    assert not (off.folder / "qc").exists()
    assert not (off.folder / "npz").exists()
    check_nothing_unfinished_is_left(off.folder)
    assert "QC images: none" in log_text(off.folder)
    assert run_info(off.folder, "finished")["status"] == "finished"
    sorted_tables_equal(kit_runs["png"].folder, off.folder)
    sorted_tables_equal(kit_runs["html"].folder, off.folder)


# ---------------------------------------------------------------------------
# 5. A cancelled run and a worker that is killed
# ---------------------------------------------------------------------------


def slow_settings(base, n_images, workers):
    """Settings for images that each take a second or more, with every output on."""
    folder = base / "input"
    folder.mkdir()
    for number in range(n_images):
        write_tif(folder / f"img_{number:02d}.tif", spots_stack((12, 256, 256), seed=number, n_spots=30), "ZCYX")
    return write_settings(base / "settings.yaml", folder, base / "out", workers=workers, outputs=every_output("png"))


def an_unfinished_image_has_qc_files(command, run_folder):
    """The name of an image that is being worked on and has QC files drawn already, once another image is finished."""
    command.workers()
    finished = set(finished_images(run_folder))
    if not finished:
        return None
    for staging in sorted((run_folder / "qc_temporary").glob("*")):
        if staging.name not in finished and any(staging.rglob("*.png")):
            return staging.name
    return None


def wait_for_run_folder(command, base):
    folders = lambda: [path for path in (base / "out").glob("*") if path.is_dir()]
    return wait_until(lambda: folders()[0] if folders() else None, command, "the run folder")


def test_cancelled_run_keeps_the_files_of_finished_images_only(tmp_path):
    n_images = 6
    settings = slow_settings(tmp_path, n_images, workers=1)
    with running(["batch", settings], tmp_path) as command:
        folder = wait_for_run_folder(command, tmp_path)
        wait_until(lambda: an_unfinished_image_has_qc_files(command, folder), command,
                   "QC files of an image that is not finished")
        (folder / "cancel").write_text("", encoding="utf-8")
        assert command.wait() == 130, command.describe()
        assert "a `cancel` file was found" in command.out
        assert wait_until_gone(list(command.seen_workers.values())) == []

    assert progress(folder)["status"] == "cancelled"
    run_info(folder, "cancelled")
    finished = finished_images(folder)
    assert 1 <= len(finished) < n_images
    check_files_of_finished_images_only(folder, finished)


@pytest.mark.parametrize("workers, status, code", [(2, "finished", 0), (1, "stopped", 1)])
def test_killed_worker_leaves_the_files_of_finished_images_only(tmp_path, workers, status, code):
    n_images = 6
    settings = slow_settings(tmp_path, n_images, workers=workers)
    with running(["batch", settings], tmp_path) as command:
        folder = wait_for_run_folder(command, tmp_path)
        wait_until(lambda: an_unfinished_image_has_qc_files(command, folder), command,
                   "QC files of an image that is not finished")
        victims = command.workers()
        assert victims
        victims[0].kill()
        assert command.wait() == code, command.describe()
        assert wait_until_gone(list(command.seen_workers.values())) == []

    assert progress(folder)["status"] == status
    info = run_info(folder, status)
    finished = finished_images(folder)
    if status == "finished":
        # the images in progress were tried again with fewer workers
        assert finished == [f"img_{number:02d}" for number in range(n_images)]
        restarts = info["worker_restarts"]
        assert isinstance(restarts, list) and len(restarts) == 1
        assert restarts[0]["workers"] == 1 and restarts[0]["images_lost"]
        assert list(read_table(folder, "images")["status"]) == ["done"] * (2 * n_images)
    else:
        assert 1 <= len(finished) < n_images
    check_files_of_finished_images_only(folder, finished)
    assert "A worker process stopped unexpectedly" in log_text(folder)


# ---------------------------------------------------------------------------
# 6. Cellpose (stand-in model): the final QC with the run's own labels
# ---------------------------------------------------------------------------


def test_final_qc_of_a_run_with_cellpose_shows_the_runs_own_cells(crop_config_path, tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    shutil.copy(TEST_DATA / f"{CROP_NAME}.tif", folder)

    def change(data):
        data["run"]["input"].update(folder=str(folder), filter="")
        data["run"]["output_folder"] = str(tmp_path / "out")
        data["outputs"].update(npz=True, label_images=True)
        data["outputs"]["qc"].update(ON, final="html")

    config = with_cellpose(with_changes(load_config(crop_config_path), change))
    result = run_cellpose(config, StandInModel(n_cells=3))
    assert result.status == "finished", result.message
    run_folder = result.run_folder

    assert set(names_in(run_folder)) == RUN_FILES | {"labels"}
    assert names_in(run_folder / "qc") == sorted(
        [f"{CROP_NAME}_cellpose_qc.png"]
        + [f"{CROP_NAME}_ch2_{kind}" for kind in ("detection.png", "elbow.png", "final.html", "referencespot.tif")])
    assert names_in(run_folder / LABELS) == [f"{CROP_NAME}_seglabels.tif"]
    assert names_in(run_folder / "npz") == [f"{CROP_NAME}_ch2.npz"]
    check_png(run_folder / "qc" / f"{CROP_NAME}_cellpose_qc.png")
    check_nothing_unfinished_is_left(run_folder)

    # the page shows the cells of the labels this run made, with the counts of its own cells.csv
    page = run_folder / "qc" / f"{CROP_NAME}_ch2_final.html"
    check_page_needs_no_internet(page)
    labels = tifffile.imread(run_folder / LABELS / f"{CROP_NAME}_seglabels.tif")
    cells = read_table(run_folder, "cells")
    assert sorted(cells["cell_id"]) == sorted(int(label) for label in np.unique(labels) if label > 0) == [1, 2, 3]
    hover = [trace for trace in _page_data(page) if trace.get("name") == "Cell outlines" and trace.get("mode") == "markers"][0]
    rows = np.asarray(hover["customdata"])
    assert set(rows[:, 0]) == {1, 2, 3}
    for row, x, y in zip(rows, hover["x"], hover["y"]):
        assert labels[int(round(y)), int(round(x))] == row[0]
        cell = cells[cells["cell_id"] == row[0]].iloc[0]
        assert list(row[:5]) == [cell["cell_id"], cell["n_spots"], cell["n_spots_in_clusters"],
                                 cell["n_spots_outside_clusters"], cell["n_clusters"]]
    check_no_worker_left()


# ---------------------------------------------------------------------------
# 7. Keep-awake on macOS
# ---------------------------------------------------------------------------


def caffeinate_of(pid):
    """The `caffeinate` processes tied to the process `pid` (those started with `-w <pid>`)."""
    found = []
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            command = process.info["cmdline"] or []
            if process.info["name"] == "caffeinate" and command[-2:] == ["-w", str(pid)]:
                found.append(process)
        except psutil.Error:
            continue
    return found


@pytest.mark.skipif(sys.platform != "darwin", reason="caffeinate is part of macOS")
def test_command_keeps_the_computer_awake_and_leaves_no_caffeinate(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    for number in range(2):
        write_tif(folder / f"img_{number}.tif", spots_stack((8, 128, 128), seed=number, n_spots=20), "ZCYX")
    settings = write_settings(tmp_path / "settings.yaml", folder, tmp_path / "out")
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["run"]["keep_awake"] = True
    settings.write_text(yaml.safe_dump(data), encoding="utf-8")

    seen = []
    with running(["batch", settings], tmp_path) as command:
        try:
            seen = wait_until(lambda: caffeinate_of(command.process.pid), command, "caffeinate to start")
            assert command.wait() == 0, command.describe()
            end = time.monotonic() + 10
            while caffeinate_of(command.process.pid) and time.monotonic() < end:
                time.sleep(0.1)
            assert caffeinate_of(command.process.pid) == []
        finally:
            for process in caffeinate_of(command.process.pid):
                process.kill()

    assert len(seen) == 1
    folder = [path for path in (tmp_path / "out").glob("*") if path.is_dir()][0]
    assert log_text(folder).count(KEPT_AWAKE_LINE) == 1
    assert progress(folder)["status"] == "finished"
