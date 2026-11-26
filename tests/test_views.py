"""Tests for the views of qc.py that help to choose a threshold: channel previews, the LoG view, the line profile, the histogram and the LoG picture as a TIFF file."""

import numpy as np
import pytest
import tifffile
from matplotlib.figure import Figure

from bigfish_pypeline import detection, io, qc
from conftest import FISH_CHANNEL
from synthetic import make_image
from test_qc import _run_fresh_process

SPOT_RADIUS_PX = detection.get_spot_radius_px(
    (200, 65, 65), ex=570, em=610, NA=1.45, RI=1.45, microscope="confocal"
)


@pytest.fixture(scope="module")
def generated_log():
    """The LoG maximum projection of a generated image (uint16, 128 x 128)."""
    image, _, _ = make_image(n_spots=20, seed=2)
    filtered = detection.filter_channel(image, SPOT_RADIUS_PX)
    return qc.project_for_detection(filtered["rna_log"])


@pytest.fixture(scope="module")
def crop_channels(crop_path):
    """The three channels of the tissue crop, each (z, y, x)."""
    stack = tifffile.imread(crop_path)
    return [stack[:, channel] for channel in range(stack.shape[1])]


@pytest.fixture(scope="module")
def crop_log(crop_channels):
    """The LoG maximum projection of the crop's smFISH channel."""
    filtered = detection.filter_channel(crop_channels[FISH_CHANNEL], SPOT_RADIUS_PX)
    return qc.project_for_detection(filtered["rna_log"])


def _titles(figure):
    return [axes.get_title() for axes in figure.axes]


def _legend_texts(axes):
    return [text.get_text() for text in axes.get_legend().get_texts()]


# ---------------------------------------------------------------------------
# Channel previews
# ---------------------------------------------------------------------------

def test_previews_have_one_panel_per_channel_titled_from_zero():
    pictures = [np.random.default_rng(i).poisson(50, (30, 40)) for i in range(3)]

    figure = qc.draw_channel_previews(pictures, ["DAPI", None, "exon"])

    assert isinstance(figure, Figure)
    assert _titles(figure) == ["channel 0 (DAPI)", "channel 1", "channel 2 (exon)"]


def test_previews_without_names_give_numbers_only():
    figure = qc.draw_channel_previews([np.ones((5, 6)), np.ones((5, 6))])

    assert _titles(figure) == ["channel 0", "channel 1"]


def test_previews_project_3d_channels_with_their_maximum():
    stack = np.zeros((4, 10, 12))
    stack[2, 3, 4] = 100
    stack[0, 5, 6] = 50

    figure = qc.draw_channel_previews([stack, stack[0]])

    shown = np.asarray(figure.axes[0].images[0].get_array())
    assert shown.shape == (10, 12)
    assert shown[3, 4] == shown.max() and shown[5, 6] > shown[0, 0]
    assert np.array_equal(
        np.asarray(figure.axes[1].images[0].get_array()),
        qc._grey_levels(stack[0]),
    )


def test_previews_stretch_the_contrast_of_each_channel_separately():
    dim = np.random.default_rng(0).poisson(10, (40, 40))
    bright = dim * 100

    figure = qc.draw_channel_previews([dim, bright])

    first, second = (np.asarray(axes.images[0].get_array()) for axes in figure.axes)
    assert np.array_equal(first, second)
    assert first.min() == 0 and first.max() == 255


def test_previews_continue_on_a_new_row_above_four_channels():
    figure = qc.draw_channel_previews([np.ones((4, 4))] * 5)

    assert len(figure.axes) == 8
    assert sum(axes.get_title() != "" for axes in figure.axes) == 5


def test_previews_name_the_image():
    figure = qc.draw_channel_previews([np.ones((4, 4))], image_name="slide 3")

    assert figure.get_suptitle() == "slide 3"


def test_previews_without_channels_or_with_a_wrong_shape_are_refused():
    with pytest.raises(ValueError, match="no channels"):
        qc.draw_channel_previews([])
    with pytest.raises(ValueError, match="2 or 3 dimensions"):
        qc.draw_channel_previews([np.ones(5)])


