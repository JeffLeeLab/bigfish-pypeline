"""Read local TIFF images: list the files, read their header information and read single channels."""

import logging
import math
import re
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile

LAYOUTS = ("ZCYX", "CZYX", "ZYX", "CYX", "YX")
EXTENSIONS = (".tif", ".tiff")
LABEL_SUFFIX = "_seglabels"

# Axis letters that tifffile uses for several positions (Micro-Manager positions, mosaic tiles).
POSITION_AXES = ("R", "M")

# Length units found in ImageJ and OME metadata, as the number of nm in one unit.
NM_PER_UNIT = {
    "nm": 1.0,
    "nanometer": 1.0,
    "nanometre": 1.0,
    "um": 1e3,
    "µm": 1e3,
    "μm": 1e3,
    "\\u00b5m": 1e3,
    "micron": 1e3,
    "microns": 1e3,
    "micrometer": 1e3,
    "micrometre": 1e3,
    "mm": 1e6,
    "millimeter": 1e6,
    "millimetre": 1e6,
    "cm": 1e7,
    "centimeter": 1e7,
    "centimetre": 1e7,
    "m": 1e9,
    "meter": 1e9,
    "metre": 1e9,
}

# Voxel sizes closer than this fraction are treated as equal (rounding in the metadata).
VOXEL_SIZE_TOLERANCE = 0.001


class ImageReadError(Exception):
    """An image that cannot be used, with a plain one-line reason."""


@dataclass
class ImageInfo:
    """Information read from the file header, without loading the pixels.

    `shape` and `axes` are as stored in the file, with axes of length 1 left out.
    `layout` is the layout the metadata suggests, or None when the metadata does not say.
    Voxel sizes are in nm, or None when the metadata does not give them.
    """

    path: Path
    shape: tuple
    axes: str
    dtype: np.dtype
    layout: str | None
    n_timepoints: int
    n_positions: int
    voxel_size_z: float | None
    voxel_size_y: float | None
    voxel_size_x: float | None

    @property
    def nbytes(self):
        """Size of the whole image in memory, in bytes."""
        return math.prod(self.shape) * self.dtype.itemsize

    @property
    def xy_sizes_differ(self):
        """True when the metadata gives different pixel sizes in X and Y."""
        if self.voxel_size_y is None or self.voxel_size_x is None:
            return False
        return not _close(self.voxel_size_y, self.voxel_size_x)


# File list


def _nfc(text):
    """The same text in one Unicode form, so that accented names compare equal on every system."""
    return unicodedata.normalize("NFC", text)


def list_images(folder, filter_text="", extension=".tif"):
    """Image files at the top level of `folder` whose name contains `filter_text`, sorted by name.

    Label images (name ending in `_seglabels`), hidden files and subfolders are left out.
    The extension is matched without regard to upper or lower case, and `.tif` does not match `.tiff`.
    """
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")

    extension = extension.lower()
    if not extension.startswith("."):
        extension = "." + extension
    if extension not in EXTENSIONS:
        raise ValueError(f"Extension must be .tif or .tiff, not {extension}")

    filter_text = _nfc(filter_text or "")
    images = []
    for path in folder.iterdir():
        name = _nfc(path.name)
        if name.startswith("."):
            continue
        if path.suffix.lower() != extension:
            continue
        if path.stem.endswith(LABEL_SUFFIX):
            continue
        if filter_text not in name:
            continue
        if not path.is_file():
            continue
        images.append(path)
    return sorted(images, key=lambda p: _nfc(p.name))


# Output names


def output_name(path):
    """Name used for the image in the result tables and file names: the file name without its extension."""
    return Path(path).stem


def check_output_names(paths):
    """Stop when two images would give the same output name.

    Names that differ only in upper or lower case count as the same, because the
    result files would overwrite each other on macOS and Windows.
    """
    seen = {}
    for path in paths:
        name = output_name(path)
        seen.setdefault(_nfc(name).casefold(), []).append(Path(path).name)
    clashes = [names for names in seen.values() if len(names) > 1]
    if clashes:
        listed = "; ".join(", ".join(names) for names in clashes)
        raise ValueError(f"These images would give the same output name: {listed}. Rename them or change the filter.")


# Header information


def _open(path):
    """Open a TIFF file, turning any failure into an ImageReadError."""
    path = Path(path)
    if not path.is_file():
        raise ImageReadError(f"{path.name}: file not found")
    try:
        return tifffile.TiffFile(path)
    except Exception as error:
        raise ImageReadError(f"{path.name}: not a readable TIFF file ({_reason(error)})") from error


