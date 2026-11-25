"""Tests for qc.py: the Cellpose QC figure, the elbow plot, the calibration plot, the detection plot, the reference spot and the final QC."""

import base64
import hashlib
import io
import json
import os
import re
import struct
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import tifffile
from matplotlib.collections import EllipseCollection, LineCollection, PatchCollection

from bigfish_pypeline import decomposition, detection, outputs, qc
from bigfish_pypeline import segmentation as seg
from cellpose_standin import StandInModel
from synthetic import make_image

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IMAGE = "slide 3 é"
PRETREATMENT = seg.describe_pretreatment(projection="max", bg_radius=200)


def _segmentation(n_cells, shape=(60, 90)):
    """What the batch runner passes on: the result of segment_cells with the stand-in model."""
    rng = np.random.default_rng(1)
    image = rng.poisson(40, shape).astype(np.uint16)
    image[15:45, 10:80] += 200
    return seg.segment_cells(StandInModel(n_cells=n_cells), image)


def _png_size(path):
    """Width and height in pixels, read from the PNG header; raises if it is not a PNG."""
    data = Path(path).read_bytes()
    assert data[:8] == PNG_SIGNATURE
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def _write(folder, n_cells=3, diameter=None, **kwargs):
    return qc.write_cellpose_qc(
        folder, IMAGE, _segmentation(n_cells), channel=0, pretreatment=PRETREATMENT,
        diameter=diameter, **kwargs,
    )


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------

def test_path_is_in_the_qc_folder(tmp_path):
    assert qc.cellpose_qc_path(tmp_path, "img_01") == tmp_path / "qc" / "img_01_cellpose_qc.png"


@pytest.mark.parametrize("n_cells", [3, 0])
def test_figure_is_written_as_a_png(tmp_path, n_cells):
    path = _write(tmp_path, n_cells=n_cells)

    assert path == tmp_path / "qc" / f"{IMAGE}_cellpose_qc.png"
    width, height = _png_size(path)
    assert 1200 <= width <= 3000
    assert 200 <= height <= 1500
    assert width > height


def test_no_temporary_file_is_left_behind(tmp_path):
    _write(tmp_path)
    _write(tmp_path, n_cells=0)

    assert [p.name for p in (tmp_path / "qc").iterdir()] == [f"{IMAGE}_cellpose_qc.png"]


def test_a_second_figure_replaces_the_first(tmp_path):
    first = _write(tmp_path, n_cells=3)
    first_bytes = first.read_bytes()
    second = _write(tmp_path, n_cells=0)

    assert second == first
    assert second.read_bytes() != first_bytes


def test_failed_write_leaves_no_file(tmp_path, monkeypatch):
    def fail(self, *args, **kwargs):
        Path(args[0]).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", fail)
    with pytest.raises(OSError):
        _write(tmp_path)

    assert list((tmp_path / "qc").iterdir()) == []


def test_the_image_given_is_not_changed(tmp_path):
    result = _segmentation(3)
    before = result["model_input"].copy()
    masks_before = result["masks"].copy()

    qc.write_cellpose_qc(tmp_path, IMAGE, result, 0, PRETREATMENT, None)

    np.testing.assert_array_equal(result["model_input"], before)
    np.testing.assert_array_equal(result["masks"], masks_before)


def test_a_flat_image_still_gives_a_figure(tmp_path):
    result = seg.segment_cells(StandInModel(n_cells=0), np.zeros((30, 40)))
    path = qc.write_cellpose_qc(tmp_path, IMAGE, result, 0, PRETREATMENT, None)
    assert _png_size(path)[0] > 0


def test_a_tall_image_gives_a_taller_figure(tmp_path):
    wide = qc.write_cellpose_qc(tmp_path, "wide", _segmentation(2, (40, 120)), 0, PRETREATMENT, None)
    tall = qc.write_cellpose_qc(tmp_path, "tall", _segmentation(2, (120, 40)), 0, PRETREATMENT, None)
    assert _png_size(tall)[1] > _png_size(wide)[1]


# ---------------------------------------------------------------------------
# The title
# ---------------------------------------------------------------------------

def test_title_holds_each_item():
    title = qc.cellpose_qc_title(
        "slide 3", 2, "max projection | rolling ball 200 px", 42.5, 17, 3.456, channel_name="DAPI",
    )

    assert "slide 3" in title
    assert "max projection" in title
    assert "channel 2 (DAPI)" in title
    assert "rolling ball 200 px" in title
    assert "diameter 42.5 px" in title
    assert "17 cells" in title
    assert "3.5 s" in title
    assert "\n" not in title


def test_title_with_the_pretreatment_text_from_the_segmentation_module():
    text = seg.describe_pretreatment(
        projection="mean", clip=True, clip_value=100, background=True, bg_radius=150,
        median_px=5, gaussian_sigma_px=1.5,
    )
    title = qc.cellpose_qc_title("img", 1, text, 30, 5, 1.0)

    assert text in title
    assert text.startswith("mean projection")


def test_title_says_when_no_diameter_is_set():
    title = qc.cellpose_qc_title("img", 0, PRETREATMENT, None, 5, 1.0)

    assert "None" not in title
    assert "no diameter set (image used at its own scale)" in title
    assert "chosen by Cellpose" not in title


def test_title_counts_cells_in_plain_words():
    assert "0 cells" in qc.cellpose_qc_title("img", 0, PRETREATMENT, None, 0, 1.0)
    assert "1 cell " in qc.cellpose_qc_title("img", 0, PRETREATMENT, None, 1, 1.0)
    assert "2 cells" in qc.cellpose_qc_title("img", 0, PRETREATMENT, None, 2, 1.0)


def test_long_title_is_continued_on_a_new_line_between_items():
    long_pretreatment = seg.describe_pretreatment(
        clip=True, median_px=5, gaussian_sigma_px=1.5, bg_radius=200,
    )
    name = "20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001"
    title = qc.cellpose_qc_title(name, 3, long_pretreatment, 42.5, 120, 12.3, channel_name="DAPI")

    lines = title.split("\n")
    assert len(lines) == 2
    assert all(len(line) <= qc.TITLE_LINE_WIDTH for line in lines)
    assert " | ".join(lines) == (
        f"{name} | channel 3 (DAPI) | {long_pretreatment} | diameter 42.5 px | 120 cells | 12.3 s"
    )


def test_very_long_image_name_does_not_run_off_the_figure():
    title = qc.cellpose_qc_title("x" * 400, 0, PRETREATMENT, None, 5, 1.0)

    assert all(len(line) <= qc.TITLE_LINE_WIDTH for line in title.split("\n"))
    assert title.split(" | ")[0].replace("\n", "") == "x" * 400


def test_title_on_the_figure_is_the_title_text():
    result = _segmentation(2)
    figure = qc.draw_cellpose_qc(result, IMAGE, 1, PRETREATMENT, 25, channel_name="DAPI")

    expected = qc.cellpose_qc_title(
        IMAGE, 1, PRETREATMENT, 25, result["n_cells"], result["seconds"], "DAPI"
    )
    assert figure.get_suptitle() == expected
    assert "2 cells" in expected
    assert len(figure.axes) == 4


def test_figure_with_no_cells_says_so_in_its_title():
    figure = qc.draw_cellpose_qc(_segmentation(0), IMAGE, 0, PRETREATMENT, None)

    assert "0 cells" in figure.get_suptitle()


# ---------------------------------------------------------------------------
# Threads, no screen, and what is imported
# ---------------------------------------------------------------------------

def test_figure_can_be_written_from_another_thread(tmp_path):
    outcome = {}

    def work():
        try:
            outcome["path"] = _write(tmp_path)
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()

    assert "error" not in outcome, outcome.get("error")
    assert _png_size(outcome["path"])[0] > 0


def _run_fresh_process(script, tmp_path, remove_display=True):
    """Run a script in a new Python process and return the finished process."""
    script_path = tmp_path / "script.py"
    script_path.write_text(textwrap.dedent(script))
    env = dict(os.environ)
    if remove_display:
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).parent)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    return subprocess.run(
        [sys.executable, str(script_path)], capture_output=True, text=True, env=env, timeout=300,
    )


def test_figure_is_written_in_a_process_without_a_display(tmp_path):
    script = f"""
        import threading
        from pathlib import Path

        import matplotlib
        import numpy as np
        from matplotlib import _pylab_helpers

        from bigfish_pypeline import qc, segmentation as seg
        from cellpose_standin import StandInModel

        def backend_setting():
            return dict.__getitem__(matplotlib.rcParams, "backend")

        backend_before = backend_setting()
        image = np.random.default_rng(0).poisson(40, (50, 70)).astype(np.uint16)
        result = seg.segment_cells(StandInModel(n_cells=2), image)

        outcome = {{}}
        def work():
            try:
                outcome["path"] = qc.write_cellpose_qc(
                    {str(tmp_path)!r}, "img", result, 0, seg.describe_pretreatment(), None)
            except BaseException as error:
                outcome["error"] = repr(error)
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()

        assert "error" not in outcome, outcome.get("error")
        assert Path(outcome["path"]).is_file()
        assert backend_setting() == backend_before, (backend_before, backend_setting())
        assert not _pylab_helpers.Gcf.get_all_fig_managers()
        print("ok")
    """
    done = _run_fresh_process(script, tmp_path)

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout
    assert (tmp_path / "qc" / "img_cellpose_qc.png").is_file()


def test_importing_the_module_does_not_load_cellpose_or_torch(tmp_path):
    script = """
        import sys
        import bigfish_pypeline.qc
        loaded = [name for name in ("cellpose", "torch", "plotly") if name in sys.modules]
        assert not loaded, loaded
        assert "matplotlib.pyplot" not in sys.modules
        print("ok")
    """
    done = _run_fresh_process(script, tmp_path, remove_display=False)

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout


# ---------------------------------------------------------------------------
# Elbow plot
# ---------------------------------------------------------------------------

SPOT_RADIUS_PX = detection.get_spot_radius_px(
    (200, 65, 65), ex=570, em=610, NA=1.45, RI=1.45, microscope="confocal"
)


@pytest.fixture(scope="module")
def rna_log():
    image, _, _ = make_image(n_spots=20, seed=2)
    return detection.filter_channel(image, SPOT_RADIUS_PX)["rna_log"]


@pytest.fixture(scope="module")
def automatic_value(rna_log):
    return detection.detect_spots(rna_log, SPOT_RADIUS_PX, threshold_mode="auto")["threshold"]


def _detected(rna_log, **kwargs):
    return detection.detect_spots(rna_log, SPOT_RADIUS_PX, **kwargs)


def _legend_texts(figure):
    return [text.get_text() for text in figure.axes[0].get_legend().get_texts()]


def test_elbow_path_is_in_the_qc_folder_and_uses_the_channel_index(tmp_path):
    assert qc.elbow_path(tmp_path, "img_01", 2) == tmp_path / "qc" / "img_01_ch2_elbow.png"
    assert qc.calibration_path(tmp_path) == tmp_path / "qc" / "calibration.png"


def test_elbow_plot_in_manual_mode(rna_log, automatic_value):
    detected = _detected(rna_log, threshold_mode="manual", threshold=11)
    figure = qc.draw_elbow_plot(detected, IMAGE, 2, "manual", channel_name="jim-exon")

    assert _legend_texts(figure) == [
        "Selected threshold = 11.0",
        f"Automatic threshold = {automatic_value:.1f} (not used)",
    ]
    axes = figure.axes[0]
    assert axes.get_title() == f"{IMAGE} | channel 2 (jim-exon) | manual threshold"
    assert axes.get_xlabel() == "Thresholds"
    assert axes.get_ylabel() == (
        "Natural log of candidate spots above each threshold\n"
        "(smoothed, before spots sharing a peak are merged)"
    )
    assert len(axes.lines) == 3  # the curve and two lines
    assert figure.get_size_inches()[0] > 0


def test_elbow_plot_in_auto_mode(rna_log, automatic_value):
    detected = _detected(rna_log, threshold_mode="auto")
    figure = qc.draw_elbow_plot(detected, IMAGE, 0, "auto")

    assert _legend_texts(figure) == [f"Selected threshold = {automatic_value:.1f}"]
    assert figure.axes[0].get_title() == f"{IMAGE} | channel 0 | automatic threshold"


def test_elbow_plot_in_auto_mode_with_a_lower_limit_not_reached(rna_log, automatic_value):
    limit = automatic_value - 5
    detected = _detected(rna_log, threshold_mode="auto", lower_limit=limit)
    figure = qc.draw_elbow_plot(detected, IMAGE, 0, "auto", lower_limit=limit)

    assert _legend_texts(figure) == [
        f"Selected threshold = {automatic_value:.1f}",
        f"Lower limit = {limit:.1f}",
    ]