def test_previews_do_not_change_the_pictures():
    picture = np.random.default_rng(0).poisson(30, (20, 20)).astype(np.uint16)
    before = picture.copy()

    qc.draw_channel_previews([picture])

    assert np.array_equal(picture, before)


def test_previews_of_the_crop(crop_channels):
    figure = qc.draw_channel_previews(crop_channels, ["DAPI", "Phalloidin", "jim-exon"])

    assert _titles(figure) == ["channel 0 (DAPI)", "channel 1 (Phalloidin)", "channel 2 (jim-exon)"]
    for axes in figure.axes:
        assert np.asarray(axes.images[0].get_array()).shape == (384, 384)


# ---------------------------------------------------------------------------
# LoG view
# ---------------------------------------------------------------------------

def test_log_view_holds_the_picture_values_at_whole_pixel_positions(generated_log):
    figure = qc.draw_log_view(generated_log)

    heatmap = figure.data[0]
    assert np.array_equal(np.asarray(heatmap.z), generated_log)
    assert np.array_equal(np.asarray(heatmap.x), np.arange(generated_log.shape[1]))
    assert np.array_equal(np.asarray(heatmap.y), np.arange(generated_log.shape[0]))
    assert "%{z:" in heatmap.hovertemplate
    assert "y = %{y}<br>x = %{x}" in heatmap.hovertemplate


def test_log_view_shows_real_values_and_not_the_display_values():
    picture = np.full((20, 30), 3.25, dtype=np.float32)
    picture[4, 7] = 123456.5

    heatmap = qc.draw_log_view(picture).data[0]

    assert heatmap.z[4, 7] == np.float32(123456.5)
    assert heatmap.z[0, 0] == np.float32(3.25)
    assert heatmap.zmax <= 123456.5


def test_log_view_axes_run_over_the_whole_picture_with_y_downwards(generated_log):
    figure = qc.draw_log_view(generated_log)

    height, width = generated_log.shape
    assert tuple(figure.layout.xaxis.range) == (-0.5, width - 0.5)
    assert tuple(figure.layout.yaxis.range) == (height - 0.5, -0.5)
    assert figure.layout.yaxis.scaleanchor == "x"
    assert figure.layout.dragmode == "pan"


def test_log_view_names_the_threshold_in_the_title(generated_log):
    with_threshold = qc.draw_log_view(generated_log, threshold=12.5)
    without = qc.draw_log_view(generated_log)

    assert "Selected threshold = 12.5" in with_threshold.layout.title.text
    assert "threshold" not in without.layout.title.text


def test_log_view_title_names_image_and_channel(generated_log):
    figure = qc.draw_log_view(generated_log, image_name="slide 3", channel=2, channel_name="exon")

    assert figure.layout.title.text.startswith("slide 3 | channel 2 (exon) | LoG-filtered")


def test_log_view_is_not_reduced_up_to_the_size_limit(generated_log, monkeypatch):
    monkeypatch.setattr(qc, "HTML_MAX_IMAGE_SIDE", max(generated_log.shape))

    figure = qc.draw_log_view(generated_log)

    assert np.asarray(figure.data[0].z).shape == generated_log.shape
    assert "reduced" not in figure.layout.title.text


def test_log_view_above_the_limit_takes_the_maximum_of_each_block(monkeypatch):
    monkeypatch.setattr(qc, "HTML_MAX_IMAGE_SIDE", 16)
    picture = np.random.default_rng(0).integers(0, 1000, (40, 50)).astype(np.float32)

    figure = qc.draw_log_view(picture, threshold=7)

    heatmap = figure.data[0]
    z = np.asarray(heatmap.z)
    block = 4
    assert z.shape == (10, 13)
    for i in range(z.shape[0]):
        for j in range(z.shape[1]):
            expected = picture[i * block:(i + 1) * block, j * block:(j + 1) * block].max()
            assert z[i, j] == expected
    title = figure.layout.title.text
    assert "reduced 4 × 4" in title and "picture 50 × 40 pixels" in title
    assert "Selected threshold = 7.0" in title
    assert "%{x:.1f}" in heatmap.hovertemplate


