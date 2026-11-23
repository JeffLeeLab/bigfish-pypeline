"""Tests for qc.py: the Cellpose QC figure."""

import os
import struct
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import numpy as np
import pytest

from bigfish_pypeline import qc
from bigfish_pypeline import segmentation as seg
from cellpose_standin import StandInModel

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
