"""Tests for qc.py: the Cellpose QC figure, the elbow plot, the calibration plot, the detection plot and the reference spot."""

import os
import struct
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import numpy as np
import pytest
import tifffile
from matplotlib.collections import EllipseCollection, PatchCollection

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


def test_title_says_when_cellpose_chooses_the_diameter():
    title = qc.cellpose_qc_title("img", 0, PRETREATMENT, None, 5, 1.0)

    assert "None" not in title
    assert "diameter chosen by Cellpose" in title


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
        loaded = [name for name in ("cellpose", "torch") if name in sys.modules]
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
    assert axes.get_ylabel() == "Number of mRNAs detected (log scale)"
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
    assert "cyan shapes: clusters" in right.get_title()


def test_spots_are_circles_of_the_spot_radius_and_clusters_are_filled_shapes():
    figure = _draw_detection(spot_radius_px=(2.2, 1.9, 1.9))

    circles, shapes = _detection_axes(figure)[1].collections
    # matplotlib keeps the half-width and half-height of each ellipse, which are the radius.
    assert np.allclose(circles._widths, 1.9) and np.allclose(circles._heights, 1.9)
    assert circles.get_facecolor().shape[0] == 0 or circles.get_facecolor()[0][3] == 0
    assert np.allclose(circles.get_edgecolor()[0][:3], (1.0, 165 / 255, 0.0))
    assert np.allclose(shapes.get_facecolor()[0][:3], (0.0, 1.0, 1.0))
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
    assert _png_size(path) == (3000, int(np.clip(10 * 60 / 80 + 1.2, 3, 16) * 150))
    assert sorted(file.name for file in (tmp_path / "qc").iterdir()) == [path.name]


def test_detection_plot_with_no_spots_is_written(tmp_path):
    path = _write_detection(tmp_path, spots=np.zeros((0, 2)), clusters=None)

    assert _png_size(path)[0] == 1500


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