def test_log_view_positions_after_reduction_are_in_pixels_of_the_full_picture(monkeypatch):
    monkeypatch.setattr(qc, "HTML_MAX_IMAGE_SIDE", 16)
    picture = np.zeros((40, 50), dtype=np.float32)
    picture[5, 49] = 9.0

    figure = qc.draw_log_view(picture)

    heatmap = figure.data[0]
    x = np.asarray(heatmap.x)
    y = np.asarray(heatmap.y)
    # Blocks of 4 pixels: the middle of the block that starts at 0 is 1.5; the last block
    # of x holds only pixels 48 and 49.
    assert x[0] == 1.5 and x[1] == 5.5 and x[-1] == 48.5
    assert y[0] == 1.5 and y[-1] == 37.5
    assert tuple(figure.layout.xaxis.range) == (-0.5, 49.5)
    assert tuple(figure.layout.yaxis.range) == (39.5, -0.5)
    # The bright pixel at y = 5, x = 49 is in the block at y 4 to 7, x 48 to 49.
    row, column = np.unravel_index(np.argmax(np.asarray(heatmap.z)), heatmap.z.shape)
    assert (y[row], x[column]) == (5.5, 48.5)


def test_log_view_of_a_picture_with_one_long_side_is_reduced_by_the_longer_side(monkeypatch):
    monkeypatch.setattr(qc, "HTML_MAX_IMAGE_SIDE", 16)

    figure = qc.draw_log_view(np.ones((10, 33), dtype=np.float32))

    assert np.asarray(figure.data[0].z).shape == (4, 11)
    assert "reduced 3 × 3" in figure.layout.title.text


def test_log_view_is_not_reduced_at_the_size_limit_of_the_html_page():
    assert qc.HTML_MAX_IMAGE_SIDE == 2048
    figure = qc.draw_log_view(np.ones((2048, 2048), dtype=np.float32))

    assert np.asarray(figure.data[0].z).shape == (2048, 2048)


def test_log_view_of_a_larger_picture_is_reduced_and_its_json_stays_small():
    picture = np.random.default_rng(0).gamma(2, 3, (2304, 2304)).astype(np.float32)

    figure = qc.draw_log_view(picture)

    assert np.asarray(figure.data[0].z).shape == (1152, 1152)
    assert len(figure.to_json()) < 30e6


def test_log_view_keeps_whole_numbers_and_converts_other_types(generated_log):
    assert np.asarray(qc.draw_log_view(generated_log).data[0].z).dtype == generated_log.dtype
    wide = generated_log.astype(np.float64) + 0.5

    assert np.allclose(np.asarray(qc.draw_log_view(wide).data[0].z), wide)


def test_log_view_does_not_change_the_picture(generated_log):
    before = generated_log.copy()

    qc.draw_log_view(generated_log, threshold=5)

    assert np.array_equal(generated_log, before)


def test_log_view_needs_a_2d_picture():
    with pytest.raises(ValueError, match="2 dimensions"):
        qc.draw_log_view(np.ones((3, 4, 5)))


def test_log_view_of_the_crop(crop_log):
    figure = qc.draw_log_view(crop_log, threshold=18)

    assert np.array_equal(np.asarray(figure.data[0].z), crop_log)
    assert "Selected threshold = 18.0" in figure.layout.title.text


def test_log_view_can_be_written_as_json_and_html(crop_log):
    figure = qc.draw_log_view(crop_log)

    assert "heatmap" in figure.to_json()
    assert "<div" in figure.to_html(include_plotlyjs=False, full_html=False)


# ---------------------------------------------------------------------------
# Line profile
# ---------------------------------------------------------------------------

@pytest.fixture
def ramp():
    """A 10 x 10 picture whose value is 10 * y + x."""
    return np.arange(100, dtype=np.float32).reshape(10, 10)


def test_profile_along_a_horizontal_line(ramp):
    distance, values = qc.line_profile_values(ramp, (3, 2), (3, 7))

    assert np.array_equal(values, [32, 33, 34, 35, 36, 37])
    assert np.allclose(distance, [0, 1, 2, 3, 4, 5])