def test_elbow_plot_in_auto_mode_raised_by_the_lower_limit(rna_log, automatic_value):
    limit = automatic_value + 10
    detected = _detected(rna_log, threshold_mode="auto", lower_limit=limit)
    figure = qc.draw_elbow_plot(detected, IMAGE, 0, "auto", lower_limit=limit)

    assert _legend_texts(figure) == [
        f"Selected threshold = {limit:.1f}",
        f"Lower limit = {limit:.1f}",
        f"Automatic threshold = {automatic_value:.1f} (raised to the lower limit)",
    ]


def test_elbow_plot_in_calibrated_mode(rna_log, automatic_value):
    detected = _detected(rna_log, threshold_mode="calibrated", threshold=24.25)
    figure = qc.draw_elbow_plot(detected, IMAGE, 1, "calibrated", lower_limit=12)

    assert _legend_texts(figure) == [
        "Selected threshold = 24.2",
        "Lower limit = 12.0",
        f"Automatic threshold = {automatic_value:.1f} (not used)",
    ]
    assert figure.axes[0].get_title().endswith("calibrated threshold")


def test_manual_value_outside_the_curve_stays_in_view(rna_log):
    detected = _detected(rna_log, threshold_mode="manual", threshold=10_000)
    figure = qc.draw_elbow_plot(detected, IMAGE, 1, "manual")

    assert figure.axes[0].get_xlim()[1] > 10_000


def test_elbow_plot_says_when_the_elbow_method_gives_no_value():
    thresholds = np.arange(10, dtype=float)
    detected = {
        "elbow_thresholds": thresholds, "elbow_counts": np.full(10, 3.0),
        "threshold": 4.0, "auto_threshold": None,
    }
    figure = qc.draw_elbow_plot(detected, IMAGE, 1, "manual")
    assert _legend_texts(figure) == ["Selected threshold = 4.0", "No automatic threshold found"]

    detected["threshold"] = None
    figure = qc.draw_elbow_plot(detected, IMAGE, 1, "auto")
    assert _legend_texts(figure) == ["No automatic threshold found"]


def test_elbow_title_names_the_image_channel_and_mode():
    assert qc.elbow_title("a", 3, "auto", "DAPI") == "a | channel 3 (DAPI) | automatic threshold"
    assert qc.elbow_title("a", 3, "manual") == "a | channel 3 | manual threshold"
    long_title = qc.elbow_title("x" * 120, 3, "calibrated", "DAPI")
    assert all(len(line) <= qc.ELBOW_TITLE_LINE_WIDTH for line in long_title.split("\n"))


def _write_elbow(folder, rna_log, mode="manual", **kwargs):
    detected_arguments = {"threshold": 11} if mode != "auto" else {}
    detected = _detected(rna_log, threshold_mode=mode, **detected_arguments)
    return qc.write_elbow_plot(folder, IMAGE, detected, 2, mode, **kwargs)


@pytest.mark.parametrize("mode", ["manual", "auto", "calibrated"])
def test_elbow_plot_is_written_as_a_png(tmp_path, rna_log, mode):
    path = _write_elbow(tmp_path, rna_log, mode, channel_name="jim-exon")

    assert path == tmp_path / "qc" / f"{IMAGE}_ch2_elbow.png"
    width, height = _png_size(path)
    assert width > 500 and height > 500
    assert [p.name for p in (tmp_path / "qc").iterdir()] == [path.name]


def test_no_elbow_values_writes_nothing(tmp_path):
    image, _, _ = make_image(n_spots=0, blank=True)
    blank_log = detection.filter_channel(image, SPOT_RADIUS_PX)["rna_log"]
    for mode in ("auto", "manual"):
        detected = _detected(blank_log, threshold_mode=mode, **({"threshold": 5} if mode == "manual" else {}))
        assert detected["elbow_thresholds"].size == 0
        assert qc.draw_elbow_plot(detected, IMAGE, 2, mode) is None
        assert qc.write_elbow_plot(tmp_path, IMAGE, detected, 2, mode) is None
    assert not (tmp_path / "qc").exists()


def test_elbow_values_not_asked_for_write_nothing(tmp_path, rna_log):
    detected = _detected(rna_log, threshold_mode="manual", threshold=11, elbow=False)

    assert detected["elbow_thresholds"] is None
    assert qc.write_elbow_plot(tmp_path, IMAGE, detected, 2, "manual") is None


def test_a_second_elbow_plot_replaces_the_first(tmp_path, rna_log):
    first = _write_elbow(tmp_path, rna_log, "manual")
    first_bytes = first.read_bytes()
    second = _write_elbow(tmp_path, rna_log, "auto")

    assert second == first
    assert second.read_bytes() != first_bytes


def test_failed_elbow_write_leaves_no_file(tmp_path, monkeypatch, rna_log):
    def fail(self, *args, **kwargs):
        Path(args[0]).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", fail)
    with pytest.raises(OSError):
        _write_elbow(tmp_path, rna_log)

    assert list((tmp_path / "qc").iterdir()) == []


def test_the_elbow_values_given_are_not_changed(tmp_path, rna_log):
    detected = _detected(rna_log, threshold_mode="manual", threshold=11)
    thresholds = detected["elbow_thresholds"].copy()
    counts = detected["elbow_counts"].copy()

    qc.write_elbow_plot(tmp_path, IMAGE, detected, 2, "manual")

    np.testing.assert_array_equal(detected["elbow_thresholds"], thresholds)
    np.testing.assert_array_equal(detected["elbow_counts"], counts)


# ---------------------------------------------------------------------------
# Calibration plot
# ---------------------------------------------------------------------------

def _table(n_images=6, channels=(2,), left_out=(), start=14.0):
    rows = []
    for channel in channels:
        for i in range(n_images):
            if i in left_out:
                rows.append((f"slide_{i + 1:02d}", channel, None, False, "no automatic threshold"))
            else:
                rows.append((f"slide_{i + 1:02d}", channel, start + channel + i % 3, True, ""))
    return outputs.make_calibration_table(rows)


def _tick_texts(axes):
    return [label.get_text() for label in axes.get_xticklabels()]


def test_calibration_plot_for_one_channel():
    table = _table(6)
    figure = qc.draw_calibration_plot(table, {2: 15.0})

    assert len(figure.axes) == 1
    assert _legend_texts(figure) == [
        "Automatic value of each image (6 images)",
        "Median used = 15.0",
    ]
    assert _tick_texts(figure.axes[0]) == [f"slide_{i:02d}" for i in range(1, 7)]
    assert figure.axes[0].get_title() == "Channel 2"


def test_calibration_plot_with_a_lower_limit_and_images_left_out():
    table = _table(8, left_out=(1, 5))
    figure = qc.draw_calibration_plot(
        table, {2: 16.0}, lower_limits={2: 12}, channel_names={2: "jim-exon"}
    )

    assert _legend_texts(figure) == [
        "Automatic value of each image (6 images)",
        "Median used = 16.0",
        "Lower limit = 12.0",
        "Left out of the median (2 images)",
    ]
    assert figure.axes[0].get_title() == "Channel 2 (jim-exon)"


def test_one_image_left_out_is_counted_in_the_singular():
    figure = qc.draw_calibration_plot(_table(4, left_out=(0,)), {2: 15.0})

    assert "Left out of the median (1 image)" in _legend_texts(figure)
    assert "Automatic value of each image (3 images)" in _legend_texts(figure)


def test_calibration_plot_for_several_channels():
    table = _table(5, channels=(1, 3), left_out=(2,))
    figure = qc.draw_calibration_plot(
        table, {1: 15.0, 3: 17.0}, lower_limits={3: 10}, channel_names={3: "DAPI"}
    )

    assert [axes.get_title() for axes in figure.axes] == ["Channel 1", "Channel 3 (DAPI)"]
    first = [text.get_text() for text in figure.axes[0].get_legend().get_texts()]
    second = [text.get_text() for text in figure.axes[1].get_legend().get_texts()]
    assert "Median used = 15.0" in first and "Lower limit = 10.0" not in " ".join(first)
    assert "Median used = 17.0" in second and "Lower limit = 10.0" in second
    assert figure.get_size_inches()[1] > qc.draw_calibration_plot(table[table.channel == 1], {1: 15.0}).get_size_inches()[1]


def test_a_channel_without_a_usable_value_says_so():
    table = _table(3, left_out=(0, 1, 2))
    figure = qc.draw_calibration_plot(table, {})

    assert _legend_texts(figure) == ["No usable median", "Left out of the median (3 images)"]


def test_images_are_numbered_above_thirty():
    names = qc.draw_calibration_plot(_table(qc.CALIBRATION_MAX_NAMED_IMAGES), {2: 15.0})
    numbers = qc.draw_calibration_plot(_table(qc.CALIBRATION_MAX_NAMED_IMAGES + 1), {2: 15.0})

    assert _tick_texts(names.axes[0])[0] == "slide_01"
    assert names.axes[0].get_xlabel() == "Image"
    numbers.canvas.draw()
    ticks = _tick_texts(numbers.axes[0])
    assert not any(text.startswith("slide") for text in ticks)
    assert all(text.lstrip("\u2212-").isdigit() for text in ticks if text)
    assert "number" in numbers.axes[0].get_xlabel()


def test_calibration_plot_with_nothing_to_show():
    table = _table(0)

    assert qc.draw_calibration_plot(table, {}) is None


def test_calibration_plot_is_written_as_a_png(tmp_path):
    table = _table(8, channels=(2, 3), left_out=(4,))
    path = qc.write_calibration_plot(tmp_path, table, {2: 15.0, 3: 16.0})

    assert path == tmp_path / "qc" / "calibration.png"
    assert _png_size(path)[0] > 500
    assert [p.name for p in (tmp_path / "qc").iterdir()] == ["calibration.png"]


def test_calibration_plot_with_forty_five_images_is_written(tmp_path):
    path = qc.write_calibration_plot(tmp_path, _table(45, left_out=(3, 40)), {2: 15.0})

    assert _png_size(path)[0] > 500


def test_empty_calibration_table_writes_nothing(tmp_path):
    assert qc.write_calibration_plot(tmp_path, _table(0), {}) is None
    assert not (tmp_path / "qc").exists()


def test_failed_calibration_write_leaves_no_file(tmp_path, monkeypatch):
    def fail(self, *args, **kwargs):
        Path(args[0]).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", fail)
    with pytest.raises(OSError):
        qc.write_calibration_plot(tmp_path, _table(4), {2: 15.0})

    assert list((tmp_path / "qc").iterdir()) == []


def test_the_calibration_table_given_is_not_changed(tmp_path):
    table = _table(6, left_out=(1,))
    before = table.copy()

    qc.write_calibration_plot(tmp_path, table, {2: 15.0})

    assert table.equals(before)


# ---------------------------------------------------------------------------
# Threads and no screen
# ---------------------------------------------------------------------------

def test_elbow_and_calibration_plots_can_be_written_from_another_thread(tmp_path, rna_log):
    outcome = {}

    def work():
        try:
            outcome["elbow"] = _write_elbow(tmp_path, rna_log)
            outcome["calibration"] = qc.write_calibration_plot(tmp_path, _table(5), {2: 15.0})
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()

    assert "error" not in outcome, outcome.get("error")
    assert _png_size(outcome["elbow"])[0] > 0
    assert _png_size(outcome["calibration"])[0] > 0


def test_elbow_and_calibration_plots_are_written_in_a_process_without_a_display(tmp_path):
    script = f"""
        import threading
        from pathlib import Path

        import matplotlib
        from matplotlib import _pylab_helpers

        from bigfish_pypeline import detection, outputs, qc
        from synthetic import make_image

        def backend_setting():
            return dict.__getitem__(matplotlib.rcParams, "backend")

        backend_before = backend_setting()
        radius = detection.get_spot_radius_px(
            (200, 65, 65), ex=570, em=610, NA=1.45, RI=1.45, microscope="confocal")
        image, _, _ = make_image(n_spots=20, seed=2)
        rna_log = detection.filter_channel(image, radius)["rna_log"]
        table = outputs.make_calibration_table(
            [("a", 2, 14.0, True, ""), ("b", 2, None, False, "no automatic threshold")])

        outcome = {{}}
        def work():
            try:
                for mode, extra in (("manual", dict(threshold=11)), ("auto", {{}})):
                    detected = detection.detect_spots(rna_log, radius, threshold_mode=mode, **extra)
                    outcome[mode] = qc.write_elbow_plot({str(tmp_path)!r}, "img", detected, 2, mode)
                outcome["calibration"] = qc.write_calibration_plot(
                    {str(tmp_path)!r}, table, {{2: 14.0}})
            except BaseException as error:
                outcome["error"] = repr(error)
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()

        assert "error" not in outcome, outcome.get("error")
        assert all(Path(outcome[key]).is_file() for key in ("manual", "auto", "calibration"))
        assert backend_setting() == backend_before, (backend_before, backend_setting())
        assert not _pylab_helpers.Gcf.get_all_fig_managers()
        print("ok")
    """
    done = _run_fresh_process(script, tmp_path)

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout
    assert (tmp_path / "qc" / "calibration.png").is_file()


