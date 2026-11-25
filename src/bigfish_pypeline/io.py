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

# Pixel types that can be used: 8-bit and 16-bit unsigned. A 12-bit image is read as 16-bit.
ACCEPTED_DTYPES = (np.dtype(np.uint8), np.dtype(np.uint16))
CONVERT_HELP = (
    "Convert the image to 16-bit, for example in Fiji with Image › Type › 16-bit "
    "(https://imagej.net/ij/docs/menus/image.html#type), then run it again. "
    'In Fiji, first untick "Scale when converting" under Edit › Options › Conversions, '
    "so that the pixel values are kept."
)


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
    """Layout given by the file's metadata, or None.

    Only ImageJ, OME and tifffile's own metadata record the axes. For a plain TIFF,
    or metadata without axes, tifffile guesses letters such as I or Q, which are
    not layouts.
    """
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


def _pixel_type_text(dtype, omero_type=None):
    """The pixel type in words, e.g. `32-bit with decimal values (float32)`."""
    if dtype is None:
        return f"'{omero_type}'"
    dtype = np.dtype(dtype)
    bits = dtype.itemsize * 8
    if dtype.kind == "f":
        return f"{bits}-bit with decimal values ({dtype.name})"
    if dtype.kind == "i":
        return f"{bits}-bit signed ({dtype.name})"
    if dtype.kind == "u":
        return f"{bits}-bit ({dtype.name})"
    if dtype.kind == "b":
        return "1-bit (black and white)"
    return dtype.name


def pixel_type_problem(info):
    """The reason an image's pixel type cannot be used, or None when it can.

    `info` is the information of a TIFF file (ImageInfo) or of an OMERO image (OmeroImageInfo).
    """
    if isinstance(info, OmeroImageInfo):
        label, dtype, omero_type = f"OMERO image {info.image_id}", info.dtype, info.pixel_type
    else:
        label, dtype, omero_type = Path(info.path).name, info.dtype, None
    return _pixel_type_message(label, dtype, omero_type)


def _pixel_type_message(label, dtype, omero_type=None):
    if dtype is not None and np.dtype(dtype).newbyteorder("=") in ACCEPTED_DTYPES:
        return None
    return (
        f"{label}: the pixel type is {_pixel_type_text(dtype, omero_type)}, which cannot be used; "
        f"only 8-bit, 12-bit and 16-bit images are accepted. {CONVERT_HELP}"
    )


def _check_pixel_type(label, dtype, omero_type=None):
    message = _pixel_type_message(label, dtype, omero_type)
    if message is not None:
        raise ImageReadError(message)