def test_profile_along_a_vertical_line(ramp):
    distance, values = qc.line_profile_values(ramp, (1, 4), (6, 4))

    assert np.array_equal(values, [14, 24, 34, 44, 54, 64])
    assert np.allclose(distance, [0, 1, 2, 3, 4, 5])


def test_profile_along_a_diagonal_line(ramp):
    distance, values = qc.line_profile_values(ramp, (0, 0), (4, 4))

    # Seven samples 4 * sqrt(2) / 6 pixels apart, each in the pixel it falls in:
    # (0, 0), (1, 1), (1, 1), (2, 2), (3, 3), (3, 3), (4, 4).
    assert np.array_equal(values, [0, 11, 11, 22, 33, 33, 44])
    assert np.allclose(distance, np.linspace(0, 4 * np.sqrt(2), 7))


def test_profile_runs_in_the_direction_given(ramp):
    _, forward = qc.line_profile_values(ramp, (3, 2), (3, 7))
    _, backward = qc.line_profile_values(ramp, (3, 7), (3, 2))

    assert np.array_equal(backward, forward[::-1])


def test_profile_holds_only_values_of_the_picture():
    picture = np.random.default_rng(0).poisson(30, (40, 50)).astype(np.float32)

    _, values = qc.line_profile_values(picture, (3.0, 4.0), (35.0, 44.0))

    assert set(values.tolist()) <= set(picture.ravel().tolist())


def test_profile_of_a_line_ending_on_the_last_pixel(ramp):
    _, values = qc.line_profile_values(ramp, (9, 0), (9, 9))

    assert np.array_equal(values, np.arange(90, 100))


@pytest.mark.parametrize("start, end, which", [
    ((10, 3), (2, 3), "start"),
    ((2, 3), (2, 10), "end"),
    ((-1, 3), (2, 3), "start"),
    ((2, 3), (-0.5, 3), "end"),
])
def test_profile_with_a_point_outside_the_picture_says_so_in_plain_words(ramp, start, end, which):
    with pytest.raises(ValueError) as error:
        qc.line_profile_values(ramp, start, end)

    message = str(error.value)
    assert f"The {which} point" in message
    assert "outside the picture" in message
    assert "10 pixels high and 10 pixels wide" in message
    assert "between 0 and 9" in message


def test_the_figure_refuses_a_point_outside_the_picture_too(ramp):
    with pytest.raises(ValueError, match="outside the picture"):
        qc.plot_line_profile(ramp, (0, 0), (0, 12))


def test_profile_with_two_equal_points_is_refused(ramp):
    with pytest.raises(ValueError, match="same"):
        qc.line_profile_values(ramp, (2, 2), (2, 2))


def test_profile_with_points_that_are_not_two_numbers_is_refused(ramp):
    with pytest.raises(ValueError, match=r"\(y, x\)"):
        qc.line_profile_values(ramp, (1, 2, 3), (4, 5))
    with pytest.raises(ValueError, match=r"\(y, x\)"):
        qc.line_profile_values(ramp, 3, (4, 5))


def test_profile_needs_a_2d_picture():
    with pytest.raises(ValueError, match="2 dimensions"):
        qc.line_profile_values(np.ones((3, 10, 10)), (0, 0), (5, 5))


def test_profile_figure_has_the_picture_with_the_line_and_the_values(ramp):
    figure = qc.plot_line_profile(ramp, (3, 2), (3, 7))

    assert isinstance(figure, Figure)
    picture_axes, curve_axes = figure.axes
    assert np.array_equal(np.asarray(picture_axes.images[0].get_array()), ramp)
    line = picture_axes.lines[0]
    assert list(line.get_xdata()) == [2, 7] and list(line.get_ydata()) == [3, 3]
    assert "(y, x) = (3, 2) to (3, 7)" in picture_axes.get_title()
    curve = curve_axes.lines[0]
    assert np.array_equal(curve.get_ydata(), [32, 33, 34, 35, 36, 37])
    assert np.allclose(curve.get_xdata(), [0, 1, 2, 3, 4, 5])
    assert curve_axes.get_xlabel() == "Distance along the line (pixels)"
    assert curve_axes.get_ylabel() == "Pixel value"


