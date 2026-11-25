"""
QC figures: pictures written as PNG files that show a biologist how an image
was processed.

The figures are drawn without a screen and without `matplotlib.pyplot`, so
they can be written from any thread, and they do not change which matplotlib
backend a notebook or app has chosen. `cellpose` and `torch` are imported only
inside the function that needs them, so importing this module never loads them.
"""

import base64
import html
import io
import os
import textwrap
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import EllipseCollection, LineCollection, PatchCollection
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import RegularPolygon
from matplotlib.patheffects import withStroke
from matplotlib.ticker import MaxNLocator

QC_FOLDER_NAME = "qc"
CELLPOSE_QC_SUFFIX = "_cellpose_qc"
ELBOW_SUFFIX = "_elbow"
CALIBRATION_FILE_NAME = "calibration"
QC_EXTENSION = ".png"

# Titles wider than this many characters are continued on a new line.
TITLE_LINE_WIDTH = 150
CELLPOSE_FIGURE_WIDTH = 18
# Height of the figure outside the four panels (title and panel names), in inches.
CELLPOSE_FIGURE_MARGIN = 1.0
FIGURE_DPI = 150

DIAMETER_AUTOMATIC = "no diameter set (image used at its own scale)"
CELLPOSE_INPUT_PANEL_TITLE = "image after pre-treatment"

# Elbow plot
ELBOW_FIGURE_SIZE = (6.5, 5.0)
# Titles of the elbow plot are continued on a new line after this many characters.
ELBOW_TITLE_LINE_WIDTH = 60
# The curve is big-fish's: the natural log of the number of candidate spots
# above each threshold, smoothed, before spots that share a peak are merged.
ELBOW_Y_LABEL = (
    "Natural log of candidate spots above each threshold\n"
    "(smoothed, before spots sharing a peak are merged)"
)
ELBOW_CURVE_COLOUR = "#2c7bb6"
SELECTED_COLOUR = "#d7191c"
AUTOMATIC_COLOUR = "#e08214"
LOWER_LIMIT_COLOUR = "#1a9641"
THRESHOLD_MODE_WORDS = {
    "manual": "manual threshold",
    "auto": "automatic threshold",
    "calibrated": "calibrated threshold",
}

# Calibration plot
# Image names are written along the axis up to this number of images; above it
# the images are numbered.
CALIBRATION_MAX_NAMED_IMAGES = 30
CALIBRATION_PANEL_HEIGHT = 3.8
# Room, in inches, for the legend beside each panel.
CALIBRATION_LEGEND_WIDTH = 3.2
CALIBRATION_LEFT_OUT_COLOUR = "#7f7f7f"

# Detection plot and reference spot
DETECTION_SUFFIX = "_detection"
REFERENCE_SPOT_SUFFIX = "_referencespot"
REFERENCE_SPOT_EXTENSION = ".tif"
# Width of the detection plot in inches, as in v1 (20 inches for two pictures).
# Its height follows the shape of the image, and is never more than v1's 16 inches.
DETECTION_FIGURE_WIDTH = 20
# Dots per inch of the detection plot: the file is 2,000 pixels wide, as in v1.
DETECTION_FIGURE_DPI = 100
DETECTION_MAX_HEIGHT = 16
# Height of the figure outside the pictures (title and picture names), in inches.
DETECTION_FIGURE_MARGIN = 1.2
DETECTION_COLOUR_MAP = "viridis"
SPOT_COLOUR = "orange"
SPOT_LINE_WIDTH = 1
CLUSTER_COLOUR = "cyan"
CLUSTER_LINE_WIDTH = 2
# Clusters are drawn as pentagons.
CLUSTER_SHAPE_SIDES = 5
# Pixels brighter than this percentile are all shown in the brightest colour.
DETECTION_CONTRAST_PERCENTILE = 99.9

# Final QC
FINAL_SUFFIX = "_final"
HTML_EXTENSION = ".html"
# Above this number of cells the PNG leaves the text on the cells out.
FINAL_MAX_LABELLED_CELLS = 300
FINAL_FIGURE_WIDTH = 16
# Dots per inch of the final QC figure: the file is 2,000 pixels wide.
FINAL_FIGURE_DPI = 125
# Height of the figure outside the picture (title and legend), in inches.
FINAL_FIGURE_MARGIN = 1.9
FINAL_MAX_HEIGHT = 16
FINAL_SPOT_COLOUR = "#ff9f0a"
FINAL_OUTSIDE_SPOT_COLOUR = "#ff4fd8"
FINAL_CLUSTER_COLOUR = "cyan"
FINAL_OUTLINE_COLOUR = "#3ddc57"
# Polygons of the cell outlines are simplified until they are this many pixels from the true edge.
FINAL_OUTLINE_TOLERANCE_PX = 0.5

# The page: the picture is not larger than this many pixels on its longer side.
HTML_MAX_IMAGE_SIDE = 2048
PLOTLY_SCRIPT_NAME = "plotly.min.js"
PLOTLY_SHARED = "shared"
PLOTLY_EMBEDDED = "embedded"
# The grid of invisible points that answers a hover on a cell is this far apart
# (in picture pixels) on a picture 256 pixels wide, and wider on larger pictures.
HTML_HOVER_GRID_MIN_STEP_PX = 3
HTML_HOVER_GRID_POINTS_ACROSS = 256
HTML_HOVER_DISTANCE_PX = 12


# Cellpose QC figure

def cellpose_qc_path(run_folder, image_name):
    """Path of an image's Cellpose QC figure: `qc/<image>_cellpose_qc.png` in the run folder."""
    return Path(run_folder) / QC_FOLDER_NAME / f"{image_name}{CELLPOSE_QC_SUFFIX}{QC_EXTENSION}"


def temporary_qc_path(path):
    """Name a QC figure has while it is written: `<image>_cellpose_qc.png.tmp`."""
    path = Path(path)
    return path.with_name(path.name + ".tmp")


def _save_figure(figure, path, dpi=FIGURE_DPI):
    """
    Write a figure as a PNG file under a temporary name, then rename it, so a
    half-written figure never has the final name. The folder is made when it
    does not exist.

    dpi: dots per inch of the file; with the figure's width in inches it
        sets the width of the picture in pixels.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_qc_path(path)
    try:
        figure.savefig(temporary, format="png", dpi=dpi)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def cellpose_qc_title(image_name, channel, pretreatment, diameter, n_cells, seconds,
                      channel_name=None):
    """
    The title of the Cellpose QC figure.

    image_name: the image's name.
    channel: the segmentation channel's number.
    channel_name: the channel's name, shown after the number when given.
    pretreatment: the one-line text from `describe_pretreatment`; it starts
        with the Z projection, for example "max projection | rolling ball 200 px".
    diameter: the cell diameter in pixels given to Cellpose, or None when no
        diameter is set and the image is used at its own scale.
    n_cells: number of cells found.
    seconds: time Cellpose took.

    The items are separated by " | ". A title longer than TITLE_LINE_WIDTH
    characters is continued on a new line between two items.
    """
    channel_text = f"channel {channel}"
    if channel_name:
        channel_text += f" ({channel_name})"
    diameter_text = DIAMETER_AUTOMATIC if diameter is None else f"diameter {diameter:g} px"
    cell_text = f"{n_cells} cell" if n_cells == 1 else f"{n_cells} cells"
    items = [
        str(image_name), channel_text, str(pretreatment), diameter_text,
        cell_text, f"{seconds:.1f} s",
    ]
    return _wrap_items(items, TITLE_LINE_WIDTH)


def _wrap_items(items, width, separator=" | "):
    """Join items with the separator, starting a new line before an item that would pass `width`."""
    lines = []
    line = ""
    for item in items:
        pieces = textwrap.wrap(item, width=width, break_long_words=True) or [""]
        for piece in pieces:
            if line and len(line) + len(separator) + len(piece) > width:
                lines.append(line)
                line = piece
            else:
                line = f"{line}{separator}{piece}" if line else piece
    lines.append(line)
    return "\n".join(lines)


def _stretch_for_display(image):
    """
    The image as 8-bit grey values in three identical channels (y, x, 3), with
    the 1st percentile shown as black and the 99th as white. Only the picture
    changes; the image given is left as it is.
    """
    image = np.asarray(image, dtype=np.float32)
    low, high = np.percentile(image, [1, 99])
    shown = np.clip((image - low) / max(high - low, 1e-6), 0, 1)
    grey = (shown * 255).astype(np.uint8)
    return np.stack([grey, grey, grey], axis=-1)


def draw_cellpose_qc(segmentation, image_name, channel, pretreatment, diameter,
                     channel_name=None):
    """
    Draw the Cellpose QC figure and return it, without showing or saving it.

    segmentation: the dict returned by `segment_cells`. Its "model_input"
        (the image given to Cellpose, shown with a display-only contrast
        stretch), "masks", "flows", "n_cells" and "seconds" are used.
    The other arguments make the title; see `cellpose_qc_title`.

    The four panels are the image given to Cellpose (after pre-treatment), the
    cell outlines, the masks in colour and Cellpose's flows. Returns a
    matplotlib `Figure` that is not tied to `matplotlib.pyplot`.
    """
    from cellpose import plot

    shown = _stretch_for_display(segmentation["model_input"])
    masks = np.asarray(segmentation["masks"])
    flow_picture = segmentation["flows"][0]

    height_to_width = shown.shape[0] / shown.shape[1]
    panel_height = CELLPOSE_FIGURE_WIDTH / 4 * height_to_width
    figure_height = float(np.clip(panel_height + CELLPOSE_FIGURE_MARGIN, 2.5, 12))
    figure = Figure(
        figsize=(CELLPOSE_FIGURE_WIDTH, figure_height), dpi=FIGURE_DPI, layout="constrained"
    )
    FigureCanvasAgg(figure)
    plot.show_segmentation(figure, shown, masks, flow_picture)
    figure.axes[0].set_title(CELLPOSE_INPUT_PANEL_TITLE)
    figure.suptitle(
        cellpose_qc_title(
            image_name, channel, pretreatment, diameter,
            segmentation["n_cells"], segmentation["seconds"], channel_name,
        ),
        fontsize=11,
    )
    return figure


def write_cellpose_qc(run_folder, image_name, segmentation, channel, pretreatment,
                      diameter, channel_name=None):
    """
    Write an image's Cellpose QC figure as `qc/<image>_cellpose_qc.png` in the run folder.

    The arguments are those of `draw_cellpose_qc`, with the run folder first.
    The figure is first written under a temporary name and then renamed, so a
    half-written figure never has the final name. The `qc` folder is made when
    it does not exist. Works from any thread and needs no screen.

    Returns the path of the figure.
    """
    figure = draw_cellpose_qc(
        segmentation, image_name, channel, pretreatment, diameter, channel_name
    )
    path = cellpose_qc_path(run_folder, image_name)
    _save_figure(figure, path)
    return path


# Elbow plot

def elbow_path(run_folder, image_name, channel):
    """Path of an image's elbow plot: `qc/<image>_ch<index>_elbow.png` in the run folder."""
    return (
        Path(run_folder) / QC_FOLDER_NAME
        / f"{image_name}_ch{channel}{ELBOW_SUFFIX}{QC_EXTENSION}"
    )


