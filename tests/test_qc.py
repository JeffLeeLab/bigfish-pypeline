"""Tests for qc.py: the Cellpose QC figure, the elbow plot and the calibration plot."""

import os
import struct
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import numpy as np
import pytest

from bigfish_pypeline import detection, outputs, qc
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