def test_profile_figure_does_not_change_the_picture(ramp):
    before = ramp.copy()

    qc.plot_line_profile(ramp, (0, 0), (9, 9))

    assert np.array_equal(ramp, before)


def test_profile_of_the_crop_through_a_spot(crop_log):
    y, x = np.unravel_index(np.argmax(crop_log), crop_log.shape)
    start = (int(y), max(int(x) - 10, 0))
    end = (int(y), min(int(x) + 10, crop_log.shape[1] - 1))

    figure = qc.plot_line_profile(crop_log, start, end)
    distance, values = qc.line_profile_values(crop_log, start, end)

    assert np.array_equal(values, crop_log[y, start[1]:end[1] + 1])
    assert values.max() == crop_log.max()
    assert np.array_equal(figure.axes[1].lines[0].get_ydata(), values)


def test_profile_of_a_generated_picture(generated_log):
    figure = qc.plot_line_profile(generated_log, (10, 10), (100, 120))

    assert len(figure.axes) == 2


# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------

def test_histogram_has_a_logarithmic_count_axis(generated_log):
    figure = qc.draw_log_histogram(generated_log)

    axes = figure.axes[0]
    assert isinstance(figure, Figure)
    assert axes.get_yscale() == "log"
    assert sum(patch.get_height() for patch in axes.patches) > 0
    assert axes.get_xlabel() == "LoG value"
    assert "logarithmic" in axes.get_ylabel()
    assert axes.get_legend() is None


def test_histogram_counts_every_pixel(generated_log):
    figure = qc.draw_log_histogram(generated_log, bins=50)

    counts = [patch.get_height() for patch in figure.axes[0].patches]
    assert len(counts) == 50
    assert sum(counts) == generated_log.size


def test_histogram_names_the_threshold_in_its_legend_as_the_elbow_plot_does(generated_log):
    figure = qc.draw_log_histogram(generated_log, threshold=11)

    axes = figure.axes[0]
    assert _legend_texts(axes) == ["Selected threshold = 11.0"]
    lines = [line for line in axes.lines if list(line.get_xdata()) == [11, 11]]
    assert len(lines) == 1


def test_histogram_keeps_a_threshold_outside_the_values_in_view():
    picture = np.arange(100, dtype=np.float32).reshape(10, 10)

    axes = qc.draw_log_histogram(picture, threshold=250).axes[0]

    assert axes.get_xlim()[1] > 250


def test_histogram_title_names_image_and_channel(generated_log):
    figure = qc.draw_log_histogram(generated_log, image_name="slide 3", channel=2, channel_name="exon")

    assert figure.axes[0].get_title() == "slide 3 | channel 2 (exon) | Histogram of the LoG values"


def test_histogram_leaves_out_values_that_are_not_numbers():
    picture = np.array([[1.0, 2.0], [np.nan, np.inf]])

    counts = [patch.get_height() for patch in qc.draw_log_histogram(picture, bins=4).axes[0].patches]

    assert sum(counts) == 2


def test_histogram_of_a_flat_picture_still_gives_a_figure():
    assert qc.draw_log_histogram(np.zeros((5, 5)), threshold=1) is not None


def test_histogram_without_values_is_refused():
    with pytest.raises(ValueError, match="no values"):
        qc.draw_log_histogram(np.full((3, 3), np.nan))


def test_histogram_of_the_crop(crop_log):
    figure = qc.draw_log_histogram(crop_log, threshold=18)

    assert _legend_texts(figure.axes[0]) == ["Selected threshold = 18.0"]


# ---------------------------------------------------------------------------
# Saving the LoG picture
# ---------------------------------------------------------------------------