# ---------------------------------------------------------------------------
# Detection plot
# ---------------------------------------------------------------------------

def _picture(shape=(60, 80), seed=0):
    return np.random.default_rng(seed).poisson(50, shape).astype(np.uint16)


def _positions(n, ndim=2, shape=(60, 80), seed=1):
    rng = np.random.default_rng(seed)
    columns = [rng.uniform(0, size, n) for size in ((10,) if ndim == 3 else ()) + shape]
    return np.column_stack(columns)


def _draw_detection(n_spots=40, n_clusters=3, **kwargs):
    arguments = dict(
        image=_picture(), spots=_positions(n_spots), image_name=IMAGE, channel=2,
        spot_radius_px=1.5,
    )
    if n_clusters is not None:
        arguments.update(clusters=_positions(n_clusters, seed=2), cluster_radius_px=6.0)
    arguments.update(kwargs)
    return qc.draw_detection_plot(**arguments)


def _detection_axes(figure):
    """The picture on the left and the one with the detections on the right."""
    left, right = figure.axes
    return left, right


def test_detection_path_is_in_the_qc_folder_and_uses_the_channel_index(tmp_path):
    assert qc.detection_path(tmp_path, "img_01", 2) == tmp_path / "qc" / "img_01_ch2_detection.png"


def test_detection_title_names_the_image_the_channel_and_the_counts():
    assert qc.detection_title("slide 3", 2, 692, 6, "jim-exon") == (
        "slide 3 | channel 2 (jim-exon) | 692 spots | 6 clusters"
    )
    assert qc.detection_title("slide 3", 2, 692) == "slide 3 | channel 2 | 692 spots"
    assert qc.detection_title("slide 3", 0, 1, 1) == "slide 3 | channel 0 | 1 spot | 1 cluster"
    assert qc.detection_title("slide 3", 2, 12, 0) == "slide 3 | channel 2 | 12 spots | 0 clusters"


@pytest.mark.parametrize("n_clusters", [None, 0, 2])
def test_detection_title_with_no_spots_says_so(n_clusters):
    assert qc.detection_title("slide 3", 2, 0, n_clusters, "jim-exon") == (
        "slide 3 | channel 2 (jim-exon) | no spots found"
    )


def test_detection_title_is_continued_on_a_new_line_when_long():
    title = qc.detection_title("long name " * 25, 2, 30, 4, "jim-exon")
    assert "\n" in title
    assert max(len(line) for line in title.splitlines()) <= qc.TITLE_LINE_WIDTH


def test_detection_plot_with_spots_and_clusters():
    figure = _draw_detection(n_spots=40, n_clusters=3, channel_name="jim-exon")

    left, right = _detection_axes(figure)
    assert figure._suptitle.get_text() == f"{IMAGE} | channel 2 (jim-exon) | 40 spots | 3 clusters"
    assert len(left.collections) == 0
    assert [type(collection) for collection in right.collections] == [
        EllipseCollection, PatchCollection,
    ]
    assert len(right.collections[0].get_offsets()) == 40
    assert len(right.collections[1].get_paths()) == 3
    assert "orange circles: spots" in right.get_title()
    assert "cyan outlines: clusters" in right.get_title()


def test_spots_are_circles_of_the_spot_radius_and_clusters_are_outlines_without_fill():
    figure = _draw_detection(spot_radius_px=(2.2, 1.9, 1.9))

    circles, shapes = _detection_axes(figure)[1].collections
    # matplotlib keeps the half-width and half-height of each ellipse, which are the radius.
    assert np.allclose(circles._widths, 1.9) and np.allclose(circles._heights, 1.9)
    assert circles.get_facecolor().shape[0] == 0 or circles.get_facecolor()[0][3] == 0
    assert np.allclose(circles.get_edgecolor()[0][:3], (1.0, 165 / 255, 0.0))
    assert shapes.get_facecolor().shape[0] == 0 or shapes.get_facecolor()[0][3] == 0
    assert np.allclose(shapes.get_edgecolor()[0], (0.0, 1.0, 1.0, 1.0))
    # Five corners, each 6 px from the cluster's position (x, y).
    for path, (y, x) in zip(shapes.get_paths(), _positions(3, seed=2)):
        corners = path.vertices[:5]
        assert np.allclose(np.hypot(corners[:, 0] - x, corners[:, 1] - y), 6.0)


def test_circles_are_placed_at_x_and_y_of_the_spots():
    spots = np.array([[10.0, 20.0], [30.0, 5.0]])
    figure = _draw_detection(spots=spots, n_clusters=None)

    offsets = _detection_axes(figure)[1].collections[0].get_offsets()
    assert np.array_equal(np.asarray(offsets), [[20.0, 10.0], [5.0, 30.0]])


def test_detection_plot_with_spots_only():
    figure = _draw_detection(n_clusters=None)

    _, right = _detection_axes(figure)
    assert figure._suptitle.get_text() == f"{IMAGE} | channel 2 | 40 spots"
    assert [type(collection) for collection in right.collections] == [EllipseCollection]
    assert "cluster" not in right.get_title()


def test_clusters_switched_on_but_none_found_draws_spots_only_and_counts_zero():
    figure = _draw_detection(clusters=np.zeros((0, 3)), cluster_radius_px=None)

    _, right = _detection_axes(figure)
    assert figure._suptitle.get_text().endswith("40 spots | 0 clusters")
    assert len(right.collections) == 1


@pytest.mark.parametrize("empty", [np.zeros((0, 2)), np.zeros((0, 3)), np.array([]), []])
def test_detection_plot_with_no_spots_draws_the_image_alone(empty):
    figure = _draw_detection(spots=empty, n_clusters=None, channel_name="jim-exon")

    assert len(figure.axes) == 1
    assert len(figure.axes[0].collections) == 0
    assert len(figure.axes[0].images) == 1
    assert figure._suptitle.get_text() == f"{IMAGE} | channel 2 (jim-exon) | no spots found"


def test_no_spots_with_clusters_on_still_says_no_spots_found():
    figure = _draw_detection(spots=np.zeros((0, 3)), clusters=np.zeros((0, 3)))

    assert figure._suptitle.get_text().endswith("no spots found")


def test_two_dimensional_and_three_dimensional_coordinates_give_the_same_picture():
    spots_2d = _positions(25)
    spots_3d = np.column_stack([np.linspace(0, 9, 25), spots_2d])
    clusters_2d = _positions(3, seed=2)
    clusters_3d = np.column_stack([[1.0, 4.0, 7.0], clusters_2d])

    flat = _draw_detection(spots=spots_2d, clusters=clusters_2d, cluster_radius_px=6.0)
    deep = _draw_detection(spots=spots_3d, clusters=clusters_3d, cluster_radius_px=6.0)

    assert np.array_equal(
        flat.axes[1].collections[0].get_offsets(), deep.axes[1].collections[0].get_offsets()
    )
    assert np.array_equal(
        flat.axes[1].collections[1].get_paths()[0].vertices,
        deep.axes[1].collections[1].get_paths()[0].vertices,
    )


def test_integer_coordinates_are_accepted():
    figure = _draw_detection(spots=np.array([[3, 4], [10, 20]], dtype=np.int64), n_clusters=None)

    assert len(figure.axes[1].collections[0].get_offsets()) == 2


def test_coordinates_with_the_wrong_number_of_columns_are_refused():
    with pytest.raises(ValueError, match="two columns"):
        _draw_detection(spots=np.zeros((5, 5)), n_clusters=None)
    with pytest.raises(ValueError, match="clusters"):
        _draw_detection(clusters=np.zeros((2, 1)), cluster_radius_px=6.0)


def test_clusters_without_a_radius_are_refused():
    with pytest.raises(ValueError, match="cluster_radius_px"):
        _draw_detection(clusters=_positions(2), cluster_radius_px=None)


def test_detection_plot_is_drawn_on_a_2d_image_only():
    with pytest.raises(ValueError, match="2D"):
        _draw_detection(image=np.zeros((4, 60, 80), dtype=np.uint16))


def test_projection_of_a_3d_channel_is_its_maximum():
    stack = np.zeros((4, 5, 6), dtype=np.uint16)
    stack[2, 1, 3] = 900
    stack[0, 1, 3] = 100
    stack[3, 4, 5] = 50

    projection = qc.project_for_detection(stack)

    assert projection.shape == (5, 6) and projection.dtype == np.uint16
    assert projection[1, 3] == 900 and projection[4, 5] == 50 and projection[0, 0] == 0


def test_a_2d_channel_is_its_own_projection():
    image = _picture()

    assert qc.project_for_detection(image) is image


def test_projection_of_other_shapes_is_refused():
    with pytest.raises(ValueError, match="2 or 3 dimensions"):
        qc.project_for_detection(np.zeros((2, 3, 4, 5)))


def test_detection_plot_of_a_3d_channel_through_its_projection(tmp_path):
    stack = np.random.default_rng(3).poisson(40, (6, 50, 70)).astype(np.uint16)
    spots = _positions(30, ndim=3, shape=(50, 70))

    path = qc.write_detection_plot(
        tmp_path, IMAGE, qc.project_for_detection(stack), spots, 1, (2.0, 1.5, 1.5)
    )

    assert path == tmp_path / "qc" / f"{IMAGE}_ch1_detection.png"
    assert _png_size(path)[0] > 0


def test_picture_is_stretched_between_the_lowest_value_and_the_999th_percentile():
    image = np.arange(10000, dtype=np.uint16).reshape(100, 100)
    levels = qc._stretch_for_detection(image)

    assert levels.dtype == np.uint8
    assert levels.min() == 0 and levels.max() == 255
    assert levels[0, 0] == 0
    # Everything above the 99.9th percentile is as bright as it gets.
    assert (levels[-1, -4:] == 255).all()
    # A flat image does not divide by zero.
    assert not qc._stretch_for_detection(np.full((5, 5), 7, dtype=np.uint16)).any()


def test_the_image_and_positions_given_are_not_changed():
    image = _picture()
    spots = _positions(30)
    clusters = _positions(3, seed=2)
    before = (image.copy(), spots.copy(), clusters.copy())

    _draw_detection(image=image, spots=spots, clusters=clusters, cluster_radius_px=6.0)

    assert all(np.array_equal(a, b) for a, b in zip(before, (image, spots, clusters)))


def test_figure_follows_the_shape_of_the_image():
    wide = _draw_detection(image=_picture((40, 160)))
    tall = _draw_detection(image=_picture((200, 50)))
    square = _draw_detection(image=_picture((100, 100)))

    assert wide.get_figwidth() == tall.get_figwidth() == square.get_figwidth() == 20
    assert wide.get_figheight() < square.get_figheight() < tall.get_figheight()
    assert tall.get_figheight() <= 16


def _write_detection(folder, **kwargs):
    arguments = dict(
        run_folder=folder, image_name=IMAGE, image=_picture(), spots=_positions(40), channel=2,
        spot_radius_px=1.5, clusters=_positions(3, seed=2), cluster_radius_px=6.0,
    )
    arguments.update(kwargs)
    return qc.write_detection_plot(**arguments)


@pytest.mark.parametrize("clusters", [True, False])
def test_detection_plot_is_written_as_a_png(tmp_path, clusters):
    path = _write_detection(tmp_path, **({} if clusters else dict(clusters=None)))

    assert path == tmp_path / "qc" / f"{IMAGE}_ch2_detection.png"
    assert _png_size(path) == (2000, round(float(np.clip(10 * 60 / 80 + 1.2, 3, 16)) * 100))
    assert sorted(file.name for file in (tmp_path / "qc").iterdir()) == [path.name]


def test_detection_plot_with_no_spots_is_written(tmp_path):
    path = _write_detection(tmp_path, spots=np.zeros((0, 2)), clusters=None)

    assert _png_size(path)[0] == 1000


def test_a_second_detection_plot_replaces_the_first(tmp_path):
    first = _write_detection(tmp_path)
    first_bytes = first.read_bytes()

    _write_detection(tmp_path, spots=_positions(5, seed=9))

    assert first.read_bytes() != first_bytes


def test_failed_detection_write_leaves_no_file(tmp_path, monkeypatch):
    def broken(self, *args, **kwargs):
        Path(args[0]).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", broken)

    with pytest.raises(OSError):
        _write_detection(tmp_path)

    assert list((tmp_path / "qc").iterdir()) == []


def test_a_large_picture_with_many_spots_is_drawn_as_two_collections():
    figure = _draw_detection(
        image=_picture((256, 256)), spots=_positions(20000, shape=(256, 256)),
    )

    assert len(figure.axes[1].collections) == 2
    assert len(figure.axes[1].patches) == 0


def test_detection_plot_can_be_written_from_another_thread(tmp_path):
    outcome = {}

    def work():
        try:
            outcome["path"] = _write_detection(tmp_path)
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()

    assert "error" not in outcome, outcome.get("error")
    assert _png_size(outcome["path"])[0] > 0


