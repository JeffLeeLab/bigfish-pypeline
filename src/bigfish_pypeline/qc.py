"""
QC figures: pictures written as PNG files that show a biologist how an image
was processed.

The figures are drawn without a screen and without `matplotlib.pyplot`, so
they can be written from any thread, and they do not change which matplotlib
backend a notebook or app has chosen. `cellpose` and `torch` are imported only
inside the function that needs them, so importing this module never loads them.
"""

import os
import textwrap
from pathlib import Path

import numpy as np
import tifffile
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import EllipseCollection, PatchCollection
from matplotlib.figure import Figure
from matplotlib.patches import RegularPolygon
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

DIAMETER_AUTOMATIC = "diameter chosen by Cellpose"

# Elbow plot
ELBOW_FIGURE_SIZE = (6.5, 5.0)
# Titles of the elbow plot are continued on a new line after this many characters.
ELBOW_TITLE_LINE_WIDTH = 60
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


# Cellpose QC figure

def cellpose_qc_path(run_folder, image_name):
    """Path of an image's Cellpose QC figure: `qc/<image>_cellpose_qc.png` in the run folder."""
    return Path(run_folder) / QC_FOLDER_NAME / f"{image_name}{CELLPOSE_QC_SUFFIX}{QC_EXTENSION}"


def temporary_qc_path(path):
    """Name a QC figure has while it is written: `<image>_cellpose_qc.png.tmp`."""
    path = Path(path)
    return path.with_name(path.name + ".tmp")


def _save_figure(figure, path):
    """
    Write a figure as a PNG file under a temporary name, then rename it, so a
    half-written figure never has the final name. The folder is made when it
    does not exist.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_qc_path(path)
    try:
        figure.savefig(temporary, format="png", dpi=FIGURE_DPI)
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
    diameter: the cell diameter in pixels given to Cellpose, or None when
        Cellpose chooses the size itself.
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

    The four panels are the input image, the cell outlines, the masks in
    colour and Cellpose's flows. Returns a matplotlib `Figure` that is not
    tied to `matplotlib.pyplot`.
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

    The curve is the number of spots found at each candidate threshold. The
    legend names each line:
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
    axes.set_ylabel("Number of mRNAs detected (log scale)", fontweight="bold", fontsize=12)
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
        one row for each image of the subset and calibrated channel.
    thresholds: the threshold fixed for each calibrated channel, as a dict
        from channel number to value. A channel missing from it has no
        usable value and no line is drawn.
    lower_limits: optional dict from channel number to the channel's lower
        limit; a channel missing from it, or with None, has none.
    channel_names: optional dict from channel number to the channel's name.

    There is one panel for each channel of the table. A panel shows the
    automatic value of each image of the subset, a line at the median used
    ("Median used = 14.5") and a line at the lower limit when one is set.
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


def _draw_calibration_panel(axes, channel, rows, threshold, lower_limit, channel_name):
    """One panel of the calibration plot: the images of one channel."""
    positions = np.arange(1, len(rows) + 1)
    values = np.array([
        np.nan if row["auto_threshold"] is None else float(row["auto_threshold"])
        for row in rows
    ])
    counted = np.array([bool(row["used"]) for row in rows]) & np.isfinite(values)

    if counted.any():
        axes.scatter(
            positions[counted], values[counted], s=40, color=ELBOW_CURVE_COLOUR, zorder=3,
            label=f"Automatic value of each image ({_image_count_text(int(counted.sum()))})",
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


def _show_levels(axes, levels):
    """
    Show 8-bit levels in matplotlib's default colours, as big-fish draws the
    picture. Smoothing the picture to the size it is shown at is done on the
    8-bit levels, which takes far less memory than doing it on colours.
    """
    axes.imshow(
        levels, cmap=DETECTION_COLOUR_MAP, vmin=0, vmax=255, interpolation_stage="data"
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
        None when cluster detection is off. A cluster is drawn as a filled
        cyan shape.
    cluster_radius_px: radius of the cluster shape in pixels (the cluster
        radius in nm divided by the pixel size); needed when clusters are given.

    The picture on the left is the image with its contrast stretched for
    display (as big-fish does for `plot_detection`); the picture on the right
    has the detections on it, as orange circles for the spots and cyan shapes
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
    figure = Figure(figsize=(figure_width, figure_height), dpi=FIGURE_DPI, layout="constrained")
    FigureCanvasAgg(figure)
    figure.suptitle(
        detection_title(image_name, channel, n_spots, n_clusters, channel_name),
        fontsize=11, fontweight="bold",
    )

    if n_spots == 0:
        axes = figure.add_subplot()
        _show_levels(axes, shown)
        axes.set_title("Image, contrast stretched for display", fontsize=10)
        axes.axis("off")
        return figure

    left, right = figure.subplots(1, 2, sharex=True, sharey=True)
    _show_levels(left, shown)
    left.set_title("Image, contrast stretched for display", fontsize=10)
    _show_levels(right, shown)
    legend = "orange circles: spots"
    if n_clusters is not None:
        legend += "; cyan shapes: clusters"
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
            facecolors=CLUSTER_COLOUR, edgecolors=CLUSTER_COLOUR, linewidths=CLUSTER_LINE_WIDTH,
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
    _save_figure(figure, path)
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
