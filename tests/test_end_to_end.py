"""End-to-end tests: `bigfish-pypeline batch` started as a separate process, with the real pipeline.

Each test starts the command the way a user would, in an empty working folder, and
looks at the exit code, the printed lines and the files of the run folder.
Everything is written under the test's temporary folder.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import pytest
import tifffile
import yaml

from bigfish_pypeline import cli
from conftest import CROP_NAME, TEST_DATA, assert_clusters_as_v1
from synthetic import make_image

WAIT_S = 90
POLL_S = 0.05

windows_only_skip = pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX signals or permissions")


# ---------------------------------------------------------------------------
# Running the command
# ---------------------------------------------------------------------------


def command_arguments():
    """The installed command next to this Python, or the same code run with `-m`."""
    folder = Path(sys.executable).parent
    found = shutil.which(cli.PROGRAM, path=os.pathsep.join([str(folder), str(folder / "Scripts")]))
    if found is not None:
        return [found]
    return [sys.executable, "-m", "bigfish_pypeline.cli"]


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


class Command:
    """A running `bigfish-pypeline` process, started in its own empty working folder."""

    def __init__(self, arguments, base_folder):
        self.home = Path(tempfile.mkdtemp(prefix="command_", dir=base_folder))
        self.cwd = self.home / "cwd"
        self.cwd.mkdir()
        self._out_path = self.home / "stdout.txt"
        self._err_path = self.home / "stderr.txt"
        with open(self._out_path, "wb") as out, open(self._err_path, "wb") as err:
            self.process = subprocess.Popen(
                command_arguments() + [str(argument) for argument in arguments],
                cwd=self.cwd, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
            )
        self.seen_workers = {}

    @property
    def out(self):
        return read_text(self._out_path)

    @property
    def err(self):
        return read_text(self._err_path)

    def describe(self):
        return f"exit code {self.process.poll()}\n--- stdout ---\n{self.out}\n--- stderr ---\n{self.err}"

    def workers(self):
        """The worker processes of the command that are running now (also remembered)."""
        found = []
        try:
            children = psutil.Process(self.process.pid).children(recursive=True)
        except psutil.Error:
            children = []
        for child in children:
            try:
                if "spawn_main" in " ".join(child.cmdline()):
                    found.append(child)
                    self.seen_workers[child.pid] = child
            except psutil.Error:
                pass
        return found

    def wait(self, timeout=WAIT_S):
        """Wait for the command to end; returns its exit code."""
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pytest.fail(f"the command did not end within {timeout} s\n{self.describe()}")

    def stop(self):
        """Stop the command and every process it started."""
        try:
            descendants = psutil.Process(self.process.pid).children(recursive=True)
        except psutil.Error:
            descendants = []
        for process in descendants + list(self.seen_workers.values()):
            try:
                process.kill()
            except psutil.Error:
                pass
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()


@contextmanager
def running(arguments, base_folder):
    """Start the command; it and its workers are stopped when the block ends, whatever happens."""
    command = Command(arguments, base_folder)
    try:
        yield command
    finally:
        command.stop()


def run_command(arguments, base_folder, timeout=WAIT_S):
    """Run the command to its end; returns (command, exit code)."""
    with running(arguments, base_folder) as command:
        code = command.wait(timeout)
    return command, code


def wait_until(condition, command, what, timeout=WAIT_S):
    """Wait until `condition()` gives a true value (returned); fails if the command ends first."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        if command.process.poll() is not None:
            value = condition()
            if value:
                return value
            pytest.fail(f"the command ended before {what}\n{command.describe()}")
        time.sleep(POLL_S)
    pytest.fail(f"gave up waiting for {what}\n{command.describe()}")