def test_log_projection_reads_back_with_equal_values_and_the_pixel_size(tmp_path, crop_log):
    path = qc.write_log_projection(crop_log, tmp_path / "crop_ch2_log.tif", pixel_size_nm=65)

    found = tifffile.imread(path)
    assert path == tmp_path / "crop_ch2_log.tif"
    assert found.dtype == np.float32
    assert np.array_equal(found, crop_log.astype(np.float32))
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        description = page.tags["ImageDescription"].value
        numerator, denominator = page.tags["XResolution"].value
        y_numerator, y_denominator = page.tags["YResolution"].value
    assert "ImageJ=" in description and "unit=micron" in description
    assert numerator / denominator == pytest.approx(1000 / 65, rel=1e-3)
    assert y_numerator / y_denominator == pytest.approx(1000 / 65, rel=1e-3)


def test_log_projection_pixel_size_is_read_by_the_packages_reader(tmp_path, generated_log):
    path = qc.write_log_projection(generated_log, tmp_path / "log.tif", pixel_size_nm=65)

    info = io.get_image_info(path)

    assert info.shape == generated_log.shape
    assert info.axes == "YX" and info.layout == "YX"
    assert info.dtype == np.float32
    assert info.voxel_size_x == pytest.approx(65, rel=1e-3)
    assert info.voxel_size_y == pytest.approx(65, rel=1e-3)


def test_log_projection_without_a_pixel_size_holds_none(tmp_path, generated_log):
    path = qc.write_log_projection(generated_log, tmp_path / "log.tif")

    info = io.get_image_info(path)

    assert info.voxel_size_x is None and info.voxel_size_y is None
    assert np.array_equal(tifffile.imread(path), generated_log.astype(np.float32))


def test_log_projection_keeps_float_values_as_they_are(tmp_path):
    picture = np.random.default_rng(0).normal(size=(20, 30)).astype(np.float32)

    path = qc.write_log_projection(picture, tmp_path / "log.tif", pixel_size_nm=100)

    assert np.array_equal(tifffile.imread(path), picture)


def test_log_projection_makes_the_folder_and_leaves_no_temporary_file(tmp_path, generated_log):
    path = qc.write_log_projection(generated_log, tmp_path / "new" / "folder" / "log.tif")

    assert path.is_file()
    assert [file.name for file in path.parent.iterdir()] == ["log.tif"]


def test_log_projection_replaces_an_earlier_file(tmp_path):
    path = tmp_path / "log.tif"
    qc.write_log_projection(np.zeros((4, 4)), path)
    qc.write_log_projection(np.ones((4, 4)), path)

    assert np.array_equal(tifffile.imread(path), np.ones((4, 4), dtype=np.float32))


