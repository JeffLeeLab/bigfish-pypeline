"""Label images of cells: preparing the segmentation channel and reading label files."""

import numbers
from pathlib import Path

import numpy as np
import tifffile
from scipy import ndimage

from bigfish_pypeline.background import METHODS as BACKGROUND_METHODS
from bigfish_pypeline.background import subtract_background

LABEL_SUFFIX = "_seglabels"
LABEL_EXTENSION = ".tif"

PROJECTIONS = ("max", "mean")


# Pre-treatment of the segmentation channel

def pretreat_channel(image, projection="max", clip=False, clip_value=100,
                     background=True, bg_method="rolling_ball", bg_radius=200,
                     median_px=None, gaussian_sigma_px=None):
    """
    Turn the segmentation channel into the 2D image given to Cellpose.

    image: one channel, (z, y, x) or (y, x). A 2D image is used as it is.

    The steps run in this order:
    1. Z projection: "max" (brightest value along Z, same number type as the
       image) or "mean" (average along Z, a decimal (float64) image).
    2. Clip (when clip is True): values above clip_value are set to
       clip_value, and values below 0 are set to 0, as in the v1
       tissue-culture script. The number type is kept, so on a whole-number
       image a clip value of 100.5 acts as 100.
    3. Background subtraction (when background is True): subtract_background
       with bg_method ("rolling_ball" or "tophat") and bg_radius in pixels.
       Rolling ball keeps a uint8 or uint16 image in its type; any other
       type, such as a mean projection, gives float64 with values below the
       background kept negative. Top-hat keeps the number type.
    4. Median filter (when median_px is set): window of median_px x median_px
       pixels. The number type is kept.
    5. Gaussian filter (when gaussian_sigma_px is set): sigma in pixels. The
       result is a decimal image (float64, or the image's own decimal type),
       so that the smoothing is not rounded to whole numbers.

    With every step off, the projection is returned unchanged.
    """
    _check_pretreatment(projection, bg_method, median_px, gaussian_sigma_px)
    image = np.asarray(image)
    if image.ndim == 3:
        image = image.max(axis=0) if projection == "max" else image.mean(axis=0)
    elif image.ndim != 2:
        raise ValueError(
            f"The segmentation channel must be a 2D (y, x) image or a 3D (z, y, x) "
            f"stack; this one has {image.ndim} dimensions."
        )

    if clip:
        image = np.clip(image, 0, clip_value).astype(image.dtype, copy=False)
    if background:
        image = subtract_background(image, bg_radius, method=bg_method)
    if median_px is not None:
        image = ndimage.median_filter(image, size=int(median_px))
    if gaussian_sigma_px is not None:
        if not np.issubdtype(image.dtype, np.floating):
            image = image.astype(np.float64)
        image = ndimage.gaussian_filter(image, sigma=gaussian_sigma_px)
    return image


def describe_pretreatment(projection="max", clip=False, clip_value=100,
                          background=True, bg_method="rolling_ball", bg_radius=200,
                          median_px=None, gaussian_sigma_px=None):
    """
    One line naming the pre-treatment steps that are on, for figure titles.

    Takes the same settings as pretreat_channel, for example
    "max projection | clip 100 | rolling ball 200 px | median 5 px | Gaussian 1.5 px".
    """
    _check_pretreatment(projection, bg_method, median_px, gaussian_sigma_px)
    parts = [f"{projection} projection"]
    if clip:
        parts.append(f"clip {clip_value:g}")
    if background:
        method = {"rolling_ball": "rolling ball", "tophat": "top-hat"}[bg_method]
        parts.append(f"{method} {bg_radius:g} px")
    else:
        parts.append("no background subtraction")
    if median_px is not None:
        parts.append(f"median {int(median_px)} px")
    if gaussian_sigma_px is not None:
        parts.append(f"Gaussian {gaussian_sigma_px:g} px")
    return " | ".join(parts)