def _plane_sizes(path, tif, series, layout):
    """Size of each axis of the layout other than Y and X, in the order stored in the file.

    Raises ImageReadError when the file has several time points or positions,
    holds colour (RGB) pixels, or has a different number of axes from the layout,
    or when its metadata gives its axes in another order than the layout.
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
    # A file whose metadata does not give its axes is read with the layout as it is.
    axes = _suggested_layout(series)
    if axes is not None and axes != layout:
        raise ImageReadError(
            f"{path.name}: the file's own information says its axes are stored in the order {axes}, "
            f"which does not match the layout {layout} of this run (`image.axes` in the settings). "
            f"Save the image with its axes in the order {layout}, or run it with the layout {axes}."
        )
    return dict(zip(layout[:-2], series.shape[:-2]))


def _check_image(path, tif, series, layout, channels):
    """Check the pixel type, the layout and the channels from the file header; returns the plane sizes."""
    _check_pixel_type(path.name, series.dtype)
    sizes = _plane_sizes(path, tif, series, layout)
    n_channels = sizes.get("C", 1)
    available = "1 channel (channel 0)" if n_channels == 1 else f"{n_channels} channels (0–{n_channels - 1})"
    for channel in channels:
        if not 0 <= channel < n_channels:
            raise ImageReadError(f"{path.name}: channel {channel} does not exist; the image has {available}")
    return sizes


def check_image(path, layout, channels=()):
    """Check that an image can be read with `layout` and holds `channels`, without reading its pixels.

    Raises ImageReadError when the pixel type cannot be used, the file does not fit
    the layout, or a channel is missing.
    """
    path = Path(path)
    _check_layout(layout)
    channels = [int(c) for c in channels]
    with _damaged_file_check(path), _open(path) as tif:
        _check_image(path, tif, _first_series(path, tif), layout, channels)


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
        sizes = _check_image(path, tif, series, layout, channels)
        dtype = np.dtype(series.dtype)

        height, width = series.shape[-2:]
        # Usually each plane is one page of the file; some files hold the whole image in one page.
        one_block = series.is_truncated or len(series.pages) < math.prod(sizes.values())
        stack = _whole_series(path, tif, series) if one_block and channels else None
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


# OMERO
#
# The `omero` package is imported only inside the functions that talk to the server,
# so that local runs work without it.

logger = logging.getLogger(__name__)


def silence_omero_logging():
    """Stop every message omero-py logs (loggers named `omero` and `omero.*`) from going anywhere.

    omero-py's messages, warnings and tracebacks can hold the session key, even before
    this package knows the key. A lost connection is reported by this package itself in
    plain words, so nothing of omero-py's own is needed. Other loggers are not changed.
    """
    omero_logger = logging.getLogger("omero")
    omero_logger.setLevel(logging.CRITICAL + 1)
    omero_logger.propagate = False
    if not any(isinstance(handler, logging.NullHandler) for handler in omero_logger.handlers):
        omero_logger.addHandler(logging.NullHandler())


silence_omero_logging()


class _PlainWarnings(logging.Handler):
    """Shows a warning or error on the screen only when Python would show it anyway.

    Python prints a warning that no handler takes as its bare text (`logging.lastResort`).
    Once the root logger has a handler, `logging.basicConfig()` does nothing. This handler
    gives the root logger a handler while showing exactly what Python would have shown
    without one.
    """

    def __init__(self):
        super().__init__(logging.WARNING)

    def emit(self, record):
        current = logging.getLogger(record.name)
        while current is not None:
            if any(handler is not self for handler in current.handlers):
                return
            if not current.propagate:
                break
            current = current.parent
        if logging.lastResort is not None:
            logging.lastResort.handle(record)


def start_plain_logging():
    """Stop omero-py from setting up logging for the whole program.

    Each time omero-py makes a connection it calls `logging.basicConfig()`, after
    which the warnings of every other package (Cellpose, for example) are printed as
    `WARNING:name:...`. When the root logger has no handler, this gives it one that
    shows only what Python shows without one, so `basicConfig()` does nothing.

    Returns the handler added, or None when the root logger had a handler already.
    """
    silence_omero_logging()
    root = logging.getLogger()
    if root.handlers:
        return None
    handler = _PlainWarnings()
    root.addHandler(handler)
    return handler


def stop_plain_logging(handler):
    """Take away a handler added by `start_plain_logging` (None: nothing to do)."""
    if handler is not None:
        logging.getLogger().removeHandler(handler)


@contextmanager
def plain_logging():
    """`start_plain_logging` for the time of a `with` block; the root logger is left as it was."""
    handler = start_plain_logging()
    try:
        yield
    finally:
        stop_plain_logging(handler)


# Characters that Windows does not allow in file names.
WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# OMERO session keys look like 1b2c3d4e-0000-1111-2222-333344445555.
SESSION_KEY_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# OMERO length units (as written in the unit's name), as the number of nm in one unit.
OMERO_NM_PER_UNIT = {
    "NANOMETER": 1.0,
    "NANOMETRE": 1.0,
    "MICROMETER": 1000.0,
    "MICROMETRE": 1000.0,
    "MILLIMETER": 1_000_000.0,
    "MILLIMETRE": 1_000_000.0,
}

# OMERO pixel types and the matching numpy data types.
OMERO_PIXEL_TYPES = {
    "int8": "int8",
    "uint8": "uint8",
    "int16": "int16",
    "uint16": "uint16",
    "int32": "int32",
    "uint32": "uint32",
    "float": "float32",
    "double": "float64",
}


class OmeroSessionEnded(Exception):
    """The OMERO session has ended (for example it timed out or was closed), so no more images can be read."""


class OmeroConnectionLost(ImageReadError):
    """The connection to OMERO dropped while an image was read.

    `reason` holds the short reason from omero-py, with any session key removed.
    """


def _connection_lost(image_id, error, key):
    """OmeroConnectionLost for an omero-py error met while image `image_id` was read."""
    reason = _omero_reason(error, key)
    lost = OmeroConnectionLost(f"OMERO image {image_id}: lost the connection to OMERO ({reason})")
    lost.reason = reason
    return lost


def _lost_reason(error):
    """The short reason held by an OmeroConnectionLost, or its whole message."""
    return getattr(error, "reason", None) or str(error)


@dataclass
class OmeroImageInfo:
    """Information about an OMERO image, read from the server without loading the pixels.

    Sizes count the planes, channels and time points as stored on the server.
    `dtype` is None when the pixel type has no matching numpy type (e.g. `bit`).
    Voxel sizes are in nm, or None when the server does not give them.
    """

    image_id: int
    name: str
    size_z: int
    size_c: int
    size_t: int
    size_y: int
    size_x: int
    pixel_type: str | None
    dtype: np.dtype | None
    voxel_size_z: float | None
    voxel_size_y: float | None
    voxel_size_x: float | None
    channel_names: list

    @property
    def output_name(self):
        return omero_output_name(self.image_id, self.name)

    @property
    def path(self):
        """The output name in place of a file path, so that the image is named the same way in messages."""
        return Path(self.output_name)

    @property
    def axes(self):
        """Axes of the image with axes of length 1 left out, in the order Z, C, Y, X."""
        return _omero_axes(self.size_z, self.size_c)

    @property
    def shape(self):
        sizes = {"Z": self.size_z, "C": self.size_c, "Y": self.size_y, "X": self.size_x}
        return tuple(sizes[axis] for axis in self.axes)

    @property
    def layout(self):
        """Layout that fits the image. OMERO does not store an order, so `ZCYX` and `CZYX` both fit when there are both."""
        return self.axes if self.axes in LAYOUTS else None

    @property
    def n_timepoints(self):
        return self.size_t

    @property
    def n_positions(self):
        return 1

    @property
    def nbytes(self):
        """Size of one time point of the image in memory, in bytes (None when the pixel type is not known)."""
        if self.dtype is None:
            return None
        return math.prod(self.shape) * self.dtype.itemsize

    @property
    def xy_sizes_differ(self):
        """True when the server gives different pixel sizes in X and Y."""
        if self.voxel_size_y is None or self.voxel_size_x is None:
            return False
        return not _close(self.voxel_size_y, self.voxel_size_x)


def _omero_axes(size_z, size_c):
    axes = ""
    if size_z > 1:
        axes += "Z"
    if size_c > 1:
        axes += "C"
    return axes + "YX"


def _omero_errors():
    """Errors raised by omero-py when the connection or the session is lost."""
    import Glacier2
    import Ice
    import omero
    import omero.gateway  # noqa: F401 (loads omero.SessionException)

    return (Ice.LocalException, omero.SessionException, omero.ClientError, Glacier2.SessionNotExistException)


def _hide_key(text, key=None):
    """`text` with any session key replaced by `[hidden]`."""
    text = SESSION_KEY_PATTERN.sub("[hidden]", str(text))
    if key:
        text = text.replace(str(key), "[hidden]")
    return text


def _omero_reason(error, key=None):
    """Short reason for an omero-py error, with any session key removed."""
    return _hide_key(f"{type(error).__name__}: {_reason(error)}", key)


def _known_key(conn):
    """The session key of `conn` if it can be found without contacting the server, otherwise None."""
    try:
        return conn.c.getSessionId()
    except Exception:
        return None


def _id_number(value, kind="image"):
    """An OMERO ID as a whole number. Accepts 123, "123" or "Image:123"."""
    text = str(value).strip()
    prefix = kind.capitalize() + ":"
    if text.startswith(prefix):
        text = text[len(prefix):].strip()
    if not text.isdigit():
        raise ValueError(f"OMERO {kind} IDs are whole numbers, not '{value}'")
    return int(text)


def omero_output_name(image_id, image_name):
    """
    Output name of an OMERO image: `<image ID>_<image name>`.

    A `.tif` or `.tiff` at the end of the image name is left out, as for
    local files, and characters Windows does not allow are replaced by `_`.
    """
    image_name = str(image_name)
    for extension in EXTENSIONS:
        if image_name.lower().endswith(extension) and len(image_name) > len(extension):
            image_name = image_name[: -len(extension)]
            break
    name = _nfc(f"{int(image_id)}_{image_name}")
    return WINDOWS_FORBIDDEN.sub("_", name)


# Listing


def list_omero_images(conn, dataset_id=None, image_ids=None):
    """OMERO images as a list of (image ID, image name) pairs.

    Give either a dataset ID or a list of image IDs. A dataset's images are sorted
    by name, then ID; a list of image IDs keeps its order, with repeats left out.
    """
    if (dataset_id is None) == (image_ids is None):
        raise ValueError("Give either a dataset ID or a list of image IDs")
    key = _known_key(conn)
    try:
        if dataset_id is not None:
            return _dataset_images(conn, _id_number(dataset_id, "dataset"))
        return _listed_images(conn, image_ids)
    except _omero_errors() as error:
        raise ConnectionError(f"Lost the connection to OMERO ({_omero_reason(error, key)})") from None


def _dataset_images(conn, dataset_id):
    dataset = conn.getObject("Dataset", dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset {dataset_id} was not found on OMERO, or you cannot see it from your current group")
    images = [(int(image.getId()), image.getName()) for image in dataset.listChildren()]
    return sorted(images, key=lambda pair: (pair[1], pair[0]))


def _listed_images(conn, image_ids):
    ids = []
    for value in image_ids:
        image_id = _id_number(value)
        if image_id not in ids:
            ids.append(image_id)
    images = []
    missing = []
    for image_id in ids:
        image = conn.getObject("Image", image_id)
        if image is None:
            missing.append(str(image_id))
        else:
            images.append((image_id, image.getName()))
    if missing:
        raise ValueError(
            f"These image IDs were not found on OMERO, or you cannot see them from your current group: "
            f"{', '.join(missing)}"
        )
    return images


# Image information


def _length_to_nm(length):
    """An OMERO length (value and unit) in nm, or None when it is missing or the unit is not known."""
    if length is None:
        return None
    value = float(length.getValue())
    unit = str(length.getUnit()).upper()
    if not value > 0:
        return None
    for name, factor in OMERO_NM_PER_UNIT.items():
        if name in unit:
            return round(value * factor, 3)
    return None


def _channel_name(channel, index):
    """Channel name from the server, or `Channel <number>` when it has none."""
    getters = (
        lambda: channel.getName(),
        lambda: channel.getLabel(),
        lambda: channel.getLogicalChannel().getName(),
    )
    for getter in getters:
        try:
            value = getter()
        except Exception:
            continue
        if value:
            return str(value)
    return f"Channel {index}"


def _get_image(conn, image_id):
    """The OMERO image object, or ImageReadError when it is not found."""
    image = conn.getObject("Image", image_id)
    if image is None:
        raise ImageReadError(
            f"OMERO image {image_id}: not found, or you cannot see it from your current group"
        )
    return image


def _image_info(conn, image_id):
    image = _get_image(conn, image_id)
    pixels = image.getPrimaryPixels()
    pixel_type = image.getPixelsType()
    pixel_type = str(pixel_type) if pixel_type else None
    dtype = OMERO_PIXEL_TYPES.get(str(pixel_type).lower())
    channels = image.getChannels(noRE=True) or []
    return OmeroImageInfo(
        image_id=image_id,
        name=image.getName(),
        size_z=int(image.getSizeZ()),
        size_c=int(image.getSizeC()),
        size_t=int(image.getSizeT()),
        size_y=int(image.getSizeY()),
        size_x=int(image.getSizeX()),
        pixel_type=pixel_type,
        dtype=np.dtype(dtype) if dtype else None,
        voxel_size_z=_length_to_nm(pixels.getPhysicalSizeZ()),
        voxel_size_y=_length_to_nm(pixels.getPhysicalSizeY()),
        voxel_size_x=_length_to_nm(pixels.getPhysicalSizeX()),
        channel_names=[_channel_name(channel, index) for index, channel in enumerate(channels)],
    )


def get_omero_image_info(conn, image_id):
    """Sizes, pixel type, voxel sizes (nm) and channel names of an OMERO image, without loading the pixels."""
    image_id = _id_number(image_id)
    key = _known_key(conn)
    try:
        return _image_info(conn, image_id)
    except _omero_errors() as error:
        raise _connection_lost(image_id, error, key) from None


# Reading


def _read_omero_channels(conn, image_id, layout, channels):
    """Read channels of an OMERO image. Errors from omero-py are passed on unchanged."""
    from bigfish_pypeline.omero_tools import get_omero_image

    info = _image_info(conn, image_id)
    label = f"OMERO image {image_id}"
    if info.size_t > 1:
        raise ImageReadError(f"{label}: the image has {info.size_t} time points; only one is accepted")
    _check_pixel_type(label, info.dtype, info.pixel_type)

    # Axes of length 1 are not counted. OMERO stores no order, so ZCYX and CZYX are the same here.
    if sorted(layout) != sorted(info.axes):
        shape = " × ".join(str(n) for n in info.shape)
        planes = "1 plane" if info.size_z == 1 else f"{info.size_z} planes"
        n_channels = "1 channel" if info.size_c == 1 else f"{info.size_c} channels"
        raise ImageReadError(
            f"{label}: the image has {planes} and {n_channels} ({shape}), which does not fit the layout {layout}"
        )

    available = "1 channel (channel 0)" if info.size_c == 1 else f"{info.size_c} channels (0–{info.size_c - 1})"
    for channel in channels:
        if not 0 <= channel < info.size_c:
            raise ImageReadError(f"{label}: channel {channel} does not exist; the image has {available}")

    arrays = {}
    for channel in channels:
        stack, _ = get_omero_image(conn, image_id, channels=[channel], order="ZCYX")
        data = stack[:, 0]
        if "Z" not in layout:
            data = data[0]
        arrays[channel] = data
    return arrays


def read_omero_channels(conn, image_id, layout, channels):
    """Read several channels of an OMERO image.

    Channel numbers count from 0. Returns a dict {channel: array}, each array `ZYX`
    (or `YX` for 2D layouts), in the pixel type stored on the server.
    """
    _check_layout(layout)
    image_id = _id_number(image_id)
    channels = [int(c) for c in channels]
    key = _known_key(conn)
    try:
        return _read_omero_channels(conn, image_id, layout, channels)
    except _omero_errors() as error:
        raise _connection_lost(image_id, error, key) from None


def read_omero_channel(conn, image_id, layout, channel):
    """Read one channel of an OMERO image as a `ZYX` array (or `YX` for 2D layouts)."""
    return read_omero_channels(conn, image_id, layout, [channel])[int(channel)]


class OmeroImageReader:
    """Reads one OMERO image, rejoining the session once if the connection drops.

    Every read made through one reader shares a single second try: once the session
    has been rejoined for this image, a further drop makes the image fail.

    conn: the connection to start with. After each read, `conn` is the connection to
        go on using: a new one once the session has been rejoined, or None when
        rejoining failed. The old connection has been let go in both cases.
    notes: a list to which a plain sentence is added when the session is rejoined.
        Without a list, the sentence goes to this module's logger.

    Reads raise ImageReadError when the image cannot be read, and OmeroSessionEnded
    when the session has ended and cannot be rejoined.
    """

    def __init__(self, conn, image_id, host, port, key, notes=None):
        self.conn = conn
        self.image_id = _id_number(image_id)
        self.host = host
        self.port = port
        self.key = key
        self.notes = notes
        self.rejoined = False
        self.label = f"OMERO image {self.image_id}"

    def info(self):
        """The image information, as from `get_omero_image_info`."""
        return self._read(lambda conn: get_omero_image_info(conn, self.image_id))

    def channels(self, layout, channels):
        """Channels of the image, as from `read_omero_channels`."""
        return self._read(lambda conn: read_omero_channels(conn, self.image_id, layout, channels))

    def _read(self, read):
        if self.conn is None:
            raise ImageReadError(f"{self.label}: no connection to OMERO (rejoining the session failed)")
        try:
            return read(self.conn)
        except OmeroConnectionLost as error:
            reason = _hide_key(_lost_reason(error), self.key)
            if self.rejoined:
                raise ImageReadError(f"{self.label}: lost the connection to OMERO twice ({reason})") from None
        self._rejoin(reason)
        try:
            return read(self.conn)
        except OmeroConnectionLost as error:
            raise ImageReadError(
                f"{self.label}: lost the connection to OMERO twice ({_hide_key(_lost_reason(error), self.key)})"
            ) from None

    def _rejoin(self, reason):
        note = f"{self.label}: lost the connection to OMERO ({reason}); rejoining the session and trying again"
        if self.notes is None:
            logger.warning(note)
        else:
            self.notes.append(note)
        self.rejoined = True
        detach_session(self.conn)
        self.conn = None
        try:
            self.conn = join_session(self.host, self.port, self.key)
        except ConnectionError as error:
            raise ImageReadError(
                f"{self.label}: lost the connection to OMERO and could not reconnect ({_hide_key(error, self.key)})"
            ) from None


def read_omero_channels_with_retry(conn, image_id, layout, channels, host, port, key, notes=None):
    """Read channels of an OMERO image, rejoining the session once if the connection drops.

    Returns (arrays, conn): `arrays` as from `read_omero_channels`, and the connection to
    use from now on, which is a new one when the session was rejoined.
    Raises ImageReadError when the image cannot be read, and OmeroSessionEnded when the
    session has ended and cannot be rejoined. See OmeroImageReader for `notes`.
    """
    _check_layout(layout)
    reader = OmeroImageReader(conn, image_id, host, port, key, notes)
    return reader.channels(layout, [int(c) for c in channels]), reader.conn


# Session sharing


def session_key(conn):
    """The session key of a logged-in connection, for passing to worker processes in memory.

    Never write it to a file, a log or the screen.
    """
    try:
        return conn.c.getSessionId()
    except Exception:
        raise ConnectionError("Not logged in to OMERO") from None


def join_session(host, port, key):
    """Join an OMERO session that another process has logged in to, and return the connection.

    The connection has no keep-alive and is not closed on exit: the process that logged
    in keeps the session alive and closes it. Finish with `detach_session(conn)`.
    Raises OmeroSessionEnded when the server refuses to rejoin the session, and
    ConnectionError when the server cannot be reached or does not answer in time.
    """
    import Ice
    from omero.gateway import BlitzGateway

    conn = BlitzGateway(host=host, port=int(port), secure=True)
    join_errors = _keep_join_errors(conn)
    try:
        joined = conn.connect(sUuid=key)
    except Exception as error:
        detach_session(conn)
        raise ConnectionError(
            f"cannot reach the OMERO server at {host}:{port} ({_omero_reason(error, key)})"
        ) from None
    if not joined:
        detach_session(conn)
        # BlitzGateway answers "not joined" both when the server refuses the session
        # and when the server cannot be reached in time. Only an answer from the
        # server (an Ice.UserException, e.g. Glacier2.PermissionDeniedException)
        # means that the session has ended.
        if any(isinstance(error, Ice.UserException) for error in join_errors):
            raise OmeroSessionEnded("The OMERO session has ended. Log in again and start a new run.")
        reason = _omero_reason(join_errors[-1], key) if join_errors else "no answer from the server"
        raise ConnectionError(f"cannot reach the OMERO server at {host}:{port} ({reason})")
    return conn


def _keep_join_errors(conn):
    """A list that receives every error met by `conn` while it joins a session.

    BlitzGateway.connect does not pass these errors on; it only answers whether
    the session was joined.
    """
    errors = []
    client = getattr(conn, "c", None)
    join = getattr(client, "joinSession", None)
    if join is None:
        return errors

    def join_and_keep_errors(*arguments, **keywords):
        try:
            return join(*arguments, **keywords)
        except Exception as error:
            errors.append(error)
            raise

    client.joinSession = join_and_keep_errors
    return errors


def detach_session(conn):
    """Leave a joined session without ending it, so that other processes can go on using it."""
    try:
        conn.close(hard=False)
    except Exception:
        pass
