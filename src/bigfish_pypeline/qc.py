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
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

QC_FOLDER_NAME = "qc"
CELLPOSE_QC_SUFFIX = "_cellpose_qc"
QC_EXTENSION = ".png"

# Titles wider than this many characters are continued on a new line.
TITLE_LINE_WIDTH = 150
CELLPOSE_FIGURE_WIDTH = 18
# Height of the figure outside the four panels (title and panel names), in inches.
CELLPOSE_FIGURE_MARGIN = 1.0
FIGURE_DPI = 150

DIAMETER_AUTOMATIC = "diameter chosen by Cellpose"


# Cellpose QC figure

def cellpose_qc_path(run_folder, image_name):
    """Path of an image's Cellpose QC figure: `qc/<image>_cellpose_qc.png` in the run folder."""
    return Path(run_folder) / QC_FOLDER_NAME / f"{image_name}{CELLPOSE_QC_SUFFIX}{QC_EXTENSION}"


def temporary_qc_path(path):
    """Name a QC figure has while it is written: `<image>_cellpose_qc.png.tmp`."""
    path = Path(path)
    return path.with_name(path.name + ".tmp")


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_qc_path(path)
    try:
        figure.savefig(temporary, format="png", dpi=FIGURE_DPI)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path
