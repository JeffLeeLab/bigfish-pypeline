"""Label images of cells: reading them from label files."""

from pathlib import Path

import numpy as np
import tifffile

LABEL_SUFFIX = "_seglabels"
LABEL_EXTENSION = ".tif"


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