def elbow_title(image_name, channel, threshold_mode, channel_name=None):
    """
    The title of the elbow plot: the image, the channel and the threshold mode,
    for example "slide 3 | channel 2 (jim-exon) | manual threshold". A title
    longer than ELBOW_TITLE_LINE_WIDTH characters is continued on a new line.

    channel: the channel's number.
    channel_name: the channel's name, shown after the number when given.
    threshold_mode: "manual", "auto" or "calibrated".
    """
    channel_text = f"channel {channel}"
    if channel_name:
        channel_text += f" ({channel_name})"
    mode_text = THRESHOLD_MODE_WORDS.get(threshold_mode, f"{threshold_mode} threshold")
    return _wrap_items([str(image_name), channel_text, mode_text], ELBOW_TITLE_LINE_WIDTH)


def _has_elbow_values(thresholds, counts):
    """True when the elbow curve has at least one point."""
    return thresholds is not None and counts is not None and np.size(thresholds) > 0 \
        and np.size(counts) > 0


def _elbow_method_value(thresholds, counts):
    """
    The threshold the big-fish elbow method chooses on this curve, or None when
    it cannot choose one. Used when the threshold of the channel was set by
    hand or by the calibration, so that the plot can still show the value the
    elbow method would have given.
    """
    from bigfish.detection import get_breaking_point

    try:
        value, _, _ = get_breaking_point(np.asarray(thresholds), np.asarray(counts))
    except (ValueError, IndexError):
        return None
    return float(value)


def _value_text(value):
    return f"{float(value):.1f}"