def _check_pretreatment(projection, bg_method, median_px, gaussian_sigma_px):
    """Raise ValueError with a plain message for a setting that cannot be used."""
    if projection not in PROJECTIONS:
        raise ValueError(
            f"Unknown Z projection '{projection}'. Use one of: {', '.join(PROJECTIONS)}."
        )
    if bg_method not in BACKGROUND_METHODS:
        raise ValueError(
            f"Unknown background subtraction method '{bg_method}'. "
            f"Use one of: {', '.join(BACKGROUND_METHODS)}."
        )
    if median_px is not None and not (
        isinstance(median_px, numbers.Integral) and not isinstance(median_px, bool)
        and median_px > 0
    ):
        raise ValueError(
            f"The median filter size must be a whole number of pixels above 0; got {median_px}."
        )
    if gaussian_sigma_px is not None and not (
        isinstance(gaussian_sigma_px, numbers.Real) and not isinstance(gaussian_sigma_px, bool)
        and gaussian_sigma_px > 0
    ):
        raise ValueError(
            f"The Gaussian filter sigma must be a number of pixels above 0; got {gaussian_sigma_px}."
        )


class LabelFileError(Exception):
    """A label file is missing, unreadable or does not fit its image."""


def label_file_path(label_folder, image_name):
    """Path of the label file for an image: `<image>_seglabels.tif` in the label folder."""
    return Path(label_folder) / f"{image_name}{LABEL_SUFFIX}{LABEL_EXTENSION}"


def read_label_file(label_folder, image_name, image_shape_yx):
    """
    Read an image's labels from `<image>_seglabels.tif` in the label folder.

    image_name: the image's output name (its file name without extension).
    image_shape_yx: (Y, X) size of the image the labels belong to.

    Returns the labels as `masks`, a 2D uint32 array with 0 for background
    and one whole number per cell.

    Raises LabelFileError with a one-line reason when the file is missing,
    unreadable, not 2D, of a different size from the image, or holds values
    that are not whole numbers of 0 or more.
    """
    path = label_file_path(label_folder, image_name)
    if not path.is_file():
        raise LabelFileError(f"Label file not found: {path}")
    try:
        labels = tifffile.imread(path)
    except Exception as error:
        detail = " ".join(str(error).split())
        raise LabelFileError(f"Label file could not be read: {path} ({detail})") from error
    return check_labels(labels, image_shape_yx, name=path.name)


def check_labels(labels, image_shape_yx, name="label image"):
    """
    Check a label image and return it as `masks` (2D, uint32).

    Whole numbers stored as floats are accepted and converted.
    Raises LabelFileError with a one-line reason if the labels cannot be used.
    """
    labels = np.asarray(labels)
    image_shape_yx = tuple(int(n) for n in image_shape_yx)

    if labels.ndim != 2:
        raise LabelFileError(
            f"{name}: labels must be a 2D image; this one has shape {labels.shape}"
        )
    if labels.shape != image_shape_yx:
        raise LabelFileError(
            f"{name}: labels are {labels.shape[0]} x {labels.shape[1]} px, "
            f"but the image is {image_shape_yx[0]} x {image_shape_yx[1]} px"
        )
    if labels.dtype == bool:
        labels = labels.astype(np.uint8)
    if not (np.issubdtype(labels.dtype, np.integer) or np.issubdtype(labels.dtype, np.floating)):
        raise LabelFileError(f"{name}: labels must be numbers; found type {labels.dtype}")

    if np.issubdtype(labels.dtype, np.floating):
        if not np.isfinite(labels).all():
            raise LabelFileError(f"{name}: labels contain NaN or infinite values")
        if not (labels == np.round(labels)).all():
            raise LabelFileError(f"{name}: labels contain numbers that are not whole numbers")
    if labels.size and labels.min() < 0:
        raise LabelFileError(f"{name}: labels contain negative numbers")
    if labels.size and labels.max() > np.iinfo(np.uint32).max:
        raise LabelFileError(f"{name}: labels contain numbers too large for a label image")

    return labels.astype(np.uint32)