class _ErrorCollector(logging.Handler):
    """Keeps the problems tifffile reports at ERROR level: image data that may be wrong or incomplete."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextmanager
def _damaged_file_check(path):
    """Raise an ImageReadError when tifffile finds the file damaged or incomplete while it is read."""
    collector = _ErrorCollector()
    tifffile_log = logging.getLogger("tifffile")
    tifffile_log.addHandler(collector)
    try:
        yield
    except ImageReadError:
        if not collector.messages:
            raise
    finally:
        tifffile_log.removeHandler(collector)
    if collector.messages:
        # tifffile starts its messages with the object concerned, e.g. "<tifffile.TiffPages @8>".
        reason = re.sub(r"^<[^>]*>\s*", "", collector.messages[0])
        raise ImageReadError(f"{Path(path).name}: the file is damaged or incomplete ({reason})")


def _reason(error):
    """First line of an error message, or the error type when there is no message."""
    text = str(error).strip().splitlines()
    return text[0] if text else type(error).__name__


def _to_nm(value, unit):
    """A length in nm, or None when the unit is not a length unit."""
    if value is None or unit is None:
        return None
    factor = NM_PER_UNIT.get(str(unit).strip().lower())
    if factor is None or not value > 0:
        return None
    return round(float(value) * factor, 3)


def _voxel_sizes(tif, series):
    """Voxel sizes (z, y, x) in nm from ImageJ or OME metadata."""
    if series.kind not in ("imagej", "ome"):
        return None, None, None
    scales = series.coord_scales
    units = series.coord_units
    return tuple(_to_nm(scales.get(axis), units.get(axis)) for axis in "ZYX")


def _counts(tif, series):
    """Number of time points and positions in the file."""
    sizes = dict(zip(series.axes, series.shape))
    n_timepoints = sizes.get("T", 1)
    n_positions = math.prod(sizes.get(axis, 1) for axis in POSITION_AXES)
    if tif.is_ome:
        n_positions *= len(tif.series)
    return n_timepoints, n_positions


def _suggested_layout(series):
    """Layout given by the file's metadata, or None."""
    if series.kind not in ("imagej", "ome", "shaped"):
        return None
    axes = series.axes
    return axes if axes in LAYOUTS else None


def _first_series(path, tif):
    """The image stored in the file.

    When the file carries ImageJ or OME metadata that tifffile cannot match to the
    pixel data (for example a file cut short), the file is treated as damaged.
    """
    try:
        series = tif.series[0]
    except Exception as error:
        raise ImageReadError(f"{path.name}: the file header cannot be read ({_reason(error)})") from error
    for kind, has_metadata in (("imagej", tif.is_imagej), ("ome", tif.is_ome)):
        if has_metadata and series.kind != kind:
            name = "ImageJ" if kind == "imagej" else "OME"
            raise ImageReadError(
                f"{path.name}: the file is damaged or incomplete ({name} metadata does not match the pixel data)"
            )
    return series


def get_image_info(path):
    """Shape, data type, suggested layout, time points, positions and voxel sizes, read from the file header."""
    path = Path(path)
    with _damaged_file_check(path), _open(path) as tif:
        series = _first_series(path, tif)
        try:
            shape = tuple(series.shape)
            axes = series.axes
            dtype = np.dtype(series.dtype)
            n_timepoints, n_positions = _counts(tif, series)
            voxel_size_z, voxel_size_y, voxel_size_x = _voxel_sizes(tif, series)
            layout = _suggested_layout(series)
        except Exception as error:
            raise ImageReadError(f"{path.name}: the file header cannot be read ({_reason(error)})") from error
    return ImageInfo(
        path=path,
        shape=shape,
        axes=axes,
        dtype=dtype,
        layout=layout,
        n_timepoints=n_timepoints,
        n_positions=n_positions,
        voxel_size_z=voxel_size_z,
        voxel_size_y=voxel_size_y,
        voxel_size_x=voxel_size_x,
    )


# Reading


def _check_layout(layout):
    if layout not in LAYOUTS:
        raise ValueError(f"Layout must be one of {', '.join(LAYOUTS)}, not {layout}")


def _plane_sizes(path, tif, series, layout):
    """Size of each axis of the layout other than Y and X, in the order stored in the file.

    Raises ImageReadError when the file has several time points or positions,
    holds colour (RGB) pixels, or has a different number of axes from the layout.
    """
    n_timepoints, n_positions = _counts(tif, series)
    if n_timepoints > 1:
        raise ImageReadError(f"{path.name}: the file has {n_timepoints} time points; only one is accepted")
    if n_positions > 1:
        raise ImageReadError(f"{path.name}: the file has {n_positions} positions; only one is accepted")
    if series.keyframe.samplesperpixel > 1:
        raise ImageReadError(f"{path.name}: colour (RGB) images are not accepted; save the channels as separate planes")

    # Axes of length 1 (for example a single channel) are not counted, as in the file information.
    if len(series.shape) != len(layout):
        shape = " × ".join(str(n) for n in series.shape)
        raise ImageReadError(
            f"{path.name}: the file has {len(series.shape)} axes ({shape}) but the layout {layout} "
            f"needs {len(layout)}"
        )
    return dict(zip(layout[:-2], series.shape[:-2]))