def test_failed_log_projection_write_leaves_no_file(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(tifffile, "imwrite", broken)

    with pytest.raises(OSError):
        qc.write_log_projection(np.zeros((4, 4)), tmp_path / "log.tif")

    assert list(tmp_path.iterdir()) == []


def test_log_projection_refuses_a_pixel_size_of_zero_or_less(tmp_path):
    with pytest.raises(ValueError, match="pixel size"):
        qc.write_log_projection(np.zeros((4, 4)), tmp_path / "log.tif", pixel_size_nm=0)


def test_log_projection_does_not_change_the_picture(tmp_path, generated_log):
    before = generated_log.copy()

    qc.write_log_projection(generated_log, tmp_path / "log.tif")

    assert np.array_equal(generated_log, before)


# ---------------------------------------------------------------------------
# No screen, no pyplot
# ---------------------------------------------------------------------------

def test_the_views_are_drawn_in_a_process_without_a_display(tmp_path):
    script = f"""
        import threading

        import matplotlib
        import numpy as np
        from matplotlib import _pylab_helpers

        from bigfish_pypeline import qc

        def backend_setting():
            return dict.__getitem__(matplotlib.rcParams, "backend")

        backend_before = backend_setting()
        picture = np.random.default_rng(0).poisson(40, (50, 70)).astype(np.uint16)
        folder = {str(tmp_path)!r}
        outcome = {{}}

        def work():
            try:
                qc.draw_channel_previews([picture, picture], ["a", "b"]).savefig(folder + "/previews.png")
                qc.draw_log_view(picture, threshold=30).to_json()
                qc.plot_line_profile(picture, (3, 4), (40, 60)).savefig(folder + "/profile.png")
                qc.draw_log_histogram(picture, threshold=30).savefig(folder + "/histogram.png")
                qc.write_log_projection(picture, folder + "/log.tif", 65)
            except BaseException as error:
                outcome["error"] = repr(error)

        thread = threading.Thread(target=work)
        thread.start()
        thread.join()

        assert "error" not in outcome, outcome.get("error")
        assert backend_setting() == backend_before, (backend_before, backend_setting())
        assert not _pylab_helpers.Gcf.get_all_fig_managers()
        import sys
        assert "matplotlib.pyplot" not in sys.modules
        print("ok")
    """
    done = _run_fresh_process(script, tmp_path)

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout
    for name in ("previews.png", "profile.png", "histogram.png", "log.tif"):
        assert (tmp_path / name).is_file()


def test_importing_the_module_does_not_load_plotly_or_pyplot(tmp_path):
    script = """
        import sys
        import bigfish_pypeline.qc
        assert "plotly" not in sys.modules
        assert "matplotlib.pyplot" not in sys.modules
        print("ok")
    """
    done = _run_fresh_process(script, tmp_path, remove_display=False)

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout


# ---------------------------------------------------------------------------
# Reference spot
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def crop_detection(crop_channels):
    """The crop's smFISH channel filtered, with its spots found at a manual threshold of 18."""
    filtered = detection.filter_channel(crop_channels[FISH_CHANNEL], SPOT_RADIUS_PX)
    detected = detection.detect_spots(
        filtered["rna_log"], SPOT_RADIUS_PX, threshold_mode="manual", threshold=18, elbow=True
    )
    return filtered, detected


def _spot_panels(figure):
    """The axes that hold a picture (the colour bar is not one of them)."""
    return [axes for axes in figure.axes if axes.images]


def test_reference_spot_has_one_panel_per_plane_on_one_colour_scale():
    spot = np.arange(5 * 4 * 4, dtype=np.uint16).reshape(5, 4, 4)

    figure = qc.draw_reference_spot(spot, image_name="slide 3", channel=2, channel_name="exon")

    assert isinstance(figure, Figure)
    panels = _spot_panels(figure)
    assert [axes.get_title() for axes in panels] == [f"plane {n} of 5" for n in range(1, 6)]
    limits = {image.get_clim() for axes in panels for image in axes.images}
    assert limits == {(0.0, float(spot.max()))}
    assert np.array_equal(np.asarray(panels[2].images[0].get_array()), spot[2])
    assert figure.get_suptitle() == "slide 3 | channel 2 (exon) | reference spot"


def test_reference_spot_of_a_2d_image_is_one_panel():
    figure = qc.draw_reference_spot(np.ones((5, 5)) * 7)

    panels = _spot_panels(figure)
    assert [axes.get_title() for axes in panels] == ["single plane"]
    assert figure.get_suptitle() == "reference spot"


def test_reference_spot_with_many_planes_shows_evenly_spaced_ones_and_says_so():
    spot = np.random.default_rng(0).poisson(20, (15, 6, 6))

    figure = qc.draw_reference_spot(spot)

    titles = [axes.get_title() for axes in _spot_panels(figure)]
    assert len(titles) == qc.REFERENCE_SPOT_MAX_PANELS
    assert titles[0] == "plane 1 of 15" and titles[-1] == "plane 15 of 15"
    assert "9 of 15 planes, evenly spaced" in figure.get_suptitle()


def test_reference_spot_of_a_flat_spot_still_gives_a_figure():
    figure = qc.draw_reference_spot(np.full((3, 4, 4), 9))

    assert len(_spot_panels(figure)) == 3


def test_reference_spot_without_a_spot_or_with_a_wrong_shape_is_refused():
    with pytest.raises(ValueError, match="decomposition is switched off or was skipped"):
        qc.draw_reference_spot(None)
    with pytest.raises(ValueError, match="1 dimensions"):
        qc.draw_reference_spot(np.ones(5))
    with pytest.raises(ValueError, match="4 dimensions"):
        qc.draw_reference_spot(np.ones((2, 2, 2, 2)))


def test_reference_spot_does_not_change_the_spot():
    spot = np.random.default_rng(0).poisson(30, (5, 5, 5)).astype(np.uint16)
    before = spot.copy()

    qc.draw_reference_spot(spot)

    assert np.array_equal(spot, before)


def test_reference_spot_of_the_crop(crop_channels, crop_detection):
    from bigfish_pypeline import steps
    from bigfish_pypeline.config import load_config
    from conftest import TEST_DATA, CROP_NAME

    config = load_config(TEST_DATA / f"{CROP_NAME}_config.yaml")
    filtered, detected = crop_detection
    decomposed = steps.decompose(
        config, config.channels[0], CROP_NAME, filtered["rna"], detected["spots"],
        steps.spot_radius(config, config.channels[0])["spot_radius_nm"],
    )

    figure = qc.draw_reference_spot(decomposed["reference_spot"], CROP_NAME, 2, "jim-exon")

    assert len(_spot_panels(figure)) == decomposed["reference_spot"].shape[0]


# ---------------------------------------------------------------------------
# Threshold in words
# ---------------------------------------------------------------------------

def _detected(spots=5, threshold=18.0, auto_threshold=None, elbow=True):
    """What `steps.detect` gives, with an elbow curve that bends at about 12."""
    thresholds = np.arange(1.0, 40.0)
    counts = np.log(1 + 400 * np.exp(-thresholds / 6)) + (thresholds < 12) * 3.0
    return {
        "spots": np.zeros((spots, 3), dtype=np.int64),
        "threshold": threshold,
        "auto_threshold": auto_threshold,
        "elbow_thresholds": thresholds if elbow else None,
        "elbow_counts": counts if elbow else None,
        "warning": None,
    }


def test_threshold_text_for_a_manual_value_names_the_automatic_one_beside_it():
    from bigfish_pypeline.qc import _elbow_method_value

    detected = _detected(spots=473, threshold=18.0)
    automatic = _elbow_method_value(detected["elbow_thresholds"], detected["elbow_counts"])

    lines = qc.describe_threshold(detected, "manual")

    assert lines[0] == "Threshold used: 18.0 (manual)."
    assert lines[1] == f"The automatic threshold of this image would be {automatic:.1f}."
    assert lines[-1] == "473 spots found."


def test_threshold_text_for_a_calibrated_value_names_the_automatic_one_too():
    lines = qc.describe_threshold(_detected(threshold=14.5), "calibrated")

    assert lines[0] == "Threshold used: 14.5 (calibrated)."
    assert lines[1].startswith("The automatic threshold of this image would be ")


def test_threshold_text_for_an_automatic_value_is_one_line_and_the_count():
    lines = qc.describe_threshold(_detected(threshold=13.0, auto_threshold=13.0), "auto")

    assert lines == ["Threshold used: 13.0 (automatic).", "5 spots found."]


def test_threshold_text_says_when_the_lower_limit_raised_the_automatic_value():
    lines = qc.describe_threshold(_detected(threshold=15.0, auto_threshold=11.0), "auto", lower_limit=15)

    assert lines[0] == "Threshold used: 15.0 (automatic)."
    assert lines[1] == (
        "The automatic threshold of this image is 11.0; it was raised to the lower limit of 15.0."
    )


def test_threshold_text_with_a_lower_limit_that_did_not_act_has_no_extra_line():
    lines = qc.describe_threshold(_detected(threshold=13.0, auto_threshold=13.0), "auto", lower_limit=5)

    assert len(lines) == 2


def test_threshold_text_without_a_threshold_says_there_are_no_spots():
    detected = _detected(spots=0, threshold=None, elbow=False)

    lines = qc.describe_threshold(detected, "auto")

    assert len(lines) == 1 and "no candidate spots" in lines[0]


def test_threshold_text_for_a_manual_value_without_an_elbow_curve():
    lines = qc.describe_threshold(_detected(threshold=18, elbow=False), "manual")

    assert lines[1] == "The elbow method gives no automatic threshold for this image."


def test_threshold_text_of_the_crop(crop_detection):
    _, detected = crop_detection

    lines = qc.describe_threshold(detected, "manual")

    assert lines[0] == "Threshold used: 18.0 (manual)."
    assert lines[-1] == f"{len(detected['spots'])} spots found."