def test_detection_plot_is_written_in_a_process_without_a_display(tmp_path):
    script = f"""
        import threading
        from pathlib import Path

        import matplotlib
        import numpy as np
        from matplotlib import _pylab_helpers

        from bigfish_pypeline import qc

        def backend_setting():
            return dict.__getitem__(matplotlib.rcParams, "backend")

        backend_before = backend_setting()
        rng = np.random.default_rng(0)
        image = rng.poisson(40, (5, 50, 70)).astype(np.uint16)
        spots = np.column_stack([rng.integers(0, 5, 30), rng.uniform(0, 50, 30), rng.uniform(0, 70, 30)])
        outcome = {{}}
        def work():
            try:
                picture = qc.project_for_detection(image)
                outcome["both"] = qc.write_detection_plot(
                    {str(tmp_path)!r}, "img", picture, spots, 2, 1.5,
                    clusters=spots[:2], cluster_radius_px=5)
                outcome["none"] = qc.write_detection_plot(
                    {str(tmp_path)!r}, "empty", picture, spots[:0], 2, 1.5)
                outcome["tif"] = qc.write_reference_spot({str(tmp_path)!r}, "img", 2, image[0])
            except BaseException as error:
                outcome["error"] = repr(error)
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()

        assert "error" not in outcome, outcome.get("error")
        assert all(Path(path).is_file() for path in outcome.values())
        assert backend_setting() == backend_before, (backend_before, backend_setting())
        assert not _pylab_helpers.Gcf.get_all_fig_managers()
        print("ok")
    """
    done = _run_fresh_process(script, tmp_path)

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout
    assert (tmp_path / "qc" / "img_ch2_detection.png").is_file()
    assert (tmp_path / "qc" / "empty_ch2_detection.png").is_file()
    assert (tmp_path / "qc" / "img_ch2_referencespot.tif").is_file()


# ---------------------------------------------------------------------------
# Reference spot
# ---------------------------------------------------------------------------

def test_reference_spot_path_is_in_the_qc_folder_and_uses_the_channel_index(tmp_path):
    assert qc.reference_spot_path(tmp_path, "img_01", 2) == (
        tmp_path / "qc" / "img_01_ch2_referencespot.tif"
    )


@pytest.mark.parametrize("dtype", [np.uint16, np.float32, np.float64, np.int64])
@pytest.mark.parametrize("shape", [(5, 7, 7), (9, 9)])
def test_reference_spot_is_read_back_with_the_same_values_and_data_type(tmp_path, dtype, shape):
    reference = (np.random.default_rng(0).uniform(0, 3000, shape)).astype(dtype)

    path = qc.write_reference_spot(tmp_path, IMAGE, 2, reference)

    assert path == tmp_path / "qc" / f"{IMAGE}_ch2_referencespot.tif"
    found = tifffile.imread(path)
    assert found.dtype == reference.dtype
    assert found.shape == reference.shape
    assert np.array_equal(found, reference)
    assert sorted(file.name for file in (tmp_path / "qc").iterdir()) == [path.name]


def test_no_reference_spot_writes_nothing(tmp_path):
    assert qc.write_reference_spot(tmp_path, IMAGE, 2, None) is None
    assert not (tmp_path / "qc").exists()


def test_no_reference_spot_leaves_a_file_from_an_earlier_run_as_it_is(tmp_path):
    path = qc.write_reference_spot(tmp_path, IMAGE, 2, np.ones((3, 3), dtype=np.uint16))
    before = path.read_bytes()

    assert qc.write_reference_spot(tmp_path, IMAGE, 2, None) is None

    assert path.read_bytes() == before


def test_a_second_reference_spot_replaces_the_first(tmp_path):
    qc.write_reference_spot(tmp_path, IMAGE, 2, np.ones((3, 3), dtype=np.uint16))
    path = qc.write_reference_spot(tmp_path, IMAGE, 2, np.full((4, 4), 7, dtype=np.uint16))

    assert np.array_equal(tifffile.imread(path), np.full((4, 4), 7))