def _channel_planes(sizes, channel):
    """Page numbers in the file holding one channel, in Z order."""
    if not sizes:
        return [0]
    numbers = np.arange(math.prod(sizes.values())).reshape(tuple(sizes.values()))
    if "C" in sizes:
        numbers = np.take(numbers, channel, axis=list(sizes).index("C"))
    return [int(n) for n in numbers.ravel()]


def _whole_series(path, tif, series):
    """All pixel data of a file that stores the whole image in one block (for example ImageJ files over 4 GB).

    The data are mapped from the file without loading them, so that a channel can be
    copied out on its own. When the file cannot be mapped, the whole image is read.
    """
    offset = series.dataoffset
    if offset is not None and path.stat().st_size < offset + series.nbytes:
        raise ImageReadError(f"{path.name}: the file is damaged or incomplete (pixel data cut short)")
    try:
        stack = tifffile.memmap(path, series=0, mode="r")
    except Exception:
        try:
            stack = tif.asarray(series=0)
        except Exception as error:
            raise ImageReadError(f"{path.name}: the pixel data cannot be read ({_reason(error)})") from error
    return stack.reshape(series.shape)


def read_channels(path, layout, channels):
    """Read several channels of one image, reading only their planes from the file.

    Channel numbers count from 0 and refer to the position in the file.
    Returns a dict {channel: array}, each array `ZYX` (or `YX` for 2D layouts),
    in the data type stored in the file.
    """
    path = Path(path)
    _check_layout(layout)
    channels = [int(c) for c in channels]
    arrays = {}
    with _damaged_file_check(path), _open(path) as tif:
        series = _first_series(path, tif)

        dtype = np.dtype(series.dtype)
        if dtype.kind not in "uif":
            raise ImageReadError(f"{path.name}: pixel type {dtype} is not accepted")

        sizes = _plane_sizes(path, tif, series, layout)
        n_channels = sizes.get("C", 1)
        available = "1 channel (channel 0)" if n_channels == 1 else f"{n_channels} channels (0–{n_channels - 1})"
        for channel in channels:
            if not 0 <= channel < n_channels:
                raise ImageReadError(f"{path.name}: channel {channel} does not exist; the image has {available}")

        height, width = series.shape[-2:]
        # Usually each plane is one page of the file; some files hold the whole image in one page.
        one_block = series.is_truncated or len(series.pages) < math.prod(sizes.values())
        stack = _whole_series(path, tif, series) if one_block else None
        for channel in channels:
            if one_block:
                index = [slice(None)] * len(layout)
                if "C" in layout:
                    index[layout.index("C")] = channel
                # Copy the channel out of the file, in the computer's own byte order.
                data = np.array(stack[tuple(index)], dtype=dtype.newbyteorder("="))
            else:
                planes = _channel_planes(sizes, channel)
                try:
                    data = tif.asarray(key=planes, series=0)
                except Exception as error:
                    raise ImageReadError(f"{path.name}: the pixel data cannot be read ({_reason(error)})") from error
                data = data.reshape(len(planes), height, width)
                if "Z" not in layout:
                    data = data[0]
            if dtype.kind == "f" and not np.isfinite(data).all():
                raise ImageReadError(f"{path.name}: channel {channel} contains NaN or infinite values")
            arrays[channel] = data
        # Release the file mapping so the file is not held open (needed on Windows).
        del stack
    return arrays


def read_channel(path, layout, channel):
    """Read one channel of an image as a `ZYX` array (or `YX` for 2D layouts)."""
    return read_channels(path, layout, [channel])[int(channel)]


# Metadata check


def _close(a, b):
    return math.isclose(a, b, rel_tol=VOXEL_SIZE_TOLERANCE)


def check_voxel_sizes(info, voxel_size_z, voxel_size_yx):
    """Warning text when the file's voxel sizes disagree with the config, otherwise None.

    `voxel_size_z` and `voxel_size_yx` are the config values in nm (`voxel_size_z` is
    None for 2D images). Sizes missing from the file are not compared.
    """
    differences = []
    if info.voxel_size_z is not None and voxel_size_z is not None and not _close(info.voxel_size_z, voxel_size_z):
        differences.append(f"Z {info.voxel_size_z:g} nm in the file, {voxel_size_z:g} nm in the config")
    for axis, size in (("Y", info.voxel_size_y), ("X", info.voxel_size_x)):
        if size is not None and voxel_size_yx is not None and not _close(size, voxel_size_yx):
            differences.append(f"{axis} {size:g} nm in the file, {voxel_size_yx:g} nm in the config")
    if not differences:
        return None
    return f"{info.path.name}: voxel sizes differ ({'; '.join(differences)}); the config values are used"
