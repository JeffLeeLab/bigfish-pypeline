"""
Label images of cells: preparing the segmentation channel, segmenting it with
Cellpose, and writing and reading label files.

`cellpose` and `torch` are imported only inside the functions that segment,
so that reading label files never loads them.
"""

import numbers
import os
import time
from pathlib import Path

import numpy as np
import tifffile
from scipy import ndimage

from bigfish_pypeline.background import METHODS as BACKGROUND_METHODS
from bigfish_pypeline.background import subtract_background

LABEL_SUFFIX = "_seglabels"
LABEL_EXTENSION = ".tif"

PROJECTIONS = ("max", "mean")

DEVICE_SETTINGS = ("auto", "cuda", "mps", "cpu")
DEVICE_NAMES = {"cuda": "the NVIDIA GPU (cuda)", "mps": "the Apple GPU (mps)", "cpu": "the CPU"}

CPU_WARNING = (
    "Cellpose runs on the CPU, so segmentation will be slow (minutes per image "
    "instead of seconds)."
)
NO_CELLS_WARNING = "Cellpose found no cells in this image; there are no cell-level results."

# Cellpose settings from the config that are passed on to `eval`
EVAL_SETTINGS = (
    "diameter", "flow_threshold", "cellprob_threshold", "min_size",
    "normalize", "batch_size", "niter",
)


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


# Device, model and segmentation with Cellpose

class CellposeSetupError(Exception):
    """The device or the Cellpose model cannot be used, with a plain one-line reason."""


class SegmentationError(Exception):
    """Cellpose could not segment an image, with a plain one-line reason."""


def _one_line(error):
    """The error's type and text on one line."""
    text = " ".join(str(error).split())
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def _device_available(name):
    """True when PyTorch can see the device "cuda" or "mps"; the CPU is always there."""
    if name == "cpu":
        return True
    import torch
    if name == "cuda":
        return torch.cuda.is_available()
    return torch.backends.mps.is_available()


def _test_calculation(name):
    """
    Multiply a 256 x 256 matrix of ones by itself on the device and check the
    result. Raises an error when the device does not work.
    """
    import torch
    device = torch.device(name)
    x = torch.ones((256, 256), device=device)
    y = x @ x
    if name == "cuda":
        torch.cuda.synchronize()
    elif name == "mps":
        torch.mps.synchronize()
    value = y[0, 0].item()
    if y.device.type != name or value != 256.0:
        raise RuntimeError(f"the result was {value} on {y.device.type} instead of 256 on {name}")


def choose_device(setting="auto"):
    """
    Choose and test the device Cellpose runs on, before the model is loaded.

    setting: "auto", "cuda" (NVIDIA GPU), "mps" (Apple GPU) or "cpu".
    "auto" tries the NVIDIA GPU, then the Apple GPU, then the CPU. A GPU that
    is found but fails a quick test calculation is passed over with a
    warning, and the next device is tried. A device named in the setting
    must be present and pass the test calculation.

    Returns (device, report, warnings): the device name ("cuda", "mps" or
    "cpu"), a sentence for the log naming the device used, and a list of
    warning sentences (a GPU passed over; segmentation will be slow on the
    CPU).
    Raises CellposeSetupError with a plain one-line message when the device
    named in the setting cannot be used.
    """
    if setting not in DEVICE_SETTINGS:
        raise CellposeSetupError(
            f"Unknown device '{setting}'. Use one of: {', '.join(DEVICE_SETTINGS)}."
        )

    warnings = []
    if setting == "auto":
        device = None
        for name in ("cuda", "mps"):
            if not _device_available(name):
                continue
            try:
                _test_calculation(name)
            except Exception as error:
                warnings.append(
                    f"{DEVICE_NAMES[name]} was found but failed a test calculation "
                    f"({_one_line(error)}); the next device is tried."
                )
                continue
            device = name
            break
        if device is None:
            device = "cpu"
            _check_named_device(device, setting)
    else:
        device = setting
        _check_named_device(device, setting)

    how = "chosen automatically" if setting == "auto" else "as set in the config"
    report = f"Cellpose runs on {DEVICE_NAMES[device]}, {how}."
    if device == "cpu":
        warnings.append(CPU_WARNING)
    return device, report, warnings


def _check_named_device(name, setting):
    """Raise CellposeSetupError when the device is missing or fails the test calculation."""
    other = "Use `device: auto` or `device: cpu` instead."
    if not _device_available(name):
        raise CellposeSetupError(
            f"`device: {setting}` is set in the config, but {DEVICE_NAMES[name]} is not "
            f"available on this computer. {other}"
        )
    try:
        _test_calculation(name)
    except Exception as error:
        if name == "cpu":
            other = "PyTorch may not be installed correctly in this environment."
        raise CellposeSetupError(
            f"{DEVICE_NAMES[name][0].upper()}{DEVICE_NAMES[name][1:]} failed a test "
            f"calculation ({_one_line(error)}). {other}"
        ) from error