def test_failed_reference_spot_write_leaves_no_file(tmp_path, monkeypatch):
    def broken(file, data, *args, **kwargs):
        file.write(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(tifffile, "imwrite", broken)

    with pytest.raises(OSError):
        qc.write_reference_spot(tmp_path, IMAGE, 2, np.ones((3, 3), dtype=np.uint16))

    assert list((tmp_path / "qc").iterdir()) == []


def test_reference_spot_of_the_crop_equals_the_v1_file(crop_path, crop_reference_folder, tmp_path):
    """The crop with the v1 reference settings (top-hat 5 px, manual threshold 18)."""
    voxel_size = (200, 65, 65)
    optics = dict(ex=570, em=610, NA=1.45, RI=1.45, microscope="confocal")
    spot_radius_px = detection.get_spot_radius_px(voxel_size, **optics)
    spot_radius_nm = detection.get_spot_radius_nm(voxel_size, **optics)
    image = tifffile.imread(crop_path)[:, 2]
    filtered = detection.filter_channel(image, spot_radius_px, bg_radius=5, bg_method="tophat")
    spots = detection.detect_spots(
        filtered["rna_log"], spot_radius_px, threshold_mode="manual", threshold=18, elbow=False,
    )["spots"]
    seed = decomposition.get_seed(0, "sypN_DAPI_Phal_jim-exon_crop", 2)
    result = decomposition.decompose_dense_regions(
        filtered["rna"], spots, voxel_size, spot_radius_nm, alpha=0.5, beta=1, seed=seed
    )

    path = qc.write_reference_spot(
        tmp_path, "sypN_DAPI_Phal_jim-exon_crop", 2, result["reference_spot"]
    )

    expected = tifffile.imread(
        crop_reference_folder / "general_manual18_subpixel-off"
        / "sypN_DAPI_Phal_jim-exon_crop_ch2_referencespot.tif"
    )
    found = tifffile.imread(path)
    assert path.name == "sypN_DAPI_Phal_jim-exon_crop_ch2_referencespot.tif"
    assert found.dtype == expected.dtype
    assert found.shape == expected.shape
    assert np.array_equal(found, expected)


# ---------------------------------------------------------------------------
# Final QC
# ---------------------------------------------------------------------------

FINAL_IMAGE = "slide 3 é"
VOXEL_UM2 = 0.065 ** 2


def _final_data(n_cells=6, n_spots=60, n_clusters=2, shape=(60, 80), ndim=2, subpixel=False,
                snr=False, intensity=False, seed=3):
    """
    Tables and labels as the run folder has them: square cells in a grid, spots
    placed at random (some on the cells), clusters of some of the spots.
    Returns (picture, spots, clusters, cells, labels).
    """
    rng = np.random.default_rng(seed)
    height, width = shape
    labels = np.zeros(shape, dtype=np.uint32)
    across = int(np.ceil(np.sqrt(max(n_cells, 1))))
    tile_y, tile_x = height // across, width // across
    for number in range(n_cells):
        row, column = divmod(number, across)
        labels[row * tile_y + 1:(row + 1) * tile_y - 1,
               column * tile_x + 1:(column + 1) * tile_x - 1] = number + 1

    y = rng.integers(0, height, n_spots)
    x = rng.integers(0, width, n_spots)
    cell_id = labels[y, x].astype(np.int64)
    cell_id[cell_id == 0] = -1
    cluster_id = np.full(n_spots, -1)
    cluster_id[: min(n_spots, 4 * n_clusters)] = np.arange(min(n_spots, 4 * n_clusters)) // 4
    spots = {"image": FINAL_IMAGE, "channel": 2, "channel_name": "jim-exon",
             "spot_id": np.arange(n_spots)}
    if ndim == 3:
        spots["z_px"] = rng.integers(0, 10, n_spots)
    spots.update({"y_px": y, "x_px": x})
    if subpixel:
        spots["y_sub_px"] = y + rng.uniform(-0.4, 0.4, n_spots)
        spots["x_sub_px"] = x + rng.uniform(-0.4, 0.4, n_spots)
    spots.update({"cluster_id": cluster_id, "cell_id": cell_id})
    if snr:
        spots["snr"] = rng.uniform(1, 5, n_spots)
    if intensity:
        spots["log_intensity"] = rng.uniform(5, 9, n_spots)
    spots = pd.DataFrame(spots)

    cluster_rows = {"image": FINAL_IMAGE, "channel": 2, "channel_name": "jim-exon",
                    "cluster_id": np.arange(n_clusters)}
    if ndim == 3:
        cluster_rows["z_px"] = np.full(n_clusters, 4.5)
    cluster_rows.update({
        "y_px": rng.uniform(0, height, n_clusters), "x_px": rng.uniform(0, width, n_clusters),
        "n_spots": np.full(n_clusters, 4), "cell_id": rng.integers(-1, n_cells + 1, n_clusters),
    })
    clusters = pd.DataFrame(cluster_rows)

    ids = np.arange(1, n_cells + 1)
    in_cluster = np.array([((cell_id == number) & (cluster_id >= 0)).sum() for number in ids], dtype=int)
    counts = np.array([(cell_id == number).sum() for number in ids], dtype=int)
    area = np.array([(labels == number).sum() for number in ids], dtype=int)
    cells = pd.DataFrame({
        "image": FINAL_IMAGE, "channel": 2, "channel_name": "jim-exon",
        "cell_id": ids, "area_px": area, "area_um2": area * VOXEL_UM2,
        "centroid_y_px": 1.0, "centroid_x_px": 1.0, "touches_border": False,
        "n_spots": counts, "n_spots_in_clusters": in_cluster,
        "n_spots_outside_clusters": counts - in_cluster,
        "n_clusters": np.arange(n_cells) % 3, "mean_spots_per_cluster": np.nan,
    })
    picture = rng.poisson(40, shape).astype(np.uint16)
    if ndim == 3:
        picture = np.stack([picture, picture // 2, picture // 3])
    return picture, spots, clusters, cells, labels


def _png_figure(data, **kwargs):
    picture, spots, clusters, cells, labels = data
    return qc.draw_final_qc(picture, spots, clusters, cells, labels, FINAL_IMAGE, 2, **kwargs)


def _title(figure):
    return figure.get_suptitle()


def _html_figure(data, **kwargs):
    picture, spots, clusters, cells, labels = data
    return qc.draw_final_html(picture, spots, clusters, cells, labels, FINAL_IMAGE, 2, **kwargs)


def _write_html(folder, data, **kwargs):
    picture, spots, clusters, cells, labels = data
    kwargs.setdefault("plotly_script", "shared")
    return qc.write_final_html(folder, FINAL_IMAGE, picture, spots, clusters, cells, labels, 2, **kwargs)


def _write_png(folder, data, **kwargs):
    picture, spots, clusters, cells, labels = data
    return qc.write_final_qc(folder, FINAL_IMAGE, picture, spots, clusters, cells, labels, 2, **kwargs)


def _trace(figure, name, kind=None):
    found = [t for t in figure.data if t.name == name and (kind is None or t.mode == kind)]
    assert len(found) == 1, [t.name for t in figure.data]
    return found[0]


def _page_data(path):
    """The traces written in a page, as dicts, with their typed arrays decoded."""
    text = Path(path).read_text(encoding="utf-8")
    start = text.index("Plotly.newPlot(")
    start = text.index("[", start)
    traces, _ = json.JSONDecoder().raw_decode(text[start:])

    def decode(value):
        if isinstance(value, dict) and "bdata" in value:
            array = np.frombuffer(base64.b64decode(value["bdata"]), dtype=np.dtype(value["dtype"]))
            if "shape" in value:
                array = array.reshape([int(n) for n in str(value["shape"]).split(",")])
            return array
        if isinstance(value, dict):
            return {key: decode(item) for key, item in value.items()}
        return value

    return [decode(trace) for trace in traces]


def _without_big_scripts(text):
    """The page without its script blocks of more than a megabyte (plotly's own)."""
    return re.sub(
        r"<script[^>]*>.*?</script>",
        lambda block: "" if len(block.group(0)) > 1_000_000 else block.group(0),
        text, flags=re.S,
    )


def test_final_paths_are_in_the_qc_folder_and_use_the_channel_index(tmp_path):
    assert qc.final_png_path(tmp_path, "img_01", 2) == tmp_path / "qc" / "img_01_ch2_final.png"
    assert qc.final_html_path(tmp_path, "img_01", 2) == tmp_path / "qc" / "img_01_ch2_final.html"
    assert qc.plotly_script_path(tmp_path) == tmp_path / "qc" / "plotly.min.js"


# The title

def test_final_title_names_the_image_the_channel_and_the_counts():
    assert qc.final_title("slide 3", 2, 692, 6, 44, "jim-exon") == (
        "slide 3 | channel 2 (jim-exon) | 44 cells | 692 spots | 6 clusters"
    )
    assert qc.final_title("a", 0, 1, 1, 1) == "a | channel 0 | 1 cell | 1 spot | 1 cluster"


def test_final_title_without_cells_says_so():
    for n_cells in (None, 0):
        assert "no cells" in qc.final_title("a", 2, 5, 1, n_cells)


def test_final_title_without_clusters_or_spots():
    assert qc.final_title("a", 2, 5, None, 3).endswith("3 cells | 5 spots")
    assert qc.final_title("a", 2, 5, 0, 3).endswith("5 spots | 0 clusters")
    assert qc.final_title("a", 2, 0, 0, 3).endswith("3 cells | no spots found")


def test_final_title_says_when_the_text_on_the_cells_is_left_out():
    title = qc.final_title("a", 2, 5, 1, 1300, text_left_out=True)
    assert "1300 cells (too many to number, over 300)" in title


def test_final_title_is_continued_on_a_new_line_when_long():
    title = qc.final_title("x" * 120, 2, 692, 6, 44, "jim-exon")
    assert "\n" in title


# The figure

def test_figure_names_each_mark_in_its_legend():
    figure = _png_figure(_final_data())
    labels = [text.get_text() for text in figure.axes[0].get_legend().get_texts()]
    assert labels == [
        "Cell outline", "Spot inside a cell", "Spot outside the cells", "Cluster of spots",
        "On each cell: its number, then its number of spots",
    ]


def test_each_cell_has_its_index_and_the_spot_count_of_the_cells_table():
    picture, spots, clusters, cells, labels = _final_data(n_cells=6)
    # The table's number, not a count of the spots, is written on the cell.
    cells = cells.copy()
    cells["n_spots"] = [7, 0, 12, 3, 99, 5]
    figure = qc.draw_final_qc(picture, spots, clusters, cells, labels, FINAL_IMAGE, 2)

    texts = sorted(text.get_text() for text in figure.axes[0].texts)
    assert texts == sorted(["1: 7", "2: 0", "3: 12", "4: 3", "5: 99", "6: 5"])


def test_text_is_inside_its_cell():
    picture, spots, clusters, cells, labels = _final_data(n_cells=6)
    figure = qc.draw_final_qc(picture, spots, clusters, cells, labels, FINAL_IMAGE, 2)

    for text in figure.axes[0].texts:
        x, y = text.get_position()
        assert labels[int(round(y)), int(round(x))] == int(text.get_text().split(":")[0])


def test_text_of_a_curved_cell_stays_inside_it():
    labels = np.zeros((40, 40), dtype=np.uint32)
    labels[5:35, 5:12] = 1
    labels[28:35, 5:35] = 1
    picture, spots, clusters, cells, _ = _final_data(n_cells=1, shape=(40, 40))
    figure = qc.draw_final_qc(picture, spots, clusters, cells, labels, FINAL_IMAGE, 2)

    x, y = figure.axes[0].texts[0].get_position()
    assert labels[int(round(y)), int(round(x))] == 1


def test_figure_title_names_the_counts():
    figure = _png_figure(_final_data(n_cells=6, n_spots=60, n_clusters=2), channel_name="jim-exon")
    assert _title(figure) == f"{FINAL_IMAGE} | channel 2 (jim-exon) | 6 cells | 60 spots | 2 clusters"


def test_spots_in_and_outside_cells_are_drawn_apart():
    picture, spots, clusters, cells, labels = _final_data()
    figure = qc.draw_final_qc(picture, spots, clusters, cells, labels, FINAL_IMAGE, 2)
    inside = spots["cell_id"] >= 0
    assert inside.any() and (~inside).any()

    spot_sets = [c for c in figure.axes[0].collections if len(c.get_offsets()) in
                 (inside.sum(), (~inside).sum())]
    sizes = sorted(len(c.get_offsets()) for c in spot_sets)
    assert sizes == sorted([int(inside.sum()), int((~inside).sum())])
    cluster_sets = [c for c in figure.axes[0].collections
                    if len(c.get_offsets()) == len(clusters) and c not in spot_sets]
    assert len(cluster_sets) == 1


def test_cell_outlines_are_one_collection_with_a_polygon_for_each_cell():
    figure = _png_figure(_final_data(n_cells=6))
    lines = [c for c in figure.axes[0].collections if isinstance(c, LineCollection)]
    assert len(lines) == 1
    assert len(lines[0].get_segments()) == 6


def test_clusters_off_gives_no_cluster_marks_and_no_cluster_count():
    picture, spots, _, cells, labels = _final_data()
    figure = qc.draw_final_qc(picture, spots, None, cells, labels, FINAL_IMAGE, 2)

    assert "cluster" not in _title(figure)
    legend = [t.get_text() for t in figure.axes[0].get_legend().get_texts()]
    assert "Cluster of spots" not in legend


def test_clusters_on_but_none_found_counts_zero():
    picture, spots, clusters, cells, labels = _final_data()
    figure = qc.draw_final_qc(picture, spots, clusters.iloc[:0], cells, labels, FINAL_IMAGE, 2)
    assert _title(figure).endswith("0 clusters")


def test_figure_without_labels_has_no_outlines_no_text_and_says_so():
    picture, spots, clusters, cells, _ = _final_data()
    figure = qc.draw_final_qc(picture, spots, clusters, cells, None, FINAL_IMAGE, 2)
    axes = figure.axes[0]

    assert "no cells" in _title(figure)
    assert not axes.texts
    assert not [c for c in axes.collections if isinstance(c, LineCollection)]
    legend = [t.get_text() for t in axes.get_legend().get_texts()]
    assert "Spot" in legend and "Cell outline" not in legend


def test_labels_without_any_cell_count_as_no_cells():
    picture, spots, clusters, cells, labels = _final_data()
    figure = qc.draw_final_qc(picture, spots, clusters, cells, np.zeros_like(labels), FINAL_IMAGE, 2)
    assert "no cells" in _title(figure)


def test_figure_with_no_spots_still_shows_the_cells():
    picture, spots, clusters, cells, labels = _final_data()
    figure = qc.draw_final_qc(
        picture, spots.iloc[:0], clusters.iloc[:0], cells, labels, FINAL_IMAGE, 2
    )
    assert "no spots found" in _title(figure)
    assert len(figure.axes[0].texts) == 6


def test_figure_with_no_tables_at_all():
    picture = _final_data()[0]
    figure = qc.draw_final_qc(picture, None, None, None, None, FINAL_IMAGE, 2)
    assert _title(figure).endswith("no cells | no spots found")


def test_more_than_300_cells_leave_the_text_out_and_the_title_says_so():
    data = _final_data(n_cells=320, n_spots=500, shape=(300, 300))
    figure = _png_figure(data)

    assert not figure.axes[0].texts
    assert "320 cells (too many to number, over 300)" in _title(figure)
    assert len([c for c in figure.axes[0].collections if isinstance(c, LineCollection)]) == 1


def test_exactly_300_cells_keep_the_text():
    figure = _png_figure(_final_data(n_cells=300, n_spots=100, shape=(300, 300)))
    assert len(figure.axes[0].texts) == 300
    assert "too many" not in _title(figure)


def test_three_dimensional_channel_is_projected_and_positions_use_y_and_x():
    picture, spots, clusters, cells, labels = _final_data(ndim=3)
    figure = qc.draw_final_qc(picture, spots, clusters, cells, labels, FINAL_IMAGE, 2)
    flat = qc.draw_final_qc(picture.max(axis=0), spots, clusters, cells, labels, FINAL_IMAGE, 2)

    np.testing.assert_array_equal(figure.axes[0].images[0].get_array(), flat.axes[0].images[0].get_array())
    inside = spots["cell_id"] >= 0
    offsets = [c.get_offsets() for c in figure.axes[0].collections
               if len(c.get_offsets()) == inside.sum()][0]
    np.testing.assert_allclose(offsets, spots.loc[inside, ["x_px", "y_px"]].to_numpy())


def test_subpixel_positions_are_used_when_the_table_has_them():
    picture, spots, clusters, cells, labels = _final_data(subpixel=True)
    figure = qc.draw_final_qc(picture, spots, clusters, cells, labels, FINAL_IMAGE, 2)
    inside = spots["cell_id"] >= 0
    offsets = [c.get_offsets() for c in figure.axes[0].collections
               if len(c.get_offsets()) == inside.sum()][0]
    np.testing.assert_allclose(offsets, spots.loc[inside, ["x_sub_px", "y_sub_px"]].to_numpy())

    html_figure = _html_figure((picture, spots, clusters, cells, labels))
    shown = np.concatenate([
        np.column_stack([t.x, t.y]) for t in html_figure.data if t.name == "Spots inside cells"
    ])
    assert len(shown) == inside.sum()
    expected = spots.loc[inside, ["x_sub_px", "y_sub_px"]].to_numpy()
    np.testing.assert_allclose(
        shown[np.lexsort(shown.T)], expected[np.lexsort(expected.T)], atol=1e-3
    )


def test_a_spot_row_without_a_subpixel_value_keeps_its_pixel_position():
    picture, spots, clusters, cells, labels = _final_data(subpixel=True)
    spots.loc[0, ["y_sub_px", "x_sub_px"]] = np.nan
    view = qc._final_view(picture, spots, clusters, cells, labels)
    np.testing.assert_allclose(view.spot_yx[0], spots.loc[0, ["y_px", "x_px"]].to_numpy(dtype=float))


def test_cell_of_a_spot_is_found_from_the_labels_when_the_table_has_no_cell_column():
    picture, spots, clusters, cells, labels = _final_data()
    expected = spots["cell_id"].to_numpy()
    view = qc._final_view(picture, spots.drop(columns="cell_id"), clusters, cells, labels)
    np.testing.assert_array_equal(view.spot_cell, expected)


def test_labels_of_another_size_are_refused():
    picture, spots, clusters, cells, labels = _final_data()
    with pytest.raises(ValueError, match="label image"):
        qc.draw_final_qc(picture, spots, clusters, cells, labels[:-1], FINAL_IMAGE, 2)


def test_final_picture_of_other_shapes_is_refused():
    picture, spots, clusters, cells, labels = _final_data()
    with pytest.raises(ValueError):
        qc.draw_final_qc(picture[None, None], spots, clusters, cells, labels, FINAL_IMAGE, 2)


def test_the_tables_and_labels_given_are_not_changed():
    data = _final_data(snr=True, subpixel=True)
    picture, spots, clusters, cells, labels = data
    before = [picture.copy(), spots.copy(), clusters.copy(), cells.copy(), labels.copy()]
    _png_figure(data)
    _html_figure(data)
    np.testing.assert_array_equal(picture, before[0])
    for given, kept in zip((spots, clusters, cells), before[1:4]):
        pd.testing.assert_frame_equal(given, kept)
    np.testing.assert_array_equal(labels, before[4])


# The PNG file

@pytest.mark.parametrize("variant", ["cells", "no_cells", "no_spots", "clusters_off", "three_d"])
def test_final_png_is_written(tmp_path, variant):
    picture, spots, clusters, cells, labels = _final_data(ndim=3 if variant == "three_d" else 2)
    if variant == "no_cells":
        cells, labels = None, None
    if variant == "no_spots":
        spots, clusters = spots.iloc[:0], clusters.iloc[:0]
    if variant == "clusters_off":
        clusters = None
    path = qc.write_final_qc(tmp_path, FINAL_IMAGE, picture, spots, clusters, cells, labels, 2)

    assert path == tmp_path / "qc" / f"{FINAL_IMAGE}_ch2_final.png"
    width, height = _png_size(path)
    assert width == 2000 and 500 <= height <= 2000


def test_final_png_with_more_than_300_cells_is_written(tmp_path):
    path = _write_png(tmp_path, _final_data(n_cells=320, n_spots=500, shape=(300, 300)))
    assert _png_size(path)[0] == 2000


def test_final_png_is_written_without_loading_plotly(tmp_path):
    script = f"""
        import sys
        from bigfish_pypeline import qc
        from test_qc import _final_data, _write_png
        _write_png({str(tmp_path)!r}, _final_data())
        assert "plotly" not in sys.modules
        print("ok")
    """
    done = _run_fresh_process(script, tmp_path, remove_display=False)
    assert done.returncode == 0, done.stderr


def test_no_temporary_file_is_left_behind_by_the_png(tmp_path):
    _write_png(tmp_path, _final_data())
    _write_png(tmp_path, _final_data(n_cells=0))
    assert [p.name for p in (tmp_path / "qc").iterdir()] == [f"{FINAL_IMAGE}_ch2_final.png"]


def test_failed_png_write_leaves_no_file(tmp_path, monkeypatch):
    def fail(self, *args, **kwargs):
        Path(args[0]).write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", fail)
    with pytest.raises(OSError):
        _write_png(tmp_path, _final_data())
    assert list((tmp_path / "qc").iterdir()) == []


# The page: what it holds

def test_page_holds_the_counts_of_the_cells_table(tmp_path):
    data = _final_data(n_cells=6)
    cells = data[3].copy()
    cells["n_spots"] = [7, 0, 12, 3, 99, 5]
    cells["n_spots_in_clusters"] = [1, 0, 2, 3, 4, 5]
    cells["n_spots_outside_clusters"] = [6, 0, 10, 0, 95, 0]
    cells["n_clusters"] = [1, 0, 2, 3, 4, 5]
    path = _write_html(tmp_path, (data[0], data[1], data[2], cells, data[4]))

    traces = _page_data(path)
    hover = [t for t in traces if t.get("mode") == "markers" and t["name"] == "Cell outlines"][0]
    values = np.asarray(hover["customdata"])
    assert "Spots in clusters" in hover["hovertemplate"] and "Area" in hover["hovertemplate"]
    for row in values:
        expected = cells[cells["cell_id"] == row[0]].iloc[0]
        assert list(row[:5]) == [expected["cell_id"], expected["n_spots"],
                                 expected["n_spots_in_clusters"],
                                 expected["n_spots_outside_clusters"], expected["n_clusters"]]
        assert row[5] == expected["area_px"]
        assert row[6] == pytest.approx(expected["area_um2"], rel=1e-5)
    assert set(values[:, 0]) == set(cells["cell_id"])


def test_cell_hover_text_says_what_each_number_is():
    figure = _html_figure(_final_data())
    template = _trace(figure, "Cell outlines", "markers").hovertemplate
    assert template == (
        "<b>Cell %{customdata[0]:.0f}</b><br>Spots: %{customdata[1]:.0f}<br>"
        "Spots in clusters: %{customdata[2]:.0f}<br>Spots outside clusters: %{customdata[3]:.0f}<br>"
        "Clusters: %{customdata[4]:.0f}<br>Area: %{customdata[5]:,.0f} px "
        "(%{customdata[6]:.1f} µm²)<extra></extra>"
    )


def test_every_cell_can_be_hovered():
    data = _final_data(n_cells=6)
    figure = _html_figure(data)
    hover = _trace(figure, "Cell outlines", "markers")
    assert set(np.asarray(hover.customdata)[:, 0]) == set(range(1, 7))
    # Each point lies inside the cell it names.
    labels = data[4]
    for (cell, *_), x, y in zip(np.asarray(hover.customdata), hover.x, hover.y):
        assert labels[int(round(y)), int(round(x))] == cell


def test_cell_hover_without_a_cells_table_gives_the_number_and_the_spots_counted():
    picture, spots, clusters, cells, labels = _final_data()
    figure = qc.draw_final_html(picture, spots, clusters, None, labels, FINAL_IMAGE, 2)
    hover = _trace(figure, "Cell outlines", "markers")
    assert hover.hovertemplate == (
        "<b>Cell %{customdata[0]:.0f}</b><br>Spots: %{customdata[1]:.0f}<extra></extra>"
    )
    counted = {int(row[0]): row[1] for row in np.asarray(hover.customdata)}
    for number in range(1, 7):
        assert counted[number] == (spots["cell_id"] == number).sum()


def test_spot_hover_gives_its_number_cell_and_cluster():
    figure = _html_figure(_final_data(snr=True, intensity=True))
    spots_in_clusters = [t for t in figure.data if t.name == "Spots inside cells"
                         and "Cluster: " in t.hovertemplate]
    assert spots_in_clusters
    assert spots_in_clusters[0].hovertemplate == (
        "<b>Spot %{customdata[0]:.0f}</b><br>Cell: %{customdata[1]:.0f}<br>"
        "Cluster: %{customdata[2]:.0f}<br>SNR: %{customdata[3]:.2f}<br>"
        "Log intensity: %{customdata[4]:.2f}<extra></extra>"
    )
    outside = [t for t in figure.data if t.name == "Spots outside cells"
               and "Not in a cluster" in t.hovertemplate]
    assert outside[0].hovertemplate == (
        "<b>Spot %{customdata[0]:.0f}</b><br>Outside the cells<br>Not in a cluster<br>"
        "SNR: %{customdata[1]:.2f}<br>Log intensity: %{customdata[2]:.2f}<extra></extra>"
    )


def test_spot_hover_values_are_those_of_the_table():
    picture, spots, clusters, cells, labels = _final_data(snr=True)
    figure = _html_figure((picture, spots, clusters, cells, labels))
    seen = 0
    for trace in figure.data:
        if not trace.name.startswith("Spots"):
            continue
        for row, x, y in zip(np.asarray(trace.customdata), trace.x, trace.y):
            expected = spots.iloc[int(row[0])]
            assert (x, y) == (pytest.approx(expected["x_px"]), pytest.approx(expected["y_px"]))
            assert row[-1] == pytest.approx(expected["snr"], rel=1e-5)
            seen += 1
    assert seen == len(spots)


def test_spot_hover_without_the_optional_columns_leaves_them_out():
    figure = _html_figure(_final_data(snr=False, intensity=False))
    for trace in figure.data:
        if trace.name.startswith("Spots"):
            assert "SNR" not in trace.hovertemplate and "intensity" not in trace.hovertemplate


def test_spot_hover_with_clusters_off_has_no_cluster_line():
    picture, spots, clusters, cells, labels = _final_data()
    figure = qc.draw_final_html(picture, spots, None, cells, labels, FINAL_IMAGE, 2)
    assert not [t for t in figure.data if t.name == "Clusters"]
    for trace in figure.data:
        if trace.name.startswith("Spots"):
            assert "luster" not in trace.hovertemplate


def test_cluster_hover_gives_its_number_spots_and_cell():
    picture, spots, clusters, cells, labels = _final_data()
    clusters = clusters.copy()
    clusters["cell_id"] = [3, -1]
    figure = qc.draw_final_html(picture, spots, clusters, cells, labels, FINAL_IMAGE, 2)
    trace = _trace(figure, "Clusters")
    assert list(trace.hovertext) == [
        "<b>Cluster 0</b><br>4 spots<br>In cell 3", "<b>Cluster 1</b><br>4 spots<br>Outside the cells",
    ]
    assert trace.hovertemplate == "%{hovertext}<extra></extra>"


def test_every_trace_is_webgl_and_the_outlines_are_one_trace():
    figure = _html_figure(_final_data(n_cells=40, n_spots=200, shape=(120, 120)))
    assert {t.type for t in figure.data} == {"scattergl"}
    assert len([t for t in figure.data if t.mode == "lines"]) == 1


def test_the_legend_switches_the_spots_the_clusters_and_the_outlines():
    figure = _html_figure(_final_data())
    entries = [t.name for t in figure.data if t.showlegend is not False]
    assert entries == ["Cell outlines", "Spots inside cells", "Spots outside cells", "Clusters"]
    # The pieces of one kind (the hover points of the cells, the spots in clusters) go with it.
    for name in ("Cell outlines", "Spots inside cells", "Spots outside cells"):
        assert len({t.legendgroup for t in figure.data if t.name == name}) == 1


def test_page_without_cells_has_spots_and_clusters_only():
    picture, spots, clusters, _, _ = _final_data()
    figure = qc.draw_final_html(picture, spots, clusters, None, None, FINAL_IMAGE, 2)
    assert sorted({t.name for t in figure.data}) == ["Clusters", "Spots"]
    assert "no cells" in figure.layout.title.text
    assert sum(len(t.x) for t in figure.data if t.name == "Spots") == len(spots)


def test_page_with_no_spots_and_clusters_off_has_the_outlines_and_the_picture():
    picture, spots, _, cells, labels = _final_data()
    figure = qc.draw_final_html(picture, spots.iloc[:0], None, cells, labels, FINAL_IMAGE, 2)
    assert sorted({t.name for t in figure.data}) == ["Cell outlines"]
    assert len(figure.layout.images) == 1
    assert "no spots found" in figure.layout.title.text


def test_page_title_names_the_counts():
    figure = _html_figure(_final_data(), channel_name="jim-exon")
    assert figure.layout.title.text == (
        f"{FINAL_IMAGE} | channel 2 (jim-exon) | 6 cells | 60 spots | 2 clusters"
    )


def test_page_of_a_three_dimensional_channel_with_subpixel_positions():
    figure = _html_figure(_final_data(ndim=3, subpixel=True, snr=True))
    assert sum(len(t.x) for t in figure.data if t.name.startswith("Spots")) == 60


def test_picture_is_8_bit_grey_at_full_size_up_to_2048():
    data = _final_data(shape=(60, 80))
    image = _html_figure(data).layout.images[0]
    assert (image.sizex, image.sizey) == (80, 60)
    assert image.source.startswith("data:image/png;base64,")
    from PIL import Image
    shown = Image.open(io.BytesIO(base64.b64decode(image.source.split(",", 1)[1])))
    assert shown.mode == "L" and shown.size == (80, 60)
    np.testing.assert_array_equal(np.asarray(shown), qc._stretch_for_display(data[0])[..., 0])


def test_a_larger_picture_is_reduced_but_keeps_its_coordinates():
    rng = np.random.default_rng(0)
    picture = rng.poisson(40, (2500, 3000)).astype(np.uint16)
    spots = pd.DataFrame({"spot_id": [0], "y_px": [2400], "x_px": [2900], "cluster_id": [-1],
                          "cell_id": [-1]})
    figure = qc.draw_final_html(picture, spots, None, None, None, FINAL_IMAGE, 2)
    image = figure.layout.images[0]
    from PIL import Image
    shown = Image.open(io.BytesIO(base64.b64decode(image.source.split(",", 1)[1])))

    assert shown.size == (2048, round(2500 * 2048 / 3000))
    assert (image.sizex, image.sizey) == (3000, 2500)
    assert list(figure.layout.xaxis.range) == [-0.5, 2999.5]
    assert (figure.data[0].x[0], figure.data[0].y[0]) == (2900, 2400)


def test_picture_of_exactly_2048_is_not_reduced():
    picture = np.random.default_rng(0).poisson(40, (64, 2048)).astype(np.uint16)
    image = qc.draw_final_html(picture, None, None, None, None, FINAL_IMAGE, 2).layout.images[0]
    from PIL import Image
    assert Image.open(io.BytesIO(base64.b64decode(image.source.split(",", 1)[1]))).size == (2048, 64)


def test_labels_of_another_size_are_refused_for_the_page():
    picture, spots, clusters, cells, labels = _final_data()
    with pytest.raises(ValueError, match="label image"):
        qc.draw_final_html(picture, spots, clusters, cells, labels[:, :-1], FINAL_IMAGE, 2)


# The page: the file

@pytest.mark.parametrize("variant", ["cells", "no_cells", "no_spots", "clusters_off", "three_d", "subpixel"])
@pytest.mark.parametrize("script", ["shared", "embedded"])
def test_final_page_is_written(tmp_path, variant, script):
    picture, spots, clusters, cells, labels = _final_data(
        ndim=3 if variant == "three_d" else 2, subpixel=variant == "subpixel", snr=True)
    if variant == "no_cells":
        cells, labels = None, None
    if variant == "no_spots":
        spots, clusters = spots.iloc[:0], clusters.iloc[:0]
    if variant == "clusters_off":
        clusters = None
    path = qc.write_final_html(
        tmp_path, FINAL_IMAGE, picture, spots, clusters, cells, labels, 2, plotly_script=script
    )

    assert path == tmp_path / "qc" / f"{FINAL_IMAGE}_ch2_final.html"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<html>") or text.startswith("<!doctype html>")
    assert f"<title>{FINAL_IMAGE} | channel 2 | final QC</title>" in text
    assert "Plotly.newPlot" in text


def test_a_page_holds_the_script_itself_unless_told_otherwise(tmp_path):
    picture, spots, clusters, cells, labels = _final_data()
    path = qc.write_final_html(tmp_path, FINAL_IMAGE, picture, spots, clusters, cells, labels, 2)
    assert [file.name for file in (tmp_path / "qc").iterdir()] == [path.name]
    assert path.stat().st_size > 4_000_000


def test_the_shared_script_is_one_copy_used_by_every_page_of_the_folder(tmp_path):
    from plotly.offline import get_plotlyjs

    first = _write_html(tmp_path, _final_data())
    second = qc.write_final_html(
        tmp_path, "other", *_final_data()[:1], None, None, None, None, 2, plotly_script="shared"
    )
    script = tmp_path / "qc" / "plotly.min.js"

    assert sorted(p.name for p in (tmp_path / "qc").iterdir()) == sorted(
        ["plotly.min.js", first.name, second.name])
    assert script.read_bytes() == get_plotlyjs().encode("utf-8")
    for page in (first, second):
        text = page.read_text(encoding="utf-8")
        assert '<script charset="utf-8" src="plotly.min.js"></script>' in text
        assert len(text) < 1_000_000


def test_embedded_is_the_default():
    import inspect
    assert inspect.signature(qc.write_final_html).parameters["plotly_script"].default == "embedded"


def test_the_embedded_script_is_in_the_page_and_no_script_file_is_written(tmp_path):
    path = _write_html(tmp_path, _final_data(), plotly_script="embedded")

    assert [p.name for p in (tmp_path / "qc").iterdir()] == [path.name]
    text = path.read_text(encoding="utf-8")
    assert len(text) > 4_000_000
    assert "<script src=" not in text
    assert "plotly.min.js" not in _without_big_scripts(text)


def test_an_unknown_way_of_loading_the_script_is_refused(tmp_path):
    with pytest.raises(ValueError, match="plotly_script"):
        _write_html(tmp_path, _final_data(), plotly_script="cdn")
    assert not (tmp_path / "qc").exists()


@pytest.mark.parametrize("script", ["shared", "embedded"])
def test_the_page_needs_no_address_on_the_internet(tmp_path, script):
    path = _write_html(tmp_path, _final_data(), plotly_script=script)
    text = _without_big_scripts(path.read_text(encoding="utf-8"))

    assert not re.findall(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", text)
    assert not re.findall(r"""url\(\s*["']?https?:""", text)
    before_the_data = text.split("Plotly.newPlot")[0].replace("http://www.w3.org", "")
    assert "http://" not in before_the_data and "https://" not in before_the_data
    assert "cdn.plot.ly" not in text and "cdnjs" not in text


def test_a_cut_short_copy_of_the_script_is_replaced(tmp_path):
    folder = tmp_path / "qc"
    folder.mkdir()
    (folder / "plotly.min.js").write_bytes(b"half a script")
    _write_html(tmp_path, _final_data())
    from plotly.offline import get_plotlyjs
    assert (folder / "plotly.min.js").read_bytes() == get_plotlyjs().encode("utf-8")


def test_a_whole_copy_of_the_script_is_not_written_again(tmp_path):
    _write_html(tmp_path, _final_data())
    script = tmp_path / "qc" / "plotly.min.js"
    os.utime(script, (1_000_000_000, 1_000_000_000))
    _write_html(tmp_path, _final_data())
    assert script.stat().st_mtime == 1_000_000_000


def test_two_processes_writing_pages_into_one_folder_leave_a_whole_script(tmp_path):
    from plotly.offline import get_plotlyjs

    expected = hashlib.sha256(get_plotlyjs().encode("utf-8")).hexdigest()
    script = f"""
        import sys, time
        from bigfish_pypeline import qc
        from test_qc import _final_data
        start = float(sys.argv[1])
        data = _final_data(seed=int(sys.argv[2]))
        while time.time() < start:
            pass
        qc.write_final_html({str(tmp_path / "run")!r}, "image" + sys.argv[2], data[0], data[1],
                            data[2], data[3], data[4], 2, plotly_script="shared")
        print("ok")
    """
    import time
    script_path = tmp_path / "writer.py"
    script_path.write_text(textwrap.dedent(script))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parent) + os.pathsep + env.get("PYTHONPATH", "")
    start = time.time() + 6
    processes = [
        subprocess.Popen([sys.executable, str(script_path), str(start), str(number)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        for number in range(3)
    ]
    for process in processes:
        out, err = process.communicate(timeout=300)
        assert process.returncode == 0, err

    folder = tmp_path / "run" / "qc"
    assert hashlib.sha256((folder / "plotly.min.js").read_bytes()).hexdigest() == expected
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        ["plotly.min.js"] + [f"image{n}_ch2_final.html" for n in range(3)])


def test_a_second_page_replaces_the_first(tmp_path):
    first = _write_html(tmp_path, _final_data(n_cells=6))
    first_text = first.read_text(encoding="utf-8")
    second = _write_html(tmp_path, _final_data(n_cells=0))
    assert second == first
    assert second.read_text(encoding="utf-8") != first_text


def test_failed_page_write_leaves_no_file(tmp_path, monkeypatch):
    def fail(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(qc.os, "replace", fail)
    with pytest.raises(OSError):
        _write_html(tmp_path, _final_data(), plotly_script="embedded")
    assert list((tmp_path / "qc").iterdir()) == []


def test_failed_script_write_leaves_no_file(tmp_path, monkeypatch):
    def fail(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(qc.os, "replace", fail)
    with pytest.raises(OSError):
        _write_html(tmp_path, _final_data(), plotly_script="shared")
    assert list((tmp_path / "qc").iterdir()) == []


def test_failed_page_write_after_the_script_leaves_only_the_whole_script(tmp_path, monkeypatch):
    real = os.replace

    def fail_for_the_page(source, target):
        if str(target).endswith(".html"):
            raise OSError("disk full")
        real(source, target)

    monkeypatch.setattr(qc.os, "replace", fail_for_the_page)
    with pytest.raises(OSError):
        _write_html(tmp_path, _final_data())
    assert [p.name for p in (tmp_path / "qc").iterdir()] == ["plotly.min.js"]


@pytest.mark.parametrize("script", ["shared", "embedded"])
def test_final_page_and_figure_can_be_written_from_another_thread(tmp_path, script):
    outcome = {}

    def work():
        try:
            outcome["page"] = _write_html(tmp_path, _final_data(), plotly_script=script)
            outcome["png"] = _write_png(tmp_path, _final_data())
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()

    assert "error" not in outcome, outcome.get("error")
    assert outcome["page"].is_file() and _png_size(outcome["png"])[0] > 0


def test_importing_the_module_does_not_load_plotly(tmp_path):
    script = """
        import sys
        import bigfish_pypeline.qc
        assert "plotly" not in sys.modules
        print("ok")
    """
    done = _run_fresh_process(script, tmp_path, remove_display=False)
    assert done.returncode == 0, done.stderr


def test_final_qc_is_written_in_a_process_without_a_display(tmp_path):
    script = f"""
        import threading
        from pathlib import Path

        import matplotlib
        from matplotlib import _pylab_helpers

        from bigfish_pypeline import qc
        from test_qc import _final_data

        def backend_setting():
            return dict.__getitem__(matplotlib.rcParams, "backend")

        backend_before = backend_setting()
        picture, spots, clusters, cells, labels = _final_data(ndim=3, snr=True)
        outcome = {{}}
        def work():
            try:
                outcome["png"] = qc.write_final_qc(
                    {str(tmp_path)!r}, "img", picture, spots, clusters, cells, labels, 2)
                outcome["shared"] = qc.write_final_html(
                    {str(tmp_path)!r}, "img", picture, spots, clusters, cells, labels, 2)
                outcome["embedded"] = qc.write_final_html(
                    {str(tmp_path / "alone")!r}, "img", picture, spots, clusters, cells, labels, 2,
                    plotly_script="embedded")
            except BaseException as error:
                outcome["error"] = repr(error)
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()

        assert "error" not in outcome, outcome.get("error")
        assert all(Path(path).is_file() for path in outcome.values())
        assert backend_setting() == backend_before, (backend_before, backend_setting())
        assert not _pylab_helpers.Gcf.get_all_fig_managers()
        print("ok")
    """
    done = _run_fresh_process(script, tmp_path)

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout
    assert (tmp_path / "qc" / "img_ch2_final.png").is_file()
    assert (tmp_path / "qc" / "img_ch2_final.html").is_file()
    assert (tmp_path / "alone" / "qc" / "img_ch2_final.html").is_file()


def test_a_full_size_view_is_drawn_with_one_outline_trace_and_webgl_spots():
    data = _final_data(n_cells=1300, n_spots=37000, n_clusters=270, shape=(2048, 2048))
    figure = _html_figure(data)

    assert {t.type for t in figure.data} == {"scattergl"}
    assert len([t for t in figure.data if t.mode == "lines"]) == 1
    assert sum(len(t.x) for t in figure.data if t.name.startswith("Spots")) == 37000


# Paths of an image's QC files


def test_channel_qc_paths(tmp_path):
    paths = qc.channel_qc_paths(tmp_path, "slide 3", 2)
    assert [path.name for path in paths] == [
        "slide 3_ch2_elbow.png", "slide 3_ch2_detection.png", "slide 3_ch2_referencespot.tif",
        "slide 3_ch2_final.png", "slide 3_ch2_final.html",
    ]
    assert all(path.parent == tmp_path / qc.QC_FOLDER_NAME for path in paths)
    assert outputs.QC_FOLDER_NAME == qc.QC_FOLDER_NAME


# ---------------------------------------------------------------------------
# Final QC: cells left out of the cells table, very large cell numbers, cluster marks
# ---------------------------------------------------------------------------

DROPPED_CELLS = (2, 5)


def _with_cells_dropped(data, dropped=DROPPED_CELLS):
    """
    The data as the runner has it with `drop_border_cells` on: the cells table
    and the cell of each spot and cluster leave out the dropped cells, while the
    label image still holds them.
    """
    picture, spots, clusters, cells, labels = data
    spots, clusters = spots.copy(), clusters.copy()
    spots.loc[spots["cell_id"].isin(dropped), "cell_id"] = -1
    clusters.loc[clusters["cell_id"].isin(dropped), "cell_id"] = -1
    cells = cells[~cells["cell_id"].isin(dropped)].reset_index(drop=True)
    return picture, spots, clusters, cells, labels


def _kept_cells(dropped=DROPPED_CELLS, n_cells=6):
    return [number for number in range(1, n_cells + 1) if number not in dropped]


def test_final_png_leaves_out_the_cells_that_the_cells_table_leaves_out():
    data = _with_cells_dropped(_final_data(n_cells=6))
    labels = data[4]
    figure = _png_figure(data)
    axes = figure.axes[0]

    assert "4 cells" in _title(figure) and "6 cells" not in _title(figure)
    texts = [text.get_text() for text in axes.texts]
    assert sorted(int(text.split(":")[0]) for text in texts) == _kept_cells()
    outlines = [c for c in axes.collections if isinstance(c, LineCollection)][0]
    segments = outlines.get_segments()
    assert len(segments) == 4
    for segment in segments:
        y, x = segment[:, 1].mean(), segment[:, 0].mean()
        assert labels[int(round(y)), int(round(x))] in _kept_cells()


def test_final_html_leaves_out_the_cells_that_the_cells_table_leaves_out():
    data = _with_cells_dropped(_final_data(n_cells=6))
    labels = data[4]
    figure = _html_figure(data)

    title = figure.layout.title.text
    assert "4 cells" in title and "6 cells" not in title
    outline = _trace(figure, "Cell outlines", "lines")
    x, y = np.asarray(outline.x, dtype=float), np.asarray(outline.y, dtype=float)
    gaps = np.flatnonzero(np.isnan(x))
    polygons = [part for part in np.split(np.column_stack([x, y]), gaps) if len(part[~np.isnan(part[:, 0])])]
    assert len(polygons) == 4
    for polygon in polygons:
        polygon = polygon[~np.isnan(polygon[:, 0])]
        assert labels[int(round(polygon[:, 1].mean())), int(round(polygon[:, 0].mean()))] in _kept_cells()
    hover = _trace(figure, "Cell outlines", "markers")
    assert sorted(set(np.asarray(hover.customdata)[:, 0])) == _kept_cells()
    for x_point, y_point in zip(hover.x, hover.y):
        assert labels[int(round(y_point)), int(round(x_point))] in _kept_cells()


def test_the_page_of_a_run_with_dropped_cells_holds_only_the_kept_cells(tmp_path):
    path = _write_html(tmp_path, _with_cells_dropped(_final_data(n_cells=6)))

    traces = _page_data(path)
    hover = [t for t in traces if t.get("mode") == "markers" and t["name"] == "Cell outlines"][0]
    assert sorted(set(np.asarray(hover["customdata"])[:, 0])) == _kept_cells()
    assert "4 cells" in Path(path).read_text(encoding="utf-8")


def test_a_spot_whose_cell_is_not_drawn_is_shown_outside_the_cells():
    picture, spots, clusters, cells, labels = _final_data(n_cells=6)
    # The spots table still names the dropped cells.
    cells = cells[~cells["cell_id"].isin(DROPPED_CELLS)]
    leaked = spots["cell_id"].isin(DROPPED_CELLS)
    assert leaked.any()
    view = qc._final_view(picture, spots, clusters, cells, labels)

    assert (view.spot_cell[leaked.to_numpy()] == -1).all()
    assert set(view.spot_cell[view.spot_cell >= 0]) <= set(_kept_cells())
    assert set(view.ids) == set(_kept_cells())


def test_an_empty_cells_table_draws_no_cells():
    picture, spots, clusters, cells, labels = _final_data(n_cells=6)
    spots = spots.assign(cell_id=-1)
    empty = cells.iloc[:0]
    figure = _png_figure((picture, spots, clusters, empty, labels))

    assert "no cells" in _title(figure)
    assert not figure.axes[0].texts
    assert not [c for c in figure.axes[0].collections if isinstance(c, LineCollection)]
    html_figure = _html_figure((picture, spots, clusters, empty, labels))
    assert "no cells" in html_figure.layout.title.text
    assert not [t for t in html_figure.data if t.name == "Cell outlines"]


def test_without_a_cells_table_every_cell_of_the_label_image_is_drawn():
    picture, spots, clusters, cells, labels = _final_data(n_cells=6)
    figure = qc.draw_final_qc(picture, spots, clusters, None, labels, FINAL_IMAGE, 2)

    assert "6 cells" in _title(figure)
    assert len(figure.axes[0].texts) == 6


def _with_cell_numbers(data, new_number):
    """The same data with each cell number k replaced by new_number(k)."""
    picture, spots, clusters, cells, labels = data
    numbers = np.arange(1, 7)
    table = np.zeros(7, dtype=np.int64)
    table[1:] = [new_number(k) for k in numbers]
    renumbered = table[labels.astype(np.int64)].astype(np.uint32)

    def mapped(column):
        column = column.to_numpy()
        return np.where(column > 0, table[np.clip(column, 0, 6)], column)

    spots, clusters, cells = spots.copy(), clusters.copy(), cells.copy()
    spots["cell_id"] = mapped(spots["cell_id"])
    clusters["cell_id"] = mapped(clusters["cell_id"])
    cells["cell_id"] = mapped(cells["cell_id"])
    return (picture, spots, clusters, cells, renumbered), table


def _large_numbers(k):
    return 100_000_000 + 7 * k


def _peak_bytes(function):
    import tracemalloc

    tracemalloc.start()
    try:
        function()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_cells_with_very_large_numbers_are_drawn_like_the_same_cells_numbered_from_1():
    small = _final_data(n_cells=6)
    large, table = _with_cell_numbers(small, _large_numbers)
    small_figure, large_figure = _png_figure(small), _png_figure(large)

    assert _title(small_figure) == _title(large_figure)
    small_axes, large_axes = small_figure.axes[0], large_figure.axes[0]
    small_texts = sorted(text.get_text() for text in small_axes.texts)
    large_texts = sorted(text.get_text() for text in large_axes.texts)
    assert [t.split(": ")[1] for t in sorted(small_texts, key=lambda t: int(t.split(":")[0]))] == \
        [t.split(": ")[1] for t in sorted(large_texts, key=lambda t: int(t.split(":")[0]))]
    assert sorted(int(t.split(":")[0]) for t in large_texts) == [_large_numbers(k) for k in range(1, 7)]
    small_outlines = [c for c in small_axes.collections if isinstance(c, LineCollection)][0]
    large_outlines = [c for c in large_axes.collections if isinstance(c, LineCollection)][0]
    assert len(small_outlines.get_segments()) == len(large_outlines.get_segments()) == 6
    for first, second in zip(small_outlines.get_segments(), large_outlines.get_segments()):
        np.testing.assert_allclose(first, second)

    small_html, large_html = _html_figure(small), _html_figure(large)
    np.testing.assert_array_equal(
        _trace(small_html, "Cell outlines", "lines").x, _trace(large_html, "Cell outlines", "lines").x
    )
    small_hover = np.asarray(_trace(small_html, "Cell outlines", "markers").customdata)
    large_hover = np.asarray(_trace(large_html, "Cell outlines", "markers").customdata)
    np.testing.assert_allclose(small_hover[:, 1:], large_hover[:, 1:], rtol=1e-6)
    np.testing.assert_array_equal(large_hover[:, 0], table[small_hover[:, 0].astype(int)])
    large_spot_cells = np.concatenate([
        np.asarray(t.customdata)[:, 1] for t in large_html.data
        if t.name == "Spots inside cells" and "Cell: " in t.hovertemplate
    ])
    assert set(large_spot_cells) <= {float(_large_numbers(k)) for k in range(1, 7)}


def test_spot_counts_per_cell_do_not_depend_on_the_cell_numbers():
    small = _final_data(n_cells=6)
    large, _ = _with_cell_numbers(small, _large_numbers)
    no_table = lambda data: qc._final_view(data[0], data[1], data[2], None, data[4])

    np.testing.assert_array_equal(
        no_table(small).cell_values["n_spots"], no_table(large).cell_values["n_spots"]
    )


def test_a_cell_numbered_100_million_needs_no_more_memory_than_one_numbered_1():
    picture, spots, clusters, cells, labels = _final_data(n_cells=6, shape=(300, 400))
    one = np.where(labels == 1, 1, 0).astype(np.uint32)
    huge = np.where(labels == 1, 100_000_000, 0).astype(np.uint32)
    spots = spots.assign(cell_id=-1)

    def build(image):
        return lambda: qc._final_view(picture, spots, clusters, None, image)

    peak_one, peak_huge = _peak_bytes(build(one)), _peak_bytes(build(huge))
    assert peak_huge < peak_one + 1_000_000
    assert peak_huge < 20_000_000

    def draw_png():
        qc.draw_final_qc(picture, spots, clusters, None, huge, FINAL_IMAGE, 2)

    def draw_html():
        qc.draw_final_html(picture, spots, clusters, None, huge, FINAL_IMAGE, 2)

    for draw in (draw_png, draw_html):
        assert _peak_bytes(draw) < 150_000_000


def test_very_large_cell_numbers_are_written_as_png_and_html(tmp_path):
    large, _ = _with_cell_numbers(_final_data(n_cells=6), _large_numbers)

    assert _png_size(_write_png(tmp_path, large))[0] > 0
    assert _write_html(tmp_path, large).is_file()


def test_the_cell_number_in_the_hover_text_is_exact_above_16_million():
    large, _ = _with_cell_numbers(_final_data(n_cells=6), lambda k: 123_456_789 + k)
    hover = _trace(_html_figure(large), "Cell outlines", "markers")

    assert set(np.asarray(hover.customdata)[:, 0]) == {123_456_789.0 + k for k in range(1, 7)}


def _final_cluster_marks(figure):
    axes = figure.axes[0]
    marks = [c for c in axes.collections
             if len(c.get_offsets()) == 2 and c.get_paths() and c.get_sizes().size
             and c.get_sizes()[0] > 50]
    assert len(marks) == 1
    return marks[0]


def test_clusters_are_outlines_without_fill_in_the_final_png():
    figure = _png_figure(_final_data())
    marks = _final_cluster_marks(figure)

    assert marks.get_facecolor().shape[0] == 0 or marks.get_facecolor()[0][3] == 0
    assert np.allclose(marks.get_edgecolor()[0], (0.0, 1.0, 1.0, 1.0))
    handle = [h for h in figure.axes[0].get_legend().legend_handles if h.get_label() == "Cluster of spots"][0]
    assert handle.get_markerfacecolor() in ("none", (0, 0, 0, 0))
    assert handle.get_markeredgecolor() == "cyan"


def test_clusters_are_outlines_without_fill_in_the_final_html():
    trace = _trace(_html_figure(_final_data()), "Clusters")

    assert trace.marker.symbol == "pentagon-open"
    assert trace.marker.color == "cyan"
    assert trace.marker.line.color == "cyan"
    assert "rgba" not in str(trace.marker.color)


def test_clusters_are_outlines_without_fill_in_the_detection_plot():
    figure = _draw_detection(n_spots=40, n_clusters=3)
    shapes = _detection_axes(figure)[1].collections[1]

    assert isinstance(shapes, PatchCollection)
    assert shapes.get_facecolor().shape[0] == 0 or (shapes.get_facecolor()[:, 3] == 0).all()
    assert np.allclose(shapes.get_edgecolor()[0], (0.0, 1.0, 1.0, 1.0))


# ---------------------------------------------------------------------------
# Cellpose QC figure: wording
# ---------------------------------------------------------------------------

def test_the_first_panel_says_it_shows_the_image_after_pre_treatment():
    figure = qc.draw_cellpose_qc(_segmentation(2), IMAGE, 0, PRETREATMENT, None)
    titles = [axes.get_title() for axes in figure.axes]

    assert titles[0] == "image after pre-treatment"
    assert "original image" not in titles
    assert titles[1:] == ["predicted outlines", "predicted masks", "predicted cell pose"]


def test_the_figure_without_a_diameter_says_the_image_is_used_at_its_own_scale():
    figure = qc.draw_cellpose_qc(_segmentation(2), IMAGE, 0, PRETREATMENT, None)

    assert "no diameter set (image used at its own scale)" in figure.get_suptitle()
    assert "chosen by Cellpose" not in figure.get_suptitle()


# ---------------------------------------------------------------------------
# Calibration plot: images raised to the lower limit
# ---------------------------------------------------------------------------

def _table_with_elbow_values(n_images=6, raised=(1, 3), channels=(2,), left_out=(), drop=4.0):
    """A calibration table with the `elbow_threshold` column that the runner writes."""
    table = _table(n_images, channels=channels, left_out=left_out)
    table["elbow_threshold"] = table["auto_threshold"]
    rows = [i for i in range(len(table)) if i % n_images in raised]
    table.loc[table.index[rows], "elbow_threshold"] = table.loc[table.index[rows], "auto_threshold"] - drop
    return table


def _collection(axes, label_start):
    found = [c for c in axes.collections if (c.get_label() or "").startswith(label_start)]
    assert len(found) == 1, [c.get_label() for c in axes.collections]
    return found[0]


def test_images_raised_to_the_lower_limit_are_marked_and_counted_in_the_legend():
    table = _table_with_elbow_values(6, raised=(1, 3))
    figure = qc.draw_calibration_plot(table, {2: 15.0}, lower_limits={2: 15.0})

    assert _legend_texts(figure) == [
        "Automatic value of each image (4 images)",
        "Raised to the lower limit (2 images)",
        "Value before the lower limit was applied",
        "Median used = 15.0",
        "Lower limit = 15.0",
    ]
    axes = figure.axes[0]
    used = table["auto_threshold"].to_numpy()
    before = table["elbow_threshold"].to_numpy()
    raised = _collection(axes, "Raised to the lower limit")
    earlier = _collection(axes, "Value before the lower limit")
    np.testing.assert_allclose(raised.get_offsets(), np.column_stack([[2, 4], used[[1, 3]]]))
    np.testing.assert_allclose(earlier.get_offsets(), np.column_stack([[2, 4], before[[1, 3]]]))
    assert earlier.get_facecolor().shape[0] == 0 or earlier.get_facecolor()[0][3] == 0
    plain = _collection(axes, "Automatic value of each image")
    np.testing.assert_allclose(plain.get_offsets()[:, 1], used[[0, 2, 4, 5]])


def test_the_value_before_the_limit_stays_in_view():
    table = _table_with_elbow_values(6, raised=(1,), drop=30.0)
    figure = qc.draw_calibration_plot(table, {2: 15.0}, lower_limits={2: 15.0})

    assert figure.axes[0].get_ylim()[0] < table["elbow_threshold"].min()


def test_the_calibration_plot_without_the_elbow_column_is_drawn_as_before():
    table = _table(6)
    assert "elbow_threshold" not in table

    figure = qc.draw_calibration_plot(table, {2: 15.0})
    assert _legend_texts(figure) == [
        "Automatic value of each image (6 images)", "Median used = 15.0",
    ]


def test_the_calibration_plot_with_no_image_raised_is_drawn_as_without_the_column():
    plain = _table(6)
    with_column = plain.assign(elbow_threshold=plain["auto_threshold"])
    with_missing = plain.assign(elbow_threshold=np.nan)

    for table in (with_column, with_missing):
        figure = qc.draw_calibration_plot(table, {2: 15.0}, lower_limits={2: 12})
        assert _legend_texts(figure) == _legend_texts(
            qc.draw_calibration_plot(plain, {2: 15.0}, lower_limits={2: 12})
        )
        assert len(figure.axes[0].collections) == len(
            qc.draw_calibration_plot(plain, {2: 15.0}, lower_limits={2: 12}).axes[0].collections
        )


def test_images_left_out_are_not_marked_as_raised():
    table = _table_with_elbow_values(6, raised=(1,), left_out=(0, 5))
    figure = qc.draw_calibration_plot(table, {2: 15.0}, lower_limits={2: 15.0})

    legend = _legend_texts(figure)
    assert "Raised to the lower limit (1 image)" in legend
    assert "Left out of the median (2 images)" in legend
    assert "Automatic value of each image (3 images)" in legend


def test_each_channel_of_the_calibration_plot_marks_its_own_raised_images():
    table = _table_with_elbow_values(5, raised=(0, 2), channels=(1, 3))
    table.loc[table["channel"] == 3, "elbow_threshold"] = table.loc[table["channel"] == 3, "auto_threshold"]
    figure = qc.draw_calibration_plot(table, {1: 15.0, 3: 17.0})

    first = [text.get_text() for text in figure.axes[0].get_legend().get_texts()]
    second = [text.get_text() for text in figure.axes[1].get_legend().get_texts()]
    assert "Raised to the lower limit (2 images)" in first
    assert not [text for text in second if "Raised" in text]


def test_calibration_plot_with_raised_images_is_written_and_the_table_is_not_changed(tmp_path):
    table = _table_with_elbow_values(8, raised=(0, 2, 7))
    kept = table.copy()
    path = qc.write_calibration_plot(tmp_path, table, {2: 15.0}, {2: 15.0})

    assert _png_size(path)[0] > 0
    pd.testing.assert_frame_equal(table, kept)