def wait_until_gone(processes, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        alive = []
        for process in processes:
            try:
                if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                    alive.append(process)
            except psutil.Error:
                pass
        if not alive:
            return []
        time.sleep(POLL_S)
    return alive


def run_folder_of(command):
    """The run folder named in the last `Run folder:` line printed by the command."""
    lines = [line for line in command.out.splitlines() if line.startswith("Run folder: ")]
    assert lines, command.describe()
    folder = Path(lines[-1][len("Run folder: "):])
    assert folder.is_dir(), command.describe()
    return folder


def batch(arguments, base_folder, timeout=WAIT_S):
    """Run `batch` to its end; returns (command, exit code, run folder or None)."""
    command, code = run_command(["batch"] + list(arguments), base_folder, timeout)
    folder = None
    if any(line.startswith("Run folder: ") for line in command.out.splitlines()):
        folder = run_folder_of(command)
    return command, code, folder


# ---------------------------------------------------------------------------
# Making images, labels and settings
# ---------------------------------------------------------------------------


def write_tif(path, array, axes, voxel_um=(0.2, 0.065, 0.065)):
    """An ImageJ TIFF with voxel sizes in its metadata."""
    z, y, x = voxel_um
    metadata = {"axes": axes, "unit": "um"}
    if "Z" in axes:
        metadata["spacing"] = z
    tifffile.imwrite(path, array, imagej=True, metadata=metadata, resolution=(1 / x, 1 / y))
    return Path(path)


def spots_stack(shape=(8, 64, 64), n_channels=2, seed=0, n_spots=8, blank=False):
    """A ZCYX array (uint16) with Gaussian spots, each channel with its own spots."""
    channels = [
        make_image(shape, n_spots=n_spots, seed=seed + 10 * channel, blank=blank)[0]
        for channel in range(n_channels)
    ]
    return np.stack(channels, axis=1)


def write_labels(folder, name, shape_yx, margin=4):
    """`<name>_seglabels.tif`: four rectangular cells, labelled 1 to 4."""
    height, width = shape_yx
    labels = np.zeros(shape_yx, dtype=np.uint16)
    half_y, half_x = height // 2, width // 2
    labels[margin:half_y - 1, margin:half_x - 1] = 1
    labels[margin:half_y - 1, half_x + 1:width - margin] = 2
    labels[half_y + 1:height - margin, margin:half_x - 1] = 3
    labels[half_y + 1:height - margin, half_x + 1:width - margin] = 4
    tifffile.imwrite(Path(folder) / f"{name}_seglabels.tif", labels)


def channel_settings(index, threshold=50, name=""):
    return {
        "index": index, "name": name,
        "background": {"method": "tophat", "radius_px": 5},
        "threshold": {"mode": "manual", "value": threshold},
    }


QC_OFF = {"elbow_plot": False, "detection": False, "reference_spot": False, "cellpose": False,
          "final": "none"}


def write_settings(path, input_folder, output_folder, axes="ZCYX", channels=(0, 1), workers=1,
                   label_folder=None, run_name="e2e", **changes):
    """A settings file for generated images (top-hat background, manual thresholds).

    No QC images are drawn; a test that looks at them passes its own `outputs`.
    """
    data = {
        "config_version": 1,
        "run": {
            "name": run_name,
            "input": {"source": "local", "folder": str(input_folder)},
            "output_folder": "" if output_folder is None else str(output_folder),
            "workers": workers,
            "keep_awake": False,
        },
        "image": {
            "axes": axes,
            "voxel_size_nm": {"z": 200, "yx": 65} if "Z" in axes else {"yx": 65},
        },
        "channels": [channel if isinstance(channel, dict) else channel_settings(channel) for channel in channels],
        "outputs": {"qc": dict(QC_OFF)},
    }
    if label_folder is not None:
        data["segmentation"] = {"enabled": True, "source": "label_files", "label_folder": str(label_folder)}
    data.update(changes)
    path = Path(path)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def read_table(run_folder, kind):
    return pd.read_csv(Path(run_folder) / f"{kind}.csv")


def sorted_tables_equal(first, second):
    """The combined tables of two runs agree after sorting, leaving out `runtime_s`."""
    for kind in ("images", "spots", "clusters", "cells"):
        if not (first / f"{kind}.csv").is_file():
            assert not (second / f"{kind}.csv").is_file(), kind
            continue
        one, two = read_table(first, kind), read_table(second, kind)
        if "runtime_s" in one.columns:
            one, two = one.drop(columns="runtime_s"), two.drop(columns="runtime_s")
        columns = list(one.columns)
        one = one.sort_values(columns, kind="stable").reset_index(drop=True)
        two = two.sort_values(columns, kind="stable").reset_index(drop=True)
        pd.testing.assert_frame_equal(one, two)


def log_text(run_folder):
    return read_text(Path(run_folder) / "run.log")


def progress(run_folder):
    return json.loads(read_text(Path(run_folder) / "progress.json"))


def image_names(table):
    return list(dict.fromkeys(table["image"]))


def finished_images(run_folder):
    """Images whose complete `_images.csv` is in `per_image/`."""
    return sorted(path.name[: -len("_images.csv")] for path in (Path(run_folder) / "per_image").glob("*_images.csv"))


# ---------------------------------------------------------------------------
# 1. Test kit
# ---------------------------------------------------------------------------


def kit_settings_without_qc(path):
    """The test kit's config with its folders named in full and no QC images."""
    data = yaml.safe_load((TEST_DATA / f"{CROP_NAME}_config.yaml").read_text(encoding="utf-8"))
    data["run"]["input"]["folder"] = str(TEST_DATA)
    data["segmentation"]["label_folder"] = str(TEST_DATA)
    data["outputs"]["qc"] = dict(QC_OFF)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def kit_with_labels(tmp_path_factory):
    base = tmp_path_factory.mktemp("kit_labels")
    settings = kit_settings_without_qc(base / "settings.yaml")
    command, code, folder = batch([settings, "--output-folder", base / "out"], base)
    return command, code, folder


def test_kit_with_label_files_agrees_with_v1(kit_with_labels, crop_reference_folder):
    command, code, folder = kit_with_labels
    assert code == 0, command.describe()
    assert f"{CROP_NAME}, channel 2: done, threshold 18, 692 spots" in command.out
    assert command.out.splitlines()[-1] == f"Run folder: {folder}"

    reference_folder = crop_reference_folder / "general_manual18_subpixel-off"
    reference = np.load(next(reference_folder.glob("*_bfoutput.npz")))

    spots = read_table(folder, "spots")
    assert len(spots) == 692
    np.testing.assert_array_equal(
        spots[["z_px", "y_px", "x_px", "cluster_id"]].to_numpy(), reference["spots_post_clustering"]
    )
    clusters = read_table(folder, "clusters")
    assert_clusters_as_v1(
        clusters[["z_px", "y_px", "x_px", "n_spots", "cluster_id"]].to_numpy(), reference["clusters"]
    )
    cells = read_table(folder, "cells")
    expected = pd.read_csv(reference_folder / "per_cell_counts.csv")
    assert len(cells) == len(expected) == 44
    np.testing.assert_array_equal(cells["cell_id"], expected["label"])
    for column in ("touches_border", "n_spots", "n_spots_in_clusters", "n_spots_outside_clusters", "n_clusters"):
        np.testing.assert_array_equal(cells[column], expected[column], err_msg=column)

    images = read_table(folder, "images")
    assert list(images["status"]) == ["done"]
    assert list(images["segmentation_status"]) == ["done"]


def test_kit_without_segmentation(kit_with_labels, tmp_path):
    _, _, labelled = kit_with_labels
    settings = kit_settings_without_qc(tmp_path / "no_segmentation.yaml")
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["segmentation"]["enabled"] = False
    settings.write_text(yaml.safe_dump(data), encoding="utf-8")

    command, code, folder = batch([settings, "--output-folder", tmp_path / "out"], tmp_path)
    assert code == 0, command.describe()
    assert not (folder / "cells.csv").exists()
    spots = read_table(folder, "spots")
    assert (spots["cell_id"] == -1).all()
    assert (read_table(folder, "clusters")["cell_id"] == -1).all()
    with_labels = read_table(labelled, "spots")
    assert len(spots) == 692
    pd.testing.assert_frame_equal(spots.drop(columns="cell_id"), with_labels.drop(columns="cell_id"))
    images = read_table(folder, "images")
    assert images["segmentation_status"].isna().all()
    assert images["n_cells"].isna().all()


# ---------------------------------------------------------------------------
# 2. A mixed batch in one run
# ---------------------------------------------------------------------------

ACCENTED = unicodedata.normalize("NFC", "g ünï côde 日本 name")
GOOD_IMAGES = ["a_small", "b_large", "c blank", ACCENTED, "h_no_labels"]
FAILED_IMAGES = ["d_one_channel", "e_corrupt", "f_float"]


@pytest.fixture(scope="module")
def mixed_batch(tmp_path_factory):
    """Eight images of every kind in one folder, run with two workers."""
    base = tmp_path_factory.mktemp("mixed")
    folder = base / "input"
    folder.mkdir()

    for name, shape in (("a_small", (8, 64, 64)), (ACCENTED, (10, 80, 96)), ("b_large", (12, 160, 128))):
        write_tif(folder / f"{name}.tif", spots_stack(shape, seed=len(name)), "ZCYX")
        write_labels(folder, name, shape[1:])
    write_tif(folder / "c blank.tif", spots_stack((8, 64, 64), blank=True), "ZCYX")
    write_labels(folder, "c blank", (64, 64))
    write_tif(folder / "h_no_labels.tif", spots_stack((8, 64, 64), seed=7), "ZCYX")

    # a layout that differs from the settings: one channel and no channel axis
    write_tif(folder / "d_one_channel.tif", spots_stack((8, 64, 64), n_channels=1)[:, 0], "ZYX")
    write_labels(folder, "d_one_channel", (64, 64))
    corrupt = write_tif(folder / "e_corrupt.tif", spots_stack(), "ZCYX")
    corrupt.write_bytes(corrupt.read_bytes()[:3000])
    # a pixel type that is refused
    write_tif(folder / "f_float.tif", spots_stack().astype(np.float32), "ZCYX")

    # results of an earlier run sit in a subfolder
    earlier = folder / "bigfish_results" / "2026-01-01_0900_earlier" / "labels"
    earlier.mkdir(parents=True)
    write_tif(earlier / "earlier_result.tif", spots_stack(), "ZCYX")
    write_tif(folder / "bigfish_results" / "earlier_top.tif", spots_stack(), "ZCYX")

    settings = write_settings(base / "settings.yaml", folder, base / "out", workers=2, label_folder=folder)
    command, code, run_folder = batch([settings], base)
    return command, code, run_folder, settings, base


def test_mixed_batch_run(mixed_batch):
    command, code, run_folder, _, _ = mixed_batch
    assert code == 0, command.describe()
    assert run_folder is not None
    lines = command.out.splitlines()
    assert lines[-1] == f"Run folder: {run_folder}"
    # the last line of the run gives the number of failed and skipped channels
    assert lines[-2].startswith("The run finished: 8 image(s) processed; 6 channel(s) failed"), lines[-2]
    assert lines[-2].endswith(". See images.csv and run.log in the run folder."), lines[-2]
    assert "Workers: 2 worker(s), as set in the config" in command.out
    assert progress(run_folder)["status"] == "finished"
    assert not list((run_folder / "per_image").glob("*.tmp"))


def test_mixed_batch_images_table(mixed_batch):
    _, _, run_folder, _, _ = mixed_batch
    images = read_table(run_folder, "images")
    expected_order = sorted(GOOD_IMAGES + FAILED_IMAGES)
    assert image_names(images) == expected_order
    assert expected_order[0] == "a_small"
    assert len(images) == 16
    assert list(images["channel"]) == [0, 1] * 8

    def rows(name):
        return images[images["image"] == name]

    for name in GOOD_IMAGES:
        assert list(rows(name)["status"]) == ["done", "done"], name
    for name in FAILED_IMAGES:
        assert list(rows(name)["status"]) == ["failed", "failed"], name
        assert rows(name)["reason"].notna().all(), name

    assert "axes" in rows("d_one_channel")["reason"].iloc[0] or "layout" in rows("d_one_channel")["reason"].iloc[0]
    assert "damaged or incomplete" in rows("e_corrupt")["reason"].iloc[0]
    assert "the pixel type is 32-bit with decimal values (float32)" in rows("f_float")["reason"].iloc[0]

    assert (rows("c blank")["n_spots"] == 0).all()
    for name in ("a_small", "b_large", ACCENTED):
        assert (rows(name)["n_spots"] > 0).all(), name
        assert list(rows(name)["segmentation_status"]) == ["done", "done"], name
    assert list(rows("h_no_labels")["segmentation_status"]) == ["no_labels", "no_labels"]
    assert rows("h_no_labels")["warnings"].str.contains("no cell results").all()
    assert not rows("a_small")["warnings"].fillna("").str.contains("no cell results").any()


def test_mixed_batch_combined_tables(mixed_batch):
    _, _, run_folder, _, _ = mixed_batch
    spots = read_table(run_folder, "spots")
    assert image_names(spots) == ["a_small", "b_large", ACCENTED, "h_no_labels"]
    assert set(spots["channel"]) == {0, 1}
    assert set(spots["image"]).isdisjoint(FAILED_IMAGES)

    cells = read_table(run_folder, "cells")
    assert image_names(cells) == ["a_small", "b_large", "c blank", ACCENTED]
    assert (cells.groupby(["image", "channel"]).size() == 4).all()
    labelled = spots[spots["image"] != "h_no_labels"]
    assert set(labelled["cell_id"]) <= {-1, 1, 2, 3, 4}
    assert (labelled["cell_id"] > 0).any()
    assert (spots.loc[spots["image"] == "h_no_labels", "cell_id"] == -1).all()

    assert set(read_table(run_folder, "clusters")["image"]) <= set(GOOD_IMAGES)


def test_mixed_batch_ignores_earlier_results(mixed_batch):
    _, _, run_folder, _, _ = mixed_batch
    text = log_text(run_folder)
    listed = text.split("image(s):")[1].split("Label folder")[0]
    assert "earlier" not in listed
    assert "h_no_labels: warning: no cell results" in text
    assert "channels: 10 done, 6 failed, 0 skipped" in text


def test_repeat_from_run_config(mixed_batch, tmp_path):
    _, _, run_folder, _, _ = mixed_batch
    command, code, again = batch([run_folder / "run_config.yaml", "--output-folder", tmp_path / "again"], tmp_path)
    assert code == 0, command.describe()
    assert again != run_folder
    sorted_tables_equal(run_folder, again)


# ---------------------------------------------------------------------------
# 3. Three FISH channels
# ---------------------------------------------------------------------------


def test_three_channels_with_own_thresholds(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    write_tif(folder / "three.tif", spots_stack((8, 64, 64), n_channels=3, seed=3, n_spots=10), "ZCYX")
    channels = [channel_settings(0, 30, "red"), channel_settings(1, 50, "green"), channel_settings(2, 80, "far red")]
    settings = write_settings(tmp_path / "settings.yaml", folder, tmp_path / "out", channels=channels)

    command, code, run_folder = batch([settings], tmp_path)
    assert code == 0, command.describe()
    images = read_table(run_folder, "images")
    assert list(images["channel"]) == [0, 1, 2]
    assert list(images["channel_name"]) == ["red", "green", "far red"]
    assert list(images["threshold"]) == [30, 50, 80]
    assert list(images["status"]) == ["done"] * 3
    spots = read_table(run_folder, "spots")
    assert set(spots["channel"]) == {0, 1, 2}
    counts = spots.groupby("channel").size()
    assert list(counts) == list(images["n_spots"])
    assert (counts > 0).all()


# ---------------------------------------------------------------------------
# 4. Two-dimensional images
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("axes", ["YX", "CYX"])
def test_two_dimensional_batch(tmp_path, axes):
    folder = tmp_path / "input"
    folder.mkdir()
    shape = (96, 80)
    for number, name in enumerate(("flat_1", "flat_2")):
        dense = {"centre": (48, 40), "n_spots": 20, "spread": 1.5}
        planes = [
            make_image(shape, n_spots=12, seed=number + 10 * channel, dense_region=dense)[0]
            for channel in range(2)
        ]
        array = planes[0] if axes == "YX" else np.stack(planes)
        write_tif(folder / f"{name}.tif", array, axes)
        write_labels(folder, name, shape)
    channels = [0] if axes == "YX" else [0, 1]
    settings = write_settings(tmp_path / "settings.yaml", folder, tmp_path / "out", axes=axes,
                              channels=channels, label_folder=folder)

    command, code, run_folder = batch([settings], tmp_path)
    assert code == 0, command.describe()
    for kind in ("spots", "clusters", "cells", "images"):
        table = read_table(run_folder, kind)
        assert not [column for column in table.columns if column.startswith("z_")], kind
        assert len(table) > 0, kind
    spots = read_table(run_folder, "spots")
    assert {"y_px", "x_px", "y_nm", "x_nm"} <= set(spots.columns)
    assert list(read_table(run_folder, "images")["status"]) == ["done"] * (2 * len(channels))
    assert set(spots["cell_id"]) <= {-1, 1, 2, 3, 4}


# ---------------------------------------------------------------------------
# 5. Pixel types
# ---------------------------------------------------------------------------


def test_8_bit_16_bit_and_float_images(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    base = spots_stack((8, 64, 64), seed=5, n_spots=10)
    write_tif(folder / "bits16.tif", base, "ZCYX")
    write_tif(folder / "bits8.tif", np.clip(base // 4, 0, 255).astype(np.uint8), "ZCYX")
    write_tif(folder / "float32.tif", base.astype(np.float32), "ZCYX")
    settings = write_settings(tmp_path / "settings.yaml", folder, tmp_path / "out", workers=2)

    command, code, run_folder = batch([settings], tmp_path)
    assert code == 0, command.describe()
    assert ("The run finished: 3 image(s) processed; 2 channel(s) failed. "
            "See images.csv and run.log in the run folder.") in command.out
    images = read_table(run_folder, "images")
    assert image_names(images) == ["bits16", "bits8", "float32"]
    statuses = images[["image", "channel", "status", "reason"]]
    assert list(images["status"]) == ["done"] * 4 + ["failed"] * 2, statuses
    expected = (
        "float32.tif: the pixel type is 32-bit with decimal values (float32), which cannot be used; "
        "only 8-bit, 12-bit and 16-bit images are accepted. Convert the image to 16-bit, for example in Fiji "
        "with Image › Type › 16-bit (https://imagej.net/ij/docs/menus/image.html#type), then run it again. In Fiji, first untick \"Scale when converting\" under Edit › Options › Conversions, so that the pixel values are kept."
    )
    assert list(images.loc[images["image"] == "float32", "reason"]) == [expected] * 2
    spots = read_table(run_folder, "spots")
    assert set(spots["image"]) == {"bits16", "bits8"}


# ---------------------------------------------------------------------------
# 6. Default output folder
# ---------------------------------------------------------------------------


def test_default_output_folder_and_second_run(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    for number, name in enumerate(("one", "two")):
        write_tif(folder / f"{name}.tif", spots_stack(seed=number), "ZCYX")
        write_labels(folder, name, (64, 64))
    settings = write_settings(tmp_path / "settings.yaml", folder, None, label_folder=folder)

    first_command, code, first = batch([settings], tmp_path)
    assert code == 0, first_command.describe()
    second_command, code, second = batch([settings], tmp_path)
    assert code == 0, second_command.describe()

    results = folder / "bigfish_results"
    assert first.parent == second.parent == results
    assert first != second
    if first.name[:15] == second.name[:15]:
        assert second.name == f"{first.name}_2"
    assert sorted(path.name for path in results.iterdir()) == sorted([first.name, second.name])
    for run_folder in (first, second):
        assert image_names(read_table(run_folder, "images")) == ["one", "two"]
    sorted_tables_equal(first, second)
    assert sorted(path.name for path in folder.iterdir() if path.is_file()) == [
        "one.tif", "one_seglabels.tif", "two.tif", "two_seglabels.tif"]


# ---------------------------------------------------------------------------
# 8. Cancel
# ---------------------------------------------------------------------------

N_SLOW_IMAGES = 10


def slow_batch(base, workers, n_images=N_SLOW_IMAGES):
    """Settings for images that each take about a second or more to process."""
    folder = base / "input"
    folder.mkdir()
    for number in range(n_images):
        write_tif(folder / f"img_{number:02d}.tif", spots_stack((16, 384, 384), seed=number, n_spots=40), "ZCYX")
    return write_settings(base / "settings.yaml", folder, base / "out", workers=workers)


def only_run_folder(base):
    folders = [path for path in (base / "out").glob("*") if path.is_dir()]
    return folders[0] if len(folders) == 1 else None


def check_cancelled_run(command, run_folder, worker_processes):
    assert command.out.splitlines()[-1] == f"Run folder: {run_folder}"
    assert "The run was cancelled" in command.out
    assert progress(run_folder)["status"] == "cancelled"
    assert "Traceback" not in command.err
    done = finished_images(run_folder)
    assert 1 <= len(done) < N_SLOW_IMAGES
    images = read_table(run_folder, "images")
    assert image_names(images) == done
    assert image_names(read_table(run_folder, "spots")) == done
    assert not list((run_folder / "per_image").glob("*.tmp"))
    assert worker_processes
    assert wait_until_gone(worker_processes) == []


@windows_only_skip
def test_cancel_with_ctrl_c(tmp_path):
    settings = slow_batch(tmp_path, workers=1)
    with running(["batch", settings], tmp_path) as command:
        first = wait_until(
            lambda: next(iter((tmp_path / "out").glob("*/per_image/img_00_images.csv")), None),
            command, "the first image to finish",
        )
        run_folder = first.parent.parent
        command.workers()
        os.kill(command.process.pid, signal.SIGINT)
        code = command.wait()
        assert code == 130, command.describe()
        check_cancelled_run(command, run_folder, list(command.seen_workers.values()))


def test_cancel_with_cancel_file(tmp_path):
    settings = slow_batch(tmp_path, workers=1)
    with running(["batch", settings], tmp_path) as command:
        first = wait_until(
            lambda: next(iter((tmp_path / "out").glob("*/per_image/img_00_images.csv")), None),
            command, "the first image to finish",
        )
        run_folder = first.parent.parent
        command.workers()
        (run_folder / "cancel").write_text("", encoding="utf-8")
        code = command.wait()
        assert code == 130, command.describe()
        assert "a `cancel` file was found" in command.out
        check_cancelled_run(command, run_folder, list(command.seen_workers.values()))


# ---------------------------------------------------------------------------
# 9. A worker that stops
# ---------------------------------------------------------------------------


def test_worker_killed_during_a_run(tmp_path):
    settings = slow_batch(tmp_path, workers=2, n_images=8)
    with running(["batch", settings], tmp_path) as command:
        def both_busy():
            started = command.out.count(": started")
            workers = command.workers()
            return len(workers) >= 1 and started >= 2 and workers

        workers = wait_until(both_busy, command, "two images to be in progress")
        workers[0].kill()
        code = command.wait()
        assert code == 0, command.describe()
        run_folder = run_folder_of(command)

    text = log_text(run_folder)
    assert "A worker process stopped unexpectedly" in text
    assert "Starting again with 1 worker(s)" in text
    assert "will be tried once more" in text
    assert "8 of 8 image(s) finished" in text
    images = read_table(run_folder, "images")
    assert list(images["status"]) == ["done"] * 16
    assert image_names(images) == [f"img_{number:02d}" for number in range(8)]
    assert image_names(read_table(run_folder, "spots")) == image_names(images)
    assert progress(run_folder)["status"] == "finished"
    assert progress(run_folder)["workers"] == 1
    assert not list((run_folder / "per_image").glob("*.tmp"))
    assert wait_until_gone(list(command.seen_workers.values())) == []


# ---------------------------------------------------------------------------
# 10. Problems before the run
# ---------------------------------------------------------------------------


def test_first_image_cannot_be_read(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    damaged = write_tif(folder / "a_damaged.tif", spots_stack(), "ZCYX")
    damaged.write_bytes(damaged.read_bytes()[:3000])
    write_tif(folder / "b_good.tif", spots_stack(), "ZCYX")
    settings = write_settings(tmp_path / "settings.yaml", folder, tmp_path / "out")

    command, code, run_folder = batch([settings], tmp_path)
    assert code == 1, command.describe()
    assert run_folder is None
    assert "The first image cannot be used" in command.err
    assert "a_damaged.tif" in command.err
    assert "Traceback" not in command.err
    assert not (tmp_path / "out").exists()


def test_first_image_with_another_layout(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    write_tif(folder / "a_one_channel.tif", spots_stack(n_channels=1)[:, 0], "ZYX")
    write_tif(folder / "b_good.tif", spots_stack(), "ZCYX")
    settings = write_settings(tmp_path / "settings.yaml", folder, tmp_path / "out")

    command, code, run_folder = batch([settings], tmp_path)
    assert code == 1, command.describe()
    assert run_folder is None
    assert "The first image cannot be used" in command.err
    assert "Traceback" not in command.err
    assert not (tmp_path / "out").exists()


@windows_only_skip
def test_output_folder_that_cannot_be_written(tmp_path):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("the root user can write to any folder")
    folder = tmp_path / "input"
    folder.mkdir()
    write_tif(folder / "good.tif", spots_stack(), "ZCYX")
    locked = tmp_path / "locked"
    locked.mkdir()
    settings = write_settings(tmp_path / "settings.yaml", folder, locked / "results")
    locked.chmod(0o500)
    try:
        command, code, run_folder = batch([settings], tmp_path)
    finally:
        locked.chmod(0o700)
    assert code == 1, command.describe()
    assert run_folder is None
    assert "cannot be" in command.err
    assert "Traceback" not in command.err
    assert list(locked.iterdir()) == []