def load_cellpose_model(model_name="cpsam_v2", device="cpu", threads=None):
    """
    Load a Cellpose model once, to be reused for every image.

    model_name: one of Cellpose's own models (e.g. "cpsam_v2"), a model added
        in the Cellpose window, or the full path to a model file. Cellpose
        downloads one of its own models the first time it is used.
    device: "cuda", "mps" or "cpu", as returned by choose_device.
    threads: on the CPU, the number of processor threads Cellpose may use;
        None leaves PyTorch's own choice.

    Returns the Cellpose model.
    Raises CellposeSetupError with a plain one-line message when the model
    name is unknown, the model cannot be downloaded, or it cannot be loaded.
    """
    from cellpose import models
    import torch

    model_name = str(model_name).strip()
    path = Path(model_name).expanduser()
    known = list(models.MODEL_NAMES) + list(models.get_user_models())
    if path.is_file():
        pretrained = str(path)
        downloading = False
    elif model_name in known:
        pretrained = model_name
        downloading = not (models.MODEL_DIR / model_name).is_file()
    else:
        raise CellposeSetupError(
            f"Unknown Cellpose model '{model_name}': it is neither a model file on this "
            f"computer nor one of Cellpose's models ({', '.join(known)})."
        )

    if device == "cpu" and threads is not None:
        torch.set_num_threads(int(threads))
    try:
        return models.CellposeModel(
            pretrained_model=pretrained, device=torch.device(device), use_bfloat16=False
        )
    except MemoryError:
        raise
    except Exception as error:
        if downloading:
            raise CellposeSetupError(
                f"The Cellpose model '{model_name}' could not be downloaded ({_one_line(error)}). "
                f"Check the internet connection and try again; the model is saved in "
                f"{models.MODEL_DIR} and is downloaded only once."
            ) from error
        raise CellposeSetupError(
            f"The Cellpose model '{model_name}' could not be loaded ({_one_line(error)}). "
            f"If the model file is damaged, delete it from {models.MODEL_DIR} so that "
            f"Cellpose downloads it again."
        ) from error


def cellpose_eval_settings(cellpose_settings):
    """
    The settings passed to segment_cells, taken from the config's
    `segmentation.cellpose` section (a CellposeSettings or a dict).
    """
    if not isinstance(cellpose_settings, dict):
        cellpose_settings = cellpose_settings.model_dump()
    return {name: cellpose_settings[name] for name in EVAL_SETTINGS}


def segment_cells(model, image, diameter=None, flow_threshold=0.4, cellprob_threshold=0,
                  min_size=15, normalize=True, batch_size=1, niter=None):
    """
    Segment one 2D image with a loaded Cellpose model.

    image: the 2D (y, x) image given to Cellpose, usually from pretreat_channel.
    The other settings are passed to Cellpose's `eval` unchanged
    (see the `segmentation.cellpose` section of the config).

    Returns a dict with:
    - "masks": the label image, 2D uint32 of the image's size, 0 for
      background and one whole number per cell,
    - "model_input": the image as given to Cellpose (32-bit decimal numbers),
    - "flows": Cellpose's flows; flows[0] is the flow picture shown in the QC
      figure,
    - "n_cells": the number of cells,
    - "seconds": the time Cellpose took,
    - "warning": NO_CELLS_WARNING when no cell was found, otherwise None.

    Raises SegmentationError with a plain one-line reason when Cellpose fails.
    """
    image = np.asarray(image)
    if image.ndim != 2:
        raise SegmentationError(
            f"The image given to Cellpose must be 2D (y, x); this one has shape {image.shape}."
        )
    model_input = np.ascontiguousarray(image, dtype=np.float32)

    started = time.perf_counter()
    try:
        masks, flows, _ = model.eval(
            model_input, channel_axis=None, z_axis=None, do_3D=False,
            diameter=diameter, flow_threshold=flow_threshold,
            cellprob_threshold=cellprob_threshold, min_size=min_size,
            normalize=normalize, batch_size=batch_size, niter=niter,
        )
    except MemoryError:
        raise
    except Exception as error:
        raise SegmentationError(f"Cellpose could not segment the image ({_one_line(error)})") from error
    finally:
        _release_gpu_memory(model)
    seconds = time.perf_counter() - started

    masks = np.asarray(masks)
    if masks.size != model_input.size:
        raise SegmentationError(
            f"Cellpose returned labels of shape {masks.shape} for an image of shape "
            f"{model_input.shape}."
        )
    masks = masks.reshape(model_input.shape).astype(np.uint32)
    n_cells = len(np.unique(masks[masks > 0]))
    return {
        "masks": masks,
        "model_input": model_input,
        "flows": flows,
        "n_cells": n_cells,
        "seconds": seconds,
        "warning": NO_CELLS_WARNING if n_cells == 0 else None,
    }


def _release_gpu_memory(model):
    """Hand the GPU memory PyTorch keeps in reserve back to the computer after an image."""
    device_type = getattr(getattr(model, "device", None), "type", None)
    if device_type not in ("cuda", "mps"):
        return
    import torch
    if device_type == "cuda":
        torch.cuda.empty_cache()
    else:
        torch.mps.empty_cache()


# Label files

class LabelFileError(Exception):
    """A label file is missing, unreadable or does not fit its image."""


def label_file_path(label_folder, image_name):
    """Path of the label file for an image: `<image>_seglabels.tif` in the label folder."""
    return Path(label_folder) / f"{image_name}{LABEL_SUFFIX}{LABEL_EXTENSION}"


def temporary_label_path(path):
    """Name a label file has while it is written: `<image>_seglabels.tif.tmp`."""
    path = Path(path)
    return path.with_name(path.name + ".tmp")


def write_label_file(masks, label_folder, image_name):
    """
    Write an image's labels as `<image>_seglabels.tif` in the label folder.

    masks: 2D label image, 0 for background and one whole number per cell.
    It is saved as uint32. The file is first written under a temporary name
    and then renamed, so a half-written file never has the label file's name.
    The folder is made when it does not exist.

    Returns the path of the label file.
    Raises LabelFileError when masks is not a usable label image.
    """
    path = label_file_path(label_folder, image_name)
    masks = np.asarray(masks)
    masks = check_labels(masks, masks.shape[-2:], name=path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_label_path(path)
    try:
        tifffile.imwrite(temporary, masks, photometric="minisblack", metadata={"axes": "YX"})
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


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