def draw_elbow_plot(detected, image_name, channel, threshold_mode, lower_limit=None,
                    channel_name=None):
    """
    Draw the elbow plot of one image and channel and return it, without
    showing or saving it.

    detected: the dict returned by `detect_spots` (with `elbow=True`). Its
        "elbow_thresholds", "elbow_counts", "threshold" and "auto_threshold"
        are used.
    image_name, channel, channel_name: the image's name and the channel's
        number and name; they make the title (see `elbow_title`).
    threshold_mode: "manual", "auto" or "calibrated".
    lower_limit: the channel's lower limit, or None when none is set.

    The curve is the natural log of the number of candidate spots above each
    threshold, smoothed, counted before spots that share a peak are merged
    (so it is not the final number of spots). The legend names each line:
    - "Selected threshold = 11.0": the threshold used.
    - "Lower limit = 15.0", when a lower limit is set.
    - "Automatic threshold = 13.0 (not used)" for a manual or calibrated
      threshold, and "Automatic threshold = 13.0 (raised to the lower limit)"
      when the lower limit raised the automatic threshold. When the elbow
      method gives no value, the legend says "No automatic threshold found".

    Returns a matplotlib `Figure` that is not tied to `matplotlib.pyplot`, or
    None when there are no elbow values (big-fish found no candidate spots),
    in which case nothing is drawn.
    """
    thresholds = detected.get("elbow_thresholds")
    counts = detected.get("elbow_counts")
    if not _has_elbow_values(thresholds, counts):
        return None
    thresholds = np.asarray(thresholds, dtype=float)
    counts = np.asarray(counts, dtype=float)
    used = detected.get("threshold")
    auto_value = detected.get("auto_threshold")

    # What the second line shows, and what its legend says.
    automatic_text = None
    if threshold_mode == "auto":
        if used is None:
            automatic_text = "No automatic threshold found"
        elif auto_value is not None and float(used) > float(auto_value):
            auto_value = float(auto_value)
            automatic_text = f"Automatic threshold = {_value_text(auto_value)} (raised to the lower limit)"
        else:
            auto_value = None
    else:
        if auto_value is None:
            auto_value = _elbow_method_value(thresholds, counts)
        if auto_value is None:
            automatic_text = "No automatic threshold found"
        else:
            automatic_text = f"Automatic threshold = {_value_text(auto_value)} (not used)"

    figure = Figure(figsize=ELBOW_FIGURE_SIZE, dpi=FIGURE_DPI, layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    axes.plot(thresholds, counts, color=ELBOW_CURVE_COLOUR, linewidth=2)

    shown = []
    if used is not None:
        used = float(used)
        shown.append(used)
        axes.axvline(
            used, color=SELECTED_COLOUR, linewidth=1.5,
            label=f"Selected threshold = {_value_text(used)}",
        )
        axes.scatter(
            [used], [np.interp(used, thresholds, counts)], marker="D", s=60,
            color=SELECTED_COLOUR, zorder=3,
        )
    if lower_limit is not None:
        shown.append(float(lower_limit))
        axes.axvline(
            float(lower_limit), color=LOWER_LIMIT_COLOUR, linewidth=1.5, linestyle=":",
            label=f"Lower limit = {_value_text(lower_limit)}",
        )
    if automatic_text is not None:
        if auto_value is not None:
            shown.append(auto_value)
            axes.axvline(
                auto_value, color=AUTOMATIC_COLOUR, linewidth=1.5, linestyle="--",
                label=automatic_text,
            )
        else:
            # A line that is not drawn, so that the legend can still say it.
            axes.plot([], [], color="none", label=automatic_text)

    # Lines outside the curve (a manual value, for example) stay in view.
    low = min([float(thresholds.min())] + shown)
    high = max([float(thresholds.max())] + shown)
    margin = 0.03 * max(high - low, 1e-9)
    axes.set_xlim(low - margin, high + margin)

    axes.set_title(
        elbow_title(image_name, channel, threshold_mode, channel_name),
        fontweight="bold", fontsize=11,
    )
    axes.set_xlabel("Thresholds", fontweight="bold", fontsize=12)
    axes.set_ylabel(ELBOW_Y_LABEL, fontweight="bold", fontsize=10)
    axes.legend(loc="upper right", prop={"size": 10})
    return figure


def write_elbow_plot(run_folder, image_name, detected, channel, threshold_mode,
                     lower_limit=None, channel_name=None):
    """
    Write an image's elbow plot as `qc/<image>_ch<index>_elbow.png` in the run folder.

    detected: the dict returned by `detect_spots`; the other arguments are
    those of `draw_elbow_plot`, with the run folder and the image's name first.
    The figure is first written under a temporary name and then renamed. The
    `qc` folder is made when it does not exist. Works from any thread and
    needs no screen.

    Returns the path of the figure, or None when there are no elbow values
    (big-fish found no candidate spots): nothing is written then, and the
    caller can log a warning. A file from an earlier run is left as it is.
    """
    figure = draw_elbow_plot(
        detected, image_name, channel, threshold_mode, lower_limit, channel_name
    )
    if figure is None:
        return None
    path = elbow_path(run_folder, image_name, channel)
    _save_figure(figure, path)
    return path


# Calibration plot

def calibration_path(run_folder):
    """Path of the calibration plot: `qc/calibration.png` in the run folder."""
    return Path(run_folder) / QC_FOLDER_NAME / f"{CALIBRATION_FILE_NAME}{QC_EXTENSION}"


def _image_count_text(number, singular="image", plural="images"):
    return f"{number} {singular if number == 1 else plural}"


def draw_calibration_plot(calibration, thresholds, lower_limits=None, channel_names=None):
    """
    Draw the calibration plot of a run and return it, without showing or
    saving it.

    calibration: the calibration table (columns of `outputs.CALIBRATION_COLUMNS`):
        one row for each image of the subset and calibrated channel. Its
        optional column `elbow_threshold` is the elbow method's value before
        the lower limit was applied, while `auto_threshold` is the value after
        it; without the column (a table from an older run) no image is marked
        as raised.
    thresholds: the threshold fixed for each calibrated channel, as a dict
        from channel number to value. A channel missing from it has no
        usable value and no line is drawn.
    lower_limits: optional dict from channel number to the channel's lower
        limit; a channel missing from it, or with None, has none.
    channel_names: optional dict from channel number to the channel's name.

    There is one panel for each channel of the table. A panel shows the
    automatic value of each image of the subset, a line at the median used
    ("Median used = 14.5") and a line at the lower limit when one is set.
    An image whose automatic value was raised to the lower limit (its
    `elbow_threshold` is below its `auto_threshold`) is a triangle at the
    value used, with an open circle, joined by a dotted line, at the value
    before the limit; the legend counts these images apart.
    Images left out of the median (not read, or no automatic value) are marked
    with a cross at the bottom of the panel and are not counted in the median;
    their number is in the legend. Image names are written along the axis for
    up to CALIBRATION_MAX_NAMED_IMAGES images, and numbers above that (the
    order of the images in calibration.csv).

    Returns a matplotlib `Figure` that is not tied to `matplotlib.pyplot`, or
    None when the table has no rows.
    """
    rows = list(calibration.to_dict("records"))
    if not rows:
        return None
    lower_limits = lower_limits or {}
    channel_names = channel_names or {}
    channels = []
    for row in rows:
        if int(row["channel"]) not in channels:
            channels.append(int(row["channel"]))

    largest = max(sum(int(row["channel"]) == channel for row in rows) for channel in channels)
    width = float(np.clip(0.3 * largest + 3, 6.5, 14)) + CALIBRATION_LEGEND_WIDTH
    figure = Figure(
        figsize=(width, CALIBRATION_PANEL_HEIGHT * len(channels) + 0.8),
        dpi=FIGURE_DPI, layout="constrained",
    )
    FigureCanvasAgg(figure)
    panels = figure.subplots(len(channels), 1, squeeze=False)[:, 0]
    figure.suptitle("Calibration of the automatic threshold", fontsize=12, fontweight="bold")

    for axes, channel in zip(panels, channels):
        channel_rows = [row for row in rows if int(row["channel"]) == channel]
        _draw_calibration_panel(
            axes, channel, channel_rows, thresholds.get(channel), lower_limits.get(channel),
            channel_names.get(channel),
        )
    return figure


def _number_or_nan(value):
    """The value as a float, or NaN when it is missing."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _draw_calibration_panel(axes, channel, rows, threshold, lower_limit, channel_name):
    """One panel of the calibration plot: the images of one channel."""
    positions = np.arange(1, len(rows) + 1)
    values = np.array([
        np.nan if row["auto_threshold"] is None else float(row["auto_threshold"])
        for row in rows
    ])
    counted = np.array([bool(row["used"]) for row in rows]) & np.isfinite(values)
    # The elbow method's value before the lower limit, when the table has it
    # (tables of older runs do not).
    before_limit = np.array([_number_or_nan(row.get("elbow_threshold")) for row in rows])
    raised = counted & (before_limit < values)
    unraised = counted & ~raised

    if unraised.any():
        axes.scatter(
            positions[unraised], values[unraised], s=40, color=ELBOW_CURVE_COLOUR, zorder=3,
            label=f"Automatic value of each image ({_image_count_text(int(unraised.sum()))})",
        )
    if raised.any():
        axes.vlines(
            positions[raised], before_limit[raised], values[raised],
            color=AUTOMATIC_COLOUR, linewidth=1, linestyle=":", zorder=2,
        )
        axes.scatter(
            positions[raised], values[raised], s=55, marker="^", color=AUTOMATIC_COLOUR, zorder=3,
            label=f"Raised to the lower limit ({_image_count_text(int(raised.sum()))})",
        )
        axes.scatter(
            positions[raised], before_limit[raised], s=40, marker="o", facecolors="none",
            edgecolors=AUTOMATIC_COLOUR, linewidths=1.5, zorder=3,
            label="Value before the lower limit was applied",
        )
    if threshold is not None:
        axes.axhline(
            float(threshold), color=SELECTED_COLOUR, linewidth=1.5,
            label=f"Median used = {_value_text(threshold)}",
        )
    else:
        axes.plot([], [], color="none", label="No usable median")
    if lower_limit is not None:
        axes.axhline(
            float(lower_limit), color=LOWER_LIMIT_COLOUR, linewidth=1.5, linestyle=":",
            label=f"Lower limit = {_value_text(lower_limit)}",
        )
    n_left_out = int((~counted).sum())
    if n_left_out:
        axes.scatter(
            positions[~counted], np.full(n_left_out, 0.03), s=50, marker="x", linewidths=2,
            color=CALIBRATION_LEFT_OUT_COLOUR, zorder=3, clip_on=False,
            transform=axes.get_xaxis_transform(),
            label=f"Left out of the median ({_image_count_text(n_left_out)})",
        )

    axes.set_xlim(0.5, len(rows) + 0.5)
    if len(rows) <= CALIBRATION_MAX_NAMED_IMAGES:
        axes.set_xticks(positions)
        axes.set_xticklabels(
            [str(row["image"]) for row in rows], rotation=60, ha="right", fontsize=8
        )
        axes.set_xlabel("Image", fontweight="bold")
    else:
        axes.xaxis.set_major_locator(MaxNLocator(integer=True))
        axes.set_xlabel("Image number (the order in calibration.csv)", fontweight="bold")
    axes.set_ylabel("Automatic threshold", fontweight="bold")
    channel_text = f"Channel {channel}"
    if channel_name:
        channel_text += f" ({channel_name})"
    axes.set_title(channel_text, fontsize=11)
    axes.margins(y=0.15)
    # The legend sits beside the panel so that it never covers a point.
    axes.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0, prop={"size": 9})


def write_calibration_plot(run_folder, calibration, thresholds, lower_limits=None,
                           channel_names=None):
    """
    Write the calibration plot as `qc/calibration.png` in the run folder.

    The arguments are those of `draw_calibration_plot`, with the run folder
    first. The figure is first written under a temporary name and then
    renamed. The `qc` folder is made when it does not exist. Works from any
    thread and needs no screen.

    Returns the path of the figure, or None, with nothing written, when the
    calibration table has no rows.
    """
    figure = draw_calibration_plot(calibration, thresholds, lower_limits, channel_names)
    if figure is None:
        return None
    path = calibration_path(run_folder)
    _save_figure(figure, path)
    return path


# Detection plot

def detection_path(run_folder, image_name, channel):
    """Path of an image's detection plot: `qc/<image>_ch<index>_detection.png` in the run folder."""
    return (
        Path(run_folder) / QC_FOLDER_NAME
        / f"{image_name}_ch{channel}{DETECTION_SUFFIX}{QC_EXTENSION}"
    )


def project_for_detection(channel_image):
    """
    The 2D picture a detection plot is drawn on: the maximum projection of a
    3D channel (z, y, x), or the channel itself when it is 2D (y, x).
    """
    channel_image = np.asarray(channel_image)
    if channel_image.ndim == 2:
        return channel_image
    if channel_image.ndim == 3:
        return channel_image.max(axis=0)
    raise ValueError(
        f"The channel must have 2 or 3 dimensions (y, x or z, y, x); got {channel_image.ndim}."
    )


def detection_title(image_name, channel, n_spots, n_clusters=None, channel_name=None):
    """
    The title of the detection plot, for example
    "slide 3 | channel 2 (jim-exon) | 692 spots | 6 clusters".

    channel: the channel's number.
    channel_name: the channel's name, shown after the number when given.
    n_spots: number of spots drawn. With none, the title ends with
        "no spots found" and says nothing about clusters.
    n_clusters: number of clusters drawn, or None when cluster detection is off.

    A title longer than TITLE_LINE_WIDTH characters is continued on a new line.
    """
    channel_text = f"channel {channel}"
    if channel_name:
        channel_text += f" ({channel_name})"
    items = [str(image_name), channel_text]
    if n_spots == 0:
        items.append("no spots found")
    else:
        items.append(f"{n_spots} spot" if n_spots == 1 else f"{n_spots} spots")
        if n_clusters is not None:
            items.append(f"{n_clusters} cluster" if n_clusters == 1 else f"{n_clusters} clusters")
    return _wrap_items(items, TITLE_LINE_WIDTH)


def _stretch_for_detection(image):
    """
    The image as 8-bit levels (y, x) for display, from 0 to 255: the lowest
    value is 0 and the DETECTION_CONTRAST_PERCENTILE-th percentile and above
    is 255. Only the picture changes; the image given is left as it is.
    """
    image = np.asarray(image, dtype=np.float32)
    low = float(image.min())
    high = float(np.percentile(image, DETECTION_CONTRAST_PERCENTILE))
    if high <= low:
        high = float(image.max())
    if high <= low:
        return np.zeros(image.shape, dtype=np.uint8)
    return (np.clip((image - low) / (high - low), 0, 1) * 255).astype(np.uint8)


def _interpolation(levels, shown_width_px):
    """
    How a picture is fitted to the width it is shown at, in pixels of the
    file. A picture shown larger than its own size keeps its pixels as they
    are ("nearest"), which stays sharp and makes a smaller file. A picture
    shown smaller is smoothed down, matplotlib's own choice (None).
    """
    return "nearest" if levels.shape[1] < shown_width_px else None


def _show_levels(axes, levels, shown_width_px):
    """
    Show 8-bit levels in matplotlib's default colours, as big-fish draws the
    picture. Smoothing the picture to the size it is shown at is done on the
    8-bit levels, which takes far less memory than doing it on colours.

    shown_width_px: the width of the picture in the file, in pixels.
    """
    axes.imshow(
        levels, cmap=DETECTION_COLOUR_MAP, vmin=0, vmax=255, interpolation_stage="data",
        interpolation=_interpolation(levels, shown_width_px),
    )


def _yx_positions(positions, name):
    """The y and x columns (the last two) of 2D or 3D positions, as an array of floats (n, 2)."""
    positions = np.asarray(positions, dtype=float)
    if positions.size == 0:
        return np.zeros((0, 2))
    if positions.ndim != 2 or positions.shape[1] not in (2, 3):
        raise ValueError(
            f"{name} needs one row for each position with two columns (y, x) or "
            f"three columns (z, y, x); got shape {positions.shape}."
        )
    return positions[:, -2:]


def draw_detection_plot(image, spots, image_name, channel, spot_radius_px, clusters=None,
                        cluster_radius_px=None, channel_name=None):
    """
    Draw the detection plot of one image and channel and return it, without
    showing or saving it.

    image: the 2D picture to draw on (y, x): the maximum projection of a 3D
        channel (see `project_for_detection`), or the channel itself when it is 2D.
    spots: final spot positions in pixels, one row for each spot, with two
        columns (y, x) or three (z, y, x). The last two columns are used.
    image_name, channel, channel_name: the image's name and the channel's
        number and name; they make the title (see `detection_title`).
    spot_radius_px: radius of the circle drawn for each spot, in pixels: one
        number, or the (z, y, x) or (y, x) values from `get_spot_radius_px`,
        of which the last is used.
    clusters: cluster positions in pixels, in the same form as `spots`, or
        None when cluster detection is off. A cluster is drawn as a cyan
        outline with no fill, so that the spots under it stay visible.
    cluster_radius_px: radius of the cluster shape in pixels (the cluster
        radius in nm divided by the pixel size); needed when clusters are given.

    The picture on the left is the image with its contrast stretched for
    display (as big-fish does for `plot_detection`); the picture on the right
    has the detections on it, as orange circles for the spots and cyan outlines
    for the clusters. Without any spot only the image is drawn, and the title
    says that no spots were found.

    Returns a matplotlib `Figure` that is not tied to `matplotlib.pyplot`.
    """
    image = np.asarray(image)
    if image.ndim != 2:
        raise ValueError(
            f"The detection plot is drawn on a 2D image (y, x); got {image.ndim} dimensions. "
            "Use project_for_detection to make a 3D channel into one."
        )
    spot_positions = _yx_positions(spots, "spots")
    cluster_positions = None if clusters is None else _yx_positions(clusters, "clusters")
    if cluster_positions is not None and len(cluster_positions) and cluster_radius_px is None:
        raise ValueError("cluster_radius_px is needed to draw clusters.")
    n_spots = len(spot_positions)
    n_clusters = None if cluster_positions is None else len(cluster_positions)

    shown = _stretch_for_detection(image)
    # Each picture is half the figure's width, or all of it when only the image is drawn.
    figure_width = DETECTION_FIGURE_WIDTH if n_spots else DETECTION_FIGURE_WIDTH / 2
    picture_width = DETECTION_FIGURE_WIDTH / 2
    figure_height = float(np.clip(
        picture_width * image.shape[0] / image.shape[1] + DETECTION_FIGURE_MARGIN,
        3, DETECTION_MAX_HEIGHT,
    ))
    figure = Figure(
        figsize=(figure_width, figure_height), dpi=DETECTION_FIGURE_DPI, layout="constrained"
    )
    FigureCanvasAgg(figure)
    figure.suptitle(
        detection_title(image_name, channel, n_spots, n_clusters, channel_name),
        fontsize=11, fontweight="bold",
    )

    if n_spots == 0:
        axes = figure.add_subplot()
        _show_levels(axes, shown, DETECTION_FIGURE_WIDTH / 2 * DETECTION_FIGURE_DPI)
        axes.set_title("Image, contrast stretched for display", fontsize=10)
        axes.axis("off")
        return figure

    left, right = figure.subplots(1, 2, sharex=True, sharey=True)
    _show_levels(left, shown, DETECTION_FIGURE_WIDTH / 2 * DETECTION_FIGURE_DPI)
    left.set_title("Image, contrast stretched for display", fontsize=10)
    _show_levels(right, shown, DETECTION_FIGURE_WIDTH / 2 * DETECTION_FIGURE_DPI)
    legend = "orange circles: spots"
    if n_clusters is not None:
        legend += "; cyan outlines: clusters"
    right.set_title(f"Detection results ({legend})", fontsize=10)

    # One collection for all the circles keeps a picture with tens of thousands of spots quick.
    radius = float(np.ravel(spot_radius_px)[-1])
    diameters = np.full(n_spots, 2 * radius)
    circles = EllipseCollection(
        diameters, diameters, np.zeros(n_spots), units="xy",
        offsets=spot_positions[:, ::-1], offset_transform=right.transData,
        facecolors="none", edgecolors=SPOT_COLOUR, linewidths=SPOT_LINE_WIDTH,
    )
    right.add_collection(circles, autolim=False)
    if n_clusters:
        cluster_radius = float(cluster_radius_px)
        shapes = PatchCollection(
            [
                RegularPolygon((x, y), CLUSTER_SHAPE_SIDES, radius=cluster_radius)
                for y, x in cluster_positions
            ],
            facecolors="none", edgecolors=CLUSTER_COLOUR, linewidths=CLUSTER_LINE_WIDTH,
        )
        right.add_collection(shapes, autolim=False)
    left.axis("off")
    right.axis("off")
    return figure


def write_detection_plot(run_folder, image_name, image, spots, channel, spot_radius_px,
                         clusters=None, cluster_radius_px=None, channel_name=None):
    """
    Write an image's detection plot as `qc/<image>_ch<index>_detection.png` in the run folder.

    The other arguments are those of `draw_detection_plot`, with the run
    folder and the image's name first. The figure is first written under a
    temporary name and then renamed. The `qc` folder is made when it does not
    exist. Works from any thread and needs no screen.

    Returns the path of the figure.
    """
    figure = draw_detection_plot(
        image, spots, image_name, channel, spot_radius_px, clusters, cluster_radius_px,
        channel_name,
    )
    path = detection_path(run_folder, image_name, channel)
    _save_figure(figure, path, DETECTION_FIGURE_DPI)
    return path


# Reference spot

def reference_spot_path(run_folder, image_name, channel):
    """Path of an image's reference spot: `qc/<image>_ch<index>_referencespot.tif` in the run folder."""
    return (
        Path(run_folder) / QC_FOLDER_NAME
        / f"{image_name}_ch{channel}{REFERENCE_SPOT_SUFFIX}{REFERENCE_SPOT_EXTENSION}"
    )


def write_reference_spot(run_folder, image_name, channel, reference_spot):
    """
    Write an image's reference spot as `qc/<image>_ch<index>_referencespot.tif` in the run folder.

    reference_spot: the "reference_spot" array that `decompose_dense_regions`
        returns, with its values and data type kept. None when
        decomposition is off or was skipped: nothing is written then.

    The file is first written under a temporary name and then renamed. The
    `qc` folder is made when it does not exist. A file from an earlier run is
    left as it is when nothing is written.

    Returns the path of the file, or None when nothing was written.
    """
    if reference_spot is None:
        return None
    path = reference_spot_path(run_folder, image_name, channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_qc_path(path)
    try:
        with open(temporary, "wb") as file:
            tifffile.imwrite(file, np.asarray(reference_spot))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


# Final QC

def final_png_path(run_folder, image_name, channel):
    """Path of an image's final QC figure: `qc/<image>_ch<index>_final.png` in the run folder."""
    return (
        Path(run_folder) / QC_FOLDER_NAME
        / f"{image_name}_ch{channel}{FINAL_SUFFIX}{QC_EXTENSION}"
    )


def final_html_path(run_folder, image_name, channel):
    """Path of an image's interactive final QC page: `qc/<image>_ch<index>_final.html` in the run folder."""
    return (
        Path(run_folder) / QC_FOLDER_NAME
        / f"{image_name}_ch{channel}{FINAL_SUFFIX}{HTML_EXTENSION}"
    )


def plotly_script_path(run_folder):
    """Path of the copy of plotly's script that the pages of a run share: `qc/plotly.min.js`."""
    return Path(run_folder) / QC_FOLDER_NAME / PLOTLY_SCRIPT_NAME


def channel_qc_paths(run_folder, image_name, channel):
    """
    Paths of every QC file that one image and channel can have in the run
    folder: the elbow plot, the detection plot, the reference spot and both
    forms of the final QC. The Cellpose QC figure (one per image) is not
    among them.
    """
    return [
        elbow_path(run_folder, image_name, channel),
        detection_path(run_folder, image_name, channel),
        reference_spot_path(run_folder, image_name, channel),
        final_png_path(run_folder, image_name, channel),
        final_html_path(run_folder, image_name, channel),
    ]


def final_title(image_name, channel, n_spots, n_clusters=None, n_cells=None,
                channel_name=None, text_left_out=False):
    """
    The title of the final QC, for example
    "slide 3 | channel 2 (jim-exon) | 44 cells | 692 spots | 6 clusters".

    channel: the channel's number.
    channel_name: the channel's name, shown after the number when given.
    n_cells: number of cells, or None or 0 when there are none: the title
        then says "no cells".
    n_spots: number of spots. With none, the title says "no spots found" and
        nothing about clusters.
    n_clusters: number of clusters, or None when cluster detection is off.
    text_left_out: True when the cell numbers are not written on the cells
        because there are too many; the title says so.

    A title longer than TITLE_LINE_WIDTH characters is continued on a new line.
    """
    channel_text = f"channel {channel}"
    if channel_name:
        channel_text += f" ({channel_name})"
    items = [str(image_name), channel_text]
    if not n_cells:
        items.append("no cells")
    else:
        cell_text = f"{n_cells} cell" if n_cells == 1 else f"{n_cells} cells"
        if text_left_out:
            cell_text += f" (too many to number, over {FINAL_MAX_LABELLED_CELLS})"
        items.append(cell_text)
    if n_spots == 0:
        items.append("no spots found")
    else:
        items.append(f"{n_spots} spot" if n_spots == 1 else f"{n_spots} spots")
        if n_clusters is not None:
            items.append(f"{n_clusters} cluster" if n_clusters == 1 else f"{n_clusters} clusters")
    return _wrap_items(items, TITLE_LINE_WIDTH)


@dataclass
class _FinalView:
    """What both forms of the final QC draw: the picture, the cells, the spots and the clusters."""

    picture: np.ndarray
    # Cells: their label values (sorted), outlines as polygons of (y, x) points,
    # the point on each cell where its text goes, and per-cell numbers.
    ids: np.ndarray
    outlines: list
    anchors: np.ndarray
    cell_values: dict
    # Spots: positions (y, x), and the cell, cluster, number and other values of each.
    spot_yx: np.ndarray
    spot_cell: np.ndarray
    spot_cluster: np.ndarray
    spot_table: object
    # Clusters, or None when cluster detection is off.
    cluster_yx: np.ndarray
    cluster_table: object
    has_clusters: bool
    # The label image of the cells drawn, renumbered 1, 2, 3... in the order
    # of `ids` (0 elsewhere), or None when no cell is drawn.
    labels: object

    @property
    def has_cells(self):
        return len(self.ids) > 0


def _table_yx(table):
    """
    Positions (y, x) in pixels of the rows of a spots or clusters table, as
    float32 (n, 2). The subpixel columns are used when the table has them (and
    the plain pixel columns for a row where one is empty).
    """
    if table is None or len(table) == 0:
        return np.zeros((0, 2), dtype=np.float32)
    columns = []
    for axis in "yx":
        values = np.asarray(table[f"{axis}_px"], dtype=float)
        if f"{axis}_sub_px" in table:
            fitted = np.asarray(table[f"{axis}_sub_px"], dtype=float)
            values = np.where(np.isnan(fitted), values, fitted)
        columns.append(values)
    return np.column_stack(columns).astype(np.float32)


def _integer_column(table, name, default, length):
    """A whole-number column of a table, or `default` for every row when the table has none."""
    if table is None or length == 0 or name not in table:
        return np.full(length, default, dtype=np.int64)
    return np.asarray(table[name], dtype=np.int64)


# Label images are read this many pixels at a time, so that working out the
# cells does not need a copy of the whole image.
_LABEL_CHUNK_PIXELS = 1 << 22


def _row_chunks(labels):
    """The label image as (first row, rows) pieces of about _LABEL_CHUNK_PIXELS pixels."""
    step = max(1, _LABEL_CHUNK_PIXELS // max(labels.shape[1], 1))
    for first in range(0, labels.shape[0], step):
        yield first, labels[first:first + step]


def _drawn_cell_ids(labels, cells):
    """
    The numbers of the cells to draw, sorted: those in the label image and,
    when a cells table is given, in the table too. Cells that the table leaves
    out (for example border cells that were dropped) are not drawn. The work
    depends on the number of cells and not on the largest cell number.
    """
    found = [np.unique(chunk) for _, chunk in _row_chunks(labels)]
    ids = np.unique(np.concatenate(found)).astype(np.int64) if found else np.zeros(0, np.int64)
    ids = ids[ids > 0]
    if cells is not None:
        listed = np.asarray(cells["cell_id"], dtype=np.int64) if "cell_id" in cells else []
        ids = np.intersect1d(ids, listed)
    return ids


def _renumbered(labels, ids):
    """
    The label image with the cells in `ids` (sorted) renumbered 1, 2, 3... in
    that order and every other pixel set to 0, in the smallest whole-number
    type that holds the new numbers.
    """
    renumbered = np.zeros(labels.shape, dtype=np.min_scalar_type(len(ids)))
    for first, chunk in _row_chunks(labels):
        chunk = chunk.astype(np.int64)
        position = np.minimum(np.searchsorted(ids, chunk), len(ids) - 1)
        renumbered[first:first + len(chunk)] = np.where(ids[position] == chunk, position + 1, 0)
    return renumbered


def _drawn_cell_of(cell_ids, ids):
    """`cell_ids` with -1 in place of every number that is not in `ids` (sorted)."""
    if len(ids) == 0:
        return np.full(len(cell_ids), -1, dtype=np.int64)
    position = np.minimum(np.searchsorted(ids, cell_ids), len(ids) - 1)
    return np.where(ids[position] == cell_ids, cell_ids, -1)


def _cell_shapes(labels, ids):
    """
    The cells of a label image renumbered 1, 2, 3... (see `_renumbered`), whose
    numbers in the original are `ids`: for each, its outline as a list of
    polygons (arrays of (y, x) points, simplified to FINAL_OUTLINE_TOLERANCE_PX),
    and a point inside it, near its centre, where its text goes.
    Returns the numbers of the cells found (in `ids` order), the outlines and
    the anchor points.
    """
    from scipy import ndimage
    from skimage import measure

    found, outlines, anchors = [], [], []
    for index, region in enumerate(ndimage.find_objects(labels)):
        if region is None:
            continue
        mask = labels[region] == index + 1
        offset = np.array([region[0].start, region[1].start], dtype=float)
        padded = np.pad(mask, 1).astype(np.float32)
        for contour in measure.find_contours(padded, 0.5):
            polygon = measure.approximate_polygon(contour, FINAL_OUTLINE_TOLERANCE_PX)
            outlines.append(polygon - 1 + offset)
        rows, columns = np.nonzero(mask)
        centre = np.array([rows.mean(), columns.mean()])
        nearest = np.round(centre).astype(int)
        if not mask[nearest[0], nearest[1]]:
            closest = np.argmin((rows - centre[0]) ** 2 + (columns - centre[1]) ** 2)
            centre = np.array([rows[closest], columns[closest]], dtype=float)
        found.append(ids[index])
        anchors.append(centre + offset)
    return np.array(found, dtype=np.int64), outlines, np.array(anchors, dtype=float).reshape(-1, 2)


# Numbers of the cells table that the page shows on hover.
_CELL_VALUE_COLUMNS = (
    "n_spots", "n_spots_in_clusters", "n_spots_outside_clusters", "n_clusters",
    "area_px", "area_um2",
)


def _cell_values(cells, ids, spot_cell):
    """
    The numbers of each cell, as a dict from column name to an array in the
    order of `ids` (NaN where unknown). They come from the cells table; the
    number of spots is counted from the spots' cells when the table has no
    number for a cell. Every cell of `spot_cell` is one of `ids`.
    """
    values = {}
    if cells is not None and len(cells) and len(ids):
        table_ids = np.asarray(cells["cell_id"], dtype=np.int64)
        order = np.argsort(table_ids)
        sorted_ids = table_ids[order]
        position = np.clip(np.searchsorted(sorted_ids, ids), 0, len(sorted_ids) - 1)
        found = sorted_ids[position] == ids
        for name in _CELL_VALUE_COLUMNS:
            if name in cells:
                column = np.asarray(cells[name], dtype=float)[order][position]
                values[name] = np.where(found, column, np.nan)
    if len(ids):
        inside = np.searchsorted(ids, spot_cell[spot_cell >= 0])
        counted = np.bincount(inside, minlength=len(ids)).astype(float)
        known = values.get("n_spots")
        values["n_spots"] = counted if known is None else np.where(np.isnan(known), counted, known)
    return values


def _final_view(picture, spots, clusters, cells, labels):
    """Check the arguments of the final QC and gather what is drawn (see `draw_final_qc`)."""
    picture = project_for_detection(picture)
    ids = np.zeros(0, dtype=np.int64)
    if labels is not None:
        labels = np.asarray(labels)
        if labels.shape != picture.shape:
            raise ValueError(
                f"The label image has shape {labels.shape}, but the picture has shape "
                f"{picture.shape}."
            )
        ids = _drawn_cell_ids(labels, cells)
    # From here on, `labels` holds only the cells drawn, renumbered from 1.
    labels = _renumbered(labels, ids) if len(ids) else None

    spot_yx = _table_yx(spots)
    n_spots = len(spot_yx)
    spot_cluster = _integer_column(spots, "cluster_id", -1, n_spots)
    if labels is None:
        spot_cell = np.full(n_spots, -1, dtype=np.int64)
    elif "cell_id" in (spots if n_spots else ()):
        spot_cell = _drawn_cell_of(_integer_column(spots, "cell_id", -1, n_spots), ids)
    elif n_spots:
        rows = np.clip(np.round(spot_yx[:, 0]).astype(int), 0, labels.shape[0] - 1)
        columns = np.clip(np.round(spot_yx[:, 1]).astype(int), 0, labels.shape[1] - 1)
        found = labels[rows, columns].astype(np.int64)
        spot_cell = np.where(found > 0, ids[np.maximum(found - 1, 0)], -1)
    else:
        spot_cell = np.zeros(0, dtype=np.int64)

    if labels is None:
        outlines, anchors = [], np.zeros((0, 2))
    else:
        ids, outlines, anchors = _cell_shapes(labels, ids)
    return _FinalView(
        picture=picture, ids=ids, outlines=outlines, anchors=anchors,
        cell_values=_cell_values(cells, ids, spot_cell),
        spot_yx=spot_yx, spot_cell=spot_cell, spot_cluster=spot_cluster, spot_table=spots,
        cluster_yx=_table_yx(clusters), cluster_table=clusters,
        has_clusters=clusters is not None, labels=labels,
    )


def _final_counts(view):
    return len(view.ids), len(view.spot_yx), (len(view.cluster_yx) if view.has_clusters else None)


def _grey_levels(picture):
    """The picture as 8-bit grey levels (y, x), with its contrast stretched for display."""
    return _stretch_for_display(picture)[..., 0]


def draw_final_qc(picture, spots, clusters, cells, labels, image_name, channel,
                  channel_name=None):
    """
    Draw the final QC of one image and channel as a figure and return it,
    without showing or saving it.

    picture: the picture to draw on, (y, x): the maximum projection of the
        channel. A 3D channel (z, y, x) is projected here.
    spots: the channel's spots table as written in `per_image/` (the columns
        of spec 8.2): `y_px` and `x_px`, or `y_sub_px` and `x_sub_px` when the
        table has them, and `cell_id`. None for no spots.
    clusters: the clusters table, or None when cluster detection is off.
    cells: the cells table of the channel, or None. When it is given, only
        the cells in it are drawn, counted and numbered: cells of the label
        image that it leaves out (border cells that were dropped, for
        example) are not shown. Each cell's number of spots is taken from it.
        Without a table every cell of the label image is drawn.
    labels: the label image (y, x) of the cells, or None when there is none.
        Without labels the figure has no outlines and no cell text, and the
        title says there are no cells.
    image_name, channel, channel_name: the image's name and the channel's
        number and name; they make the title (see `final_title`).

    The picture is grey with its contrast stretched for display. Spots in a
    cell are orange circles and spots outside the cells are pink crosses;
    clusters are cyan pentagon outlines with no fill; cells have green
    outlines. On each cell the text "12: 34" gives its number and its number
    of spots. With more than FINAL_MAX_LABELLED_CELLS cells the text is left
    out and the title says so. A legend below the picture says what each mark
    is.

    Returns a matplotlib `Figure` that is not tied to `matplotlib.pyplot`.
    """
    view = _final_view(picture, spots, clusters, cells, labels)
    n_cells, n_spots, n_clusters = _final_counts(view)
    text_left_out = n_cells > FINAL_MAX_LABELLED_CELLS
    height, width = view.picture.shape

    figure_height = float(np.clip(
        FINAL_FIGURE_WIDTH * height / width + FINAL_FIGURE_MARGIN, 3, FINAL_MAX_HEIGHT
    ))
    figure = Figure(
        figsize=(FINAL_FIGURE_WIDTH, figure_height), dpi=FINAL_FIGURE_DPI, layout="constrained"
    )
    FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    levels = _grey_levels(view.picture)
    axes.imshow(
        levels, cmap="gray", vmin=0, vmax=255, interpolation_stage="data",
        interpolation=_interpolation(levels, FINAL_FIGURE_WIDTH * FINAL_FIGURE_DPI),
    )
    axes.axis("off")
    figure.suptitle(
        final_title(
            image_name, channel, n_spots, n_clusters, n_cells, channel_name, text_left_out
        ),
        fontsize=11, fontweight="bold",
    )

    legend = []
    if view.has_cells:
        axes.add_collection(
            LineCollection(
                [polygon[:, ::-1] for polygon in view.outlines],
                colors=FINAL_OUTLINE_COLOUR, linewidths=0.8,
            ),
            autolim=False,
        )
        legend.append(Line2D([], [], color=FINAL_OUTLINE_COLOUR, linewidth=1.5, label="Cell outline"))

    inside = view.spot_cell >= 0
    if inside.any():
        axes.scatter(
            view.spot_yx[inside, 1], view.spot_yx[inside, 0], s=12, marker="o",
            facecolors="none", edgecolors=FINAL_SPOT_COLOUR, linewidths=0.6,
        )
        legend.append(Line2D(
            [], [], linestyle="", marker="o", markerfacecolor="none",
            markeredgecolor=FINAL_SPOT_COLOUR, label="Spot inside a cell",
        ))
    if (~inside).any():
        axes.scatter(
            view.spot_yx[~inside, 1], view.spot_yx[~inside, 0], s=12, marker="x",
            color=FINAL_OUTSIDE_SPOT_COLOUR, linewidths=0.6,
        )
        legend.append(Line2D(
            [], [], linestyle="", marker="x", color=FINAL_OUTSIDE_SPOT_COLOUR,
            label="Spot outside the cells" if view.has_cells else "Spot",
        ))
    if n_clusters:
        axes.scatter(
            view.cluster_yx[:, 1], view.cluster_yx[:, 0], s=110, marker="p",
            facecolors="none", edgecolors=FINAL_CLUSTER_COLOUR, linewidths=1.5,
        )
        legend.append(Line2D(
            [], [], linestyle="", marker="p", markersize=9, markerfacecolor="none",
            markeredgecolor=FINAL_CLUSTER_COLOUR, label="Cluster of spots",
        ))

    if view.has_cells and not text_left_out:
        size = 9 if n_cells <= 60 else 7 if n_cells <= 150 else 5.5
        counts = view.cell_values["n_spots"]
        for cell_id, count, (row, column) in zip(view.ids, counts, view.anchors):
            axes.text(
                column, row, f"{cell_id}: {int(count)}", color="white", fontsize=size,
                ha="center", va="center", fontweight="bold",
                path_effects=[withStroke(linewidth=1.5, foreground="black")],
            )
        legend.append(Line2D(
            [], [], linestyle="", label="On each cell: its number, then its number of spots",
        ))
    if legend:
        axes.legend(
            handles=legend, loc="upper center", bbox_to_anchor=(0.5, -0.005),
            ncol=len(legend), frameon=False, fontsize=9, handlelength=1.5, columnspacing=1.5,
        )
    return figure


def _write_atomically(path, write, temporary=None):
    """
    Write a file under a temporary name, then rename it, so that a half-written
    file never has the final name. `write` is called with the temporary path.
    The folder is made when it does not exist. A temporary file left by a
    failure is removed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_qc_path(path) if temporary is None else Path(temporary)
    try:
        write(temporary)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_final_qc(run_folder, image_name, picture, spots, clusters, cells, labels, channel,
                   channel_name=None):
    """
    Write an image's final QC figure as `qc/<image>_ch<index>_final.png` in the run folder.

    The other arguments are those of `draw_final_qc`, with the run folder and
    the image's name first. The figure is first written under a temporary name
    and then renamed. The `qc` folder is made when it does not exist. Works
    from any thread and needs no screen.

    Returns the path of the figure.
    """
    figure = draw_final_qc(
        picture, spots, clusters, cells, labels, image_name, channel, channel_name
    )
    path = final_png_path(run_folder, image_name, channel)
    _save_figure(figure, path, FINAL_FIGURE_DPI)
    return path


# Final QC as a page

def _picture_data_address(picture):
    """
    The picture as a PNG of 8-bit grey levels with its contrast stretched, as a
    text that a web page can show (a `data:` address). A picture with a side
    longer than HTML_MAX_IMAGE_SIDE is reduced to that side, by averaging.
    """
    from PIL import Image

    levels = Image.fromarray(_grey_levels(picture), mode="L")
    height, width = picture.shape
    longest = max(height, width)
    if longest > HTML_MAX_IMAGE_SIDE:
        scale = HTML_MAX_IMAGE_SIDE / longest
        levels = levels.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.BOX
        )
    buffer = io.BytesIO()
    levels.save(buffer, format="PNG", compress_level=6)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _outline_points(outlines):
    """All the outlines as one line for plotly: x and y as float32, with a gap (NaN) between polygons."""
    if not outlines:
        return np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.float32)
    gap = np.full((1, 2), np.nan)
    points = np.concatenate([part for polygon in outlines for part in (polygon, gap)])
    return points[:, 1].astype(np.float32), points[:, 0].astype(np.float32)


def _cell_hover_points(view):
    """
    Invisible points that answer a hover on a cell: one at the text point of
    each cell and a grid of points over the cells. Returns their (y, x) and
    the index of their cell in `view.ids`.
    """
    height, width = view.picture.shape
    step = max(HTML_HOVER_GRID_MIN_STEP_PX, round(max(height, width) / HTML_HOVER_GRID_POINTS_ACROSS))
    rows = np.arange(step // 2, height, step)
    columns = np.arange(step // 2, width, step)
    sampled = view.labels[np.ix_(rows, columns)]
    found_rows, found_columns = np.nonzero(sampled)
    grid = np.column_stack([rows[found_rows], columns[found_columns]]).astype(float)
    grid_cells = sampled[found_rows, found_columns].astype(np.int64) - 1
    positions = np.concatenate([view.anchors, grid])
    cell_index = np.concatenate([np.arange(len(view.ids)), grid_cells])
    return positions.astype(np.float32), cell_index


def _hover_dtype(view):
    """
    The type for the numbers behind the hover text: 32-bit floats, which hold
    whole numbers exactly up to 16,777,216, or 64-bit floats when a cell has a
    larger number.
    """
    return np.float64 if len(view.ids) and view.ids.max() > 2 ** 24 else np.float32


def _cell_hover_template(view):
    """The hover text of a cell and the columns it needs, in order, from `view.cell_values`."""
    columns = ["n_spots", "n_spots_in_clusters", "n_spots_outside_clusters", "n_clusters"]
    names = {
        "n_spots": "Spots", "n_spots_in_clusters": "Spots in clusters",
        "n_spots_outside_clusters": "Spots outside clusters", "n_clusters": "Clusters",
    }
    used = [name for name in columns if name in view.cell_values]
    lines = ["<b>Cell %{customdata[0]:.0f}</b>"]
    for position, name in enumerate(used, start=1):
        lines.append(f"{names[name]}: %{{customdata[{position}]:.0f}}")
    if "area_px" in view.cell_values:
        position = len(used) + 1
        used.append("area_px")
        line = f"Area: %{{customdata[{position}]:,.0f}} px"
        if "area_um2" in view.cell_values:
            used.append("area_um2")
            line += f" (%{{customdata[{position + 1}]:.1f}} µm²)"
        lines.append(line)
    return "<br>".join(lines) + "<extra></extra>", used


def _spot_traces(go, view):
    """
    The traces for the spots: spots in a cell as circles and spots outside the
    cells as crosses. Each kind is split by whether the spot is in a cluster,
    only so that the hover text can say it; the pieces of one kind switch on
    and off together.
    """
    traces = []
    n_spots = len(view.spot_yx)
    if n_spots == 0:
        return traces
    table = view.spot_table
    spot_ids = _integer_column(table, "spot_id", 0, n_spots)
    if "spot_id" not in table:
        spot_ids = np.arange(n_spots)
    in_cell = view.spot_cell >= 0
    in_cluster = view.spot_cluster >= 0
    kinds = (
        (True, "Spots inside cells", "circle-open", FINAL_SPOT_COLOUR),
        (False, "Spots outside cells" if view.has_cells else "Spots", "x-thin-open",
         FINAL_OUTSIDE_SPOT_COLOUR),
    )
    for is_inside, name, symbol, colour in kinds:
        first = True
        for clustered in (True, False):
            chosen = (in_cell == is_inside) & (in_cluster == clustered)
            if not chosen.any():
                continue
            fields = [spot_ids[chosen]]
            lines = ["<b>Spot %{customdata[0]:.0f}</b>"]
            if view.has_cells:
                if is_inside:
                    fields.append(view.spot_cell[chosen])
                    lines.append(f"Cell: %{{customdata[{len(fields) - 1}]:.0f}}")
                else:
                    lines.append("Outside the cells")
            if view.has_clusters:
                if clustered:
                    fields.append(view.spot_cluster[chosen])
                    lines.append(f"Cluster: %{{customdata[{len(fields) - 1}]:.0f}}")
                else:
                    lines.append("Not in a cluster")
            if "snr" in table:
                fields.append(np.asarray(table["snr"], dtype=float)[chosen])
                lines.append(f"SNR: %{{customdata[{len(fields) - 1}]:.2f}}")
            if "log_intensity" in table:
                fields.append(np.asarray(table["log_intensity"], dtype=float)[chosen])
                lines.append(f"Log intensity: %{{customdata[{len(fields) - 1}]:.2f}}")
            traces.append(go.Scattergl(
                x=view.spot_yx[chosen, 1], y=view.spot_yx[chosen, 0], mode="markers",
                name=name, legendgroup=name, showlegend=first,
                marker=dict(symbol=symbol, size=7, color=colour, line=dict(width=1.2, color=colour)),
                customdata=np.column_stack(fields).astype(_hover_dtype(view)),
                hovertemplate="<br>".join(lines) + "<extra></extra>",
            ))
            first = False
    return traces


def _cluster_trace(go, view):
    """The trace for the clusters, or None when there are none."""
    n_clusters = len(view.cluster_yx)
    if n_clusters == 0:
        return None
    table = view.cluster_table
    cluster_ids = (
        np.asarray(table["cluster_id"], dtype=np.int64) if "cluster_id" in table
        else np.arange(n_clusters)
    )
    cluster_cells = _drawn_cell_of(_integer_column(table, "cell_id", -1, n_clusters), view.ids)
    cluster_sizes = np.asarray(table["n_spots"]) if "n_spots" in table else None
    texts = []
    for position in range(n_clusters):
        lines = [f"<b>Cluster {cluster_ids[position]}</b>"]
        if cluster_sizes is not None:
            lines.append(f"{int(cluster_sizes[position])} spots")
        if view.has_cells:
            lines.append(
                f"In cell {cluster_cells[position]}" if cluster_cells[position] >= 0
                else "Outside the cells"
            )
        texts.append("<br>".join(lines))
    return go.Scattergl(
        x=view.cluster_yx[:, 1], y=view.cluster_yx[:, 0], mode="markers", name="Clusters",
        marker=dict(symbol="pentagon-open", size=14, color=FINAL_CLUSTER_COLOUR,
                    line=dict(width=2, color=FINAL_CLUSTER_COLOUR)),
        hovertext=texts, hovertemplate="%{hovertext}<extra></extra>",
    )


def draw_final_html(picture, spots, clusters, cells, labels, image_name, channel,
                    channel_name=None):
    """
    Draw the final QC of one image and channel as an interactive plotly figure
    and return it, without saving it. The arguments are those of `draw_final_qc`.

    The picture is the maximum projection in 8-bit with its contrast
    stretched, at full size up to HTML_MAX_IMAGE_SIDE pixels on its longer
    side and reduced above that; positions stay in the pixels of the picture
    given. The figure can be zoomed and panned.
    - Spots inside cells are orange circles, spots outside the cells pink
      crosses, clusters cyan pentagon outlines with no fill and cells have
      green outlines. Each can
      be switched on and off by clicking its name in the legend.
    - Hovering on a cell gives its number and the numbers of the cells table
      (spots, spots in clusters, spots outside clusters, clusters, area).
    - Hovering on a spot gives its number, its cell and cluster, and its SNR
      and log intensity when the table has them.
    - Hovering on a cluster gives its number, its number of spots and its cell.

    Spots are drawn with plotly's WebGL scatter and all the outlines are one
    trace, so that a full-size image with tens of thousands of spots and over
    a thousand cells stays smooth. `plotly` is loaded here and not when the
    module is imported.
    """
    import plotly.graph_objects as go

    view = _final_view(picture, spots, clusters, cells, labels)
    n_cells, n_spots, n_clusters = _final_counts(view)
    height, width = view.picture.shape

    figure = go.Figure()
    if view.has_cells:
        outline_x, outline_y = _outline_points(view.outlines)
        figure.add_trace(go.Scattergl(
            x=outline_x, y=outline_y, mode="lines", name="Cell outlines", legendgroup="cells",
            line=dict(width=1.5, color=FINAL_OUTLINE_COLOUR), hoverinfo="skip",
        ))
    figure.add_traces(_spot_traces(go, view))
    cluster_trace = _cluster_trace(go, view) if view.has_clusters else None
    if cluster_trace is not None:
        figure.add_trace(cluster_trace)
    if view.has_cells:
        # Added last and drawn with tiny invisible markers, so that a spot or a
        # cluster under the pointer is chosen before the cell it lies in.
        template, columns = _cell_hover_template(view)
        positions, cell_index = _cell_hover_points(view)
        values = [view.ids.astype(float)] + [view.cell_values[name] for name in columns]
        figure.add_trace(go.Scattergl(
            x=positions[:, 1], y=positions[:, 0], mode="markers", name="Cell outlines",
            legendgroup="cells", showlegend=False,
            marker=dict(size=2, color="rgba(0,0,0,0)"),
            customdata=np.column_stack(values)[cell_index].astype(_hover_dtype(view)),
            hovertemplate=template,
        ))

    title = final_title(image_name, channel, n_spots, n_clusters, n_cells, channel_name)
    figure.update_layout(
        title=dict(text=html.escape(title).replace("\n", "<br>"), x=0.01, font=dict(size=14)),
        template="plotly_white",
        images=[dict(
            source=_picture_data_address(view.picture), xref="x", yref="y", x=-0.5, y=-0.5,
            sizex=width, sizey=height, sizing="stretch", layer="below",
            xanchor="left", yanchor="top",
        )],
        xaxis=dict(range=[-0.5, width - 0.5], title="x (pixels)", constrain="domain",
                   showgrid=False, zeroline=False),
        yaxis=dict(range=[height - 0.5, -0.5], title="y (pixels)", scaleanchor="x",
                   scaleratio=1, constrain="domain", showgrid=False, zeroline=False),
        legend=dict(itemsizing="constant"),
        hoverdistance=HTML_HOVER_DISTANCE_PX,
        dragmode="pan",
        margin=dict(l=60, r=20, t=80, b=50),
    )
    return figure


def _page_title(image_name, channel, channel_name):
    channel_text = f"channel {channel}" + (f" ({channel_name})" if channel_name else "")
    return html.escape(f"{image_name} | {channel_text} | final QC")


def _write_plotly_script(run_folder):
    """
    Make sure `qc/plotly.min.js` exists in the run folder, whole. Several
    processes can call this at the same moment: each writes its own temporary
    file, named by its process and a random part, and renames it, so a half
    written copy never has the final name. A copy that is already there with
    the right size is left alone.
    """
    from plotly.offline import get_plotlyjs

    data = get_plotlyjs().encode("utf-8")
    path = plotly_script_path(run_folder)
    if path.is_file() and path.stat().st_size == len(data):
        return path
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        _write_atomically(path, lambda target: target.write_bytes(data), temporary)
    except PermissionError:
        # Windows does not rename over a file that another process is reading.
        if not (path.is_file() and path.stat().st_size == len(data)):
            raise
    return path


def write_final_html(run_folder, image_name, picture, spots, clusters, cells, labels, channel,
                     channel_name=None, plotly_script=PLOTLY_EMBEDDED):
    """
    Write an image's interactive final QC as `qc/<image>_ch<index>_final.html`
    in the run folder.

    The other arguments are those of `draw_final_html`, with the run folder
    and the image's name first.
    plotly_script: how the page gets plotly's script, so that it opens without
        an internet connection.
        "embedded" (the default): the script is inside the page, which can be
        sent on its own and is about 4.8 MB larger for it.
        "shared": one copy, `qc/plotly.min.js` (about 4.8 MB), is used by
        every page of the `qc` folder. Pages are small, and must stay in the
        folder with the script.
    The page is first written under a temporary name and then renamed; the
    shared script too, under a name that is the writing process's own. The
    `qc` folder is made when it does not exist. Works from any thread and
    needs no screen.

    Returns the path of the page.
    """
    if plotly_script not in (PLOTLY_SHARED, PLOTLY_EMBEDDED):
        raise ValueError(
            f'plotly_script must be "{PLOTLY_SHARED}" or "{PLOTLY_EMBEDDED}"; got {plotly_script!r}.'
        )
    figure = draw_final_html(
        picture, spots, clusters, cells, labels, image_name, channel, channel_name
    )
    config = {"scrollZoom": True, "displaylogo": False, "responsive": True}
    if plotly_script == PLOTLY_SHARED:
        include = PLOTLY_SCRIPT_NAME
        _write_plotly_script(run_folder)
    else:
        include = True
    page = figure.to_html(
        include_plotlyjs=include, full_html=True, config=config,
        default_width="100%", default_height="92vh",
    )
    page = page.replace(
        "<head>", f"<head><title>{_page_title(image_name, channel, channel_name)}</title>", 1
    )
    path = final_html_path(run_folder, image_name, channel)
    _write_atomically(path, lambda target: target.write_text(page, encoding="utf-8"))
    return path
