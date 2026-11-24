"""Result tables and the run folder.

The tables and their columns follow section 8.2 of the specification and the
run folder follows section 8.1. Each image's tables are written to
`per_image/` and joined into one table per type at the end of a run.
"""

import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
import yaml

from . import __version__
from .cells import CELL_COLUMNS
from .config import load_config, save_config

RESULTS_FOLDER_NAME = "bigfish_results"
PER_IMAGE_FOLDER_NAME = "per_image"
NPZ_FOLDER_NAME = "npz"
RUN_CONFIG_NAME = "run_config.yaml"
RUN_INFO_NAME = "run_info.yaml"
CALIBRATION_NAME = "calibration.csv"
TEMPORARY_SUFFIX = ".tmp"

# Packages whose versions go in `run_info.yaml`: (name shown, name of the installed package).
RUN_INFO_PACKAGES = (
    ("big-fish", "big-fish"),
    ("cellpose", "cellpose"),
    ("torch", "torch"),
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("scikit-image", "scikit-image"),
    ("tifffile", "tifffile"),
    ("omero-py", "omero-py"),
)
NOT_INSTALLED = "not installed"
NOT_AVAILABLE = "not available"
GIT_TIMEOUT_S = 10

RUN_INFO_HEADER = (
    "# Run record: when the run took place, on which computer, with which software,\n"
    "# and how it ended. The settings of the run are in run_config.yaml.\n"
)

# Kinds of per-image table, in the order they are written. `images` is last,
# so an image whose `_images.csv` exists has all its files.
TABLE_KINDS = ("spots", "clusters", "cells", "images")

CLUSTER_COLUMNS_3D = [
    "image", "channel", "channel_name", "cluster_id",
    "z_px", "y_px", "x_px", "z_nm", "y_nm", "x_nm",
    "n_spots", "cell_id",
]
CLUSTER_COLUMNS_2D = [name for name in CLUSTER_COLUMNS_3D if not name.startswith("z_")]

CELLS_TABLE_COLUMNS = ["image", "channel", "channel_name"] + CELL_COLUMNS

IMAGE_COLUMNS = [
    "image", "channel", "channel_name", "status", "reason",
    "threshold_mode", "threshold", "n_spots_detected", "n_spots", "n_clusters", "n_cells",
    "segmentation_source", "segmentation_status", "warnings", "runtime_s",
]

CALIBRATION_COLUMNS = ["image", "channel", "auto_threshold", "used", "reason"]

STATUS_CHOICES = ("done", "failed", "skipped")
SEGMENTATION_STATUS_CHOICES = ("done", "no_labels", "failed", "")

# Characters that Windows does not allow in file names, and control characters.
_UNSAFE_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class OutputError(Exception):
    """A problem with the output folder or the result files that the user must fix."""


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def spot_columns(ndim, subpixel=False, snr=False, intensity=False):
    """Columns of the spots table for a run.

    ndim: 3 for 3D images, 2 for 2D.
    subpixel: True when any channel of the run has subpixel fitting on.
    snr, intensity: True when any channel of the run has that measurement on.

    Every spots file of a run uses this one list, so the files share a header.
    """
    _check_ndim(ndim)
    axes = _axes(ndim)
    columns = ["image", "channel", "channel_name", "spot_id"]
    columns += [f"{axis}_px" for axis in axes]
    columns += [f"{axis}_nm" for axis in axes]
    if subpixel:
        columns += [f"{axis}_sub_px" for axis in axes]
        columns += [f"{axis}_sub_nm" for axis in axes]
    columns += ["cluster_id", "cell_id"]
    if snr:
        columns.append("snr")
    if intensity:
        columns.append("log_intensity")
    return columns


def cluster_columns(ndim):
    """Columns of the clusters table."""
    _check_ndim(ndim)
    return list(CLUSTER_COLUMNS_3D if ndim == 3 else CLUSTER_COLUMNS_2D)


def make_spots_table(
    image,
    channel,
    channel_name,
    spots,
    ndim,
    voxel_size_yx,
    voxel_size_z=None,
    cluster_id=None,
    cell_id=None,
    subpixel=None,
    snr=None,
    log_intensity=None,
    columns=None,
):
    """Spots table of one image and channel.

    spots: rows of (z, y, x) for ndim=3 or (y, x) for ndim=2, in pixels; any
        further column is ignored.
    voxel_size_yx, voxel_size_z: pixel sizes in nm (voxel_size_z only for 3D).
    cluster_id, cell_id: one value per spot; -1 for every spot when not given.
    subpixel: rows of subpixel positions in pixels, same layout as `spots`.
    snr, log_intensity: one value per spot.
    columns: the run's column list from `spot_columns`. Optional columns of
        the list that are not given here stay empty. When None, the optional
        columns are those given.

    Returns a DataFrame; `spot_id` counts from 0 in row order.
    """
    _check_ndim(ndim)
    axes = _axes(ndim)
    voxel = _voxel_sizes(ndim, voxel_size_yx, voxel_size_z)
    spots = _as_rows(spots, ndim, "spots")
    n = len(spots)

    if columns is None:
        columns = spot_columns(
            ndim,
            subpixel=subpixel is not None,
            snr=snr is not None,
            intensity=log_intensity is not None,
        )
    columns = list(columns)

    table = {
        "image": [image] * n,
        "channel": np.full(n, channel, dtype=np.int64),
        "channel_name": [channel_name] * n,
        "spot_id": np.arange(n, dtype=np.int64),
    }
    for position, axis in enumerate(axes):
        table[f"{axis}_px"] = spots[:, position]
    for position, axis in enumerate(axes):
        table[f"{axis}_nm"] = spots[:, position].astype(float) * voxel[position]

    if subpixel is not None:
        subpixel = _as_rows(subpixel, ndim, "subpixel")
        _check_length(subpixel, n, "subpixel")
        for position, axis in enumerate(axes):
            table[f"{axis}_sub_px"] = subpixel[:, position].astype(float)
        for position, axis in enumerate(axes):
            table[f"{axis}_sub_nm"] = subpixel[:, position].astype(float) * voxel[position]

    table["cluster_id"] = _ids_or_minus_one(cluster_id, n, "cluster_id")
    table["cell_id"] = _ids_or_minus_one(cell_id, n, "cell_id")

    for name, values in (("snr", snr), ("log_intensity", log_intensity)):
        if values is not None:
            values = np.asarray(values, dtype=float).ravel()
            _check_length(values, n, name)
            table[name] = values

    return _in_column_order(table, columns, n, "spots")


def make_clusters_table(
    image, channel, channel_name, clusters, ndim, voxel_size_yx, voxel_size_z=None, cell_id=None
):
    """Clusters table of one image and channel.

    clusters: big-fish's cluster array, rows of (z, y, x, n_spots, cluster_id)
        for ndim=3 or (y, x, n_spots, cluster_id) for ndim=2; None or empty
        when there are no clusters (the table then has no rows).
    cell_id: one value per cluster; -1 for every cluster when not given.
    """
    _check_ndim(ndim)
    axes = _axes(ndim)
    voxel = _voxel_sizes(ndim, voxel_size_yx, voxel_size_z)
    if clusters is None:
        clusters = np.zeros((0, ndim + 2), dtype=np.int64)
    clusters = _as_rows(clusters, ndim + 2, "clusters")
    n = len(clusters)

    table = {
        "image": [image] * n,
        "channel": np.full(n, channel, dtype=np.int64),
        "channel_name": [channel_name] * n,
        "cluster_id": clusters[:, ndim + 1].astype(np.int64),
    }
    for position, axis in enumerate(axes):
        table[f"{axis}_px"] = clusters[:, position]
    for position, axis in enumerate(axes):
        table[f"{axis}_nm"] = clusters[:, position].astype(float) * voxel[position]
    table["n_spots"] = clusters[:, ndim].astype(np.int64)
    table["cell_id"] = _ids_or_minus_one(cell_id, n, "cell_id")

    return _in_column_order(table, cluster_columns(ndim), n, "clusters")


def make_cells_table(image, channel, channel_name, cells):
    """Cells table of one image and channel.

    cells: the cell table returned by `cells.assign_cells`.
    """
    cells = pd.DataFrame(cells)
    if list(cells.columns) != CELL_COLUMNS:
        raise ValueError(f"The cell table must have the columns {CELL_COLUMNS}.")
    cells = cells.reset_index(drop=True)
    cells.insert(0, "channel_name", [channel_name] * len(cells))
    cells.insert(0, "channel", np.full(len(cells), channel, dtype=np.int64))
    cells.insert(0, "image", [image] * len(cells))
    return cells


def image_row(
    image,
    channel,
    channel_name,
    status,
    reason="",
    threshold_mode="",
    threshold=None,
    n_spots_detected=None,
    n_spots=None,
    n_clusters=None,
    n_cells=None,
    segmentation_source="",
    segmentation_status="",
    warnings=(),
    runtime_s=None,
):
    """One row of the images table, as a dictionary.

    status: done, failed or skipped.
    threshold, n_cells and the counts may be None, written as empty.
    segmentation_source and segmentation_status are empty when segmentation is off.
    warnings: a list of texts, joined with "; ".
    """
    if status not in STATUS_CHOICES:
        raise ValueError(f"status must be one of {STATUS_CHOICES}, not {status!r}.")
    if segmentation_status not in SEGMENTATION_STATUS_CHOICES:
        raise ValueError(
            f"segmentation_status must be one of {SEGMENTATION_STATUS_CHOICES}, "
            f"not {segmentation_status!r}."
        )
    if not isinstance(warnings, str):
        warnings = "; ".join(str(warning) for warning in warnings)
    return {
        "image": image,
        "channel": channel,
        "channel_name": channel_name,
        "status": status,
        "reason": reason or "",
        "threshold_mode": threshold_mode or "",
        "threshold": threshold,
        "n_spots_detected": n_spots_detected,
        "n_spots": n_spots,
        "n_clusters": n_clusters,
        "n_cells": n_cells,
        "segmentation_source": segmentation_source or "",
        "segmentation_status": segmentation_status or "",
        "warnings": warnings,
        "runtime_s": runtime_s,
    }


def make_images_table(rows):
    """Images table from rows made by `image_row`, one row per image and channel."""
    table = pd.DataFrame(list(rows), columns=IMAGE_COLUMNS)
    table["channel"] = table["channel"].astype("Int64")
    for name in ("n_spots_detected", "n_spots", "n_clusters", "n_cells"):
        table[name] = table[name].astype("Int64")
    for name in ("threshold", "runtime_s"):
        table[name] = table[name].astype(float)
    return table


def make_calibration_table(rows):
    """Calibration table: one row per subset image and channel.

    rows: dictionaries or tuples of (image, channel, auto_threshold, used, reason).
    auto_threshold may be None when no usable value was found.
    """
    rows = list(rows)
    if rows and not isinstance(rows[0], dict):
        rows = [dict(zip(CALIBRATION_COLUMNS, row)) for row in rows]
    table = pd.DataFrame(rows, columns=CALIBRATION_COLUMNS)
    table["channel"] = table["channel"].astype("Int64")
    table["auto_threshold"] = table["auto_threshold"].astype(float)
    table["used"] = table["used"].astype(bool)
    table["reason"] = table["reason"].fillna("")
    return table


def join_tables(tables, columns=None):
    """One table from several (for example one per channel), in the order given.

    Tables without rows add nothing; the result keeps the columns of the
    first table, or `columns` when there are no tables.
    """
    tables = [pd.DataFrame(table) for table in tables if table is not None]
    if not tables:
        return pd.DataFrame(columns=columns or [])
    header = list(tables[0].columns)
    for table in tables[1:]:
        if list(table.columns) != header:
            raise ValueError("Tables to be joined must have the same columns in the same order.")
    with_rows = [table for table in tables if len(table)]
    if not with_rows:
        return tables[0].iloc[0:0].reset_index(drop=True)
    return pd.concat(with_rows, ignore_index=True)


# ---------------------------------------------------------------------------
# Per-image files and combined tables
# ---------------------------------------------------------------------------


def per_image_path(run_folder, image, kind):
    """Path of one image's table, e.g. `per_image/<image>_spots.csv`."""
    if kind not in TABLE_KINDS:
        raise ValueError(f"kind must be one of {TABLE_KINDS}, not {kind!r}.")
    return Path(run_folder) / PER_IMAGE_FOLDER_NAME / f"{image}_{kind}.csv"


def npz_path(run_folder, image, channel):
    """Path of one image and channel's `.npz` file, e.g. `npz/<image>_ch2.npz`."""
    return Path(run_folder) / NPZ_FOLDER_NAME / f"{image}_ch{channel}.npz"


def write_image_tables(run_folder, image, images, spots=None, clusters=None, cells=None, arrays=None):
    """Write one image's tables to the run folder's `per_image/` folder, and its
    `.npz` files to `npz/`.

    Each table holds the rows of all the image's channels; a list of tables
    (one per channel) is joined first. `images` is required. A table given as
    None is not written: `cells` is None when the image has no cell results,
    `spots` and `clusters` are None for an image that failed as a whole.

    arrays: None, or for each channel index the arrays of its `.npz` file
        (name to array), written with numpy's `savez` under these names.
        The `npz/` folder is made when there is a file to write.

    The files are written under temporary names and renamed once all are
    written, `_images.csv` last. If anything fails, no file of the image is
    left behind. Returns the paths written.
    """
    tables = {"spots": spots, "clusters": clusters, "cells": cells, "images": images}
    if images is None:
        raise ValueError("The images table is required.")

    to_write = []
    for kind in TABLE_KINDS:
        table = tables[kind]
        if table is None:
            continue
        if isinstance(table, (list, tuple)):
            table = join_tables(table)
        final = per_image_path(run_folder, image, kind)
        to_write.append((_csv_writer(table), _temporary_path(final), final))
    # the .npz files go before `_images.csv`, which is renamed last
    npz_files = [
        (_npz_writer(named), _temporary_path(npz_path(run_folder, image, channel)),
         npz_path(run_folder, image, channel))
        for channel, named in (arrays or {}).items()
    ]
    to_write[-1:-1] = npz_files

    renamed = []
    current = None
    try:
        if npz_files:
            current = npz_files[0][2]
            current.parent.mkdir(parents=True, exist_ok=True)
        for write, temporary, final in to_write:
            current = final
            write(temporary)
        for _, temporary, final in to_write:
            current = final
            os.replace(temporary, final)
            renamed.append(final)
    except BaseException as error:
        for _, temporary, final in to_write:
            _remove_quietly(temporary)
        for final in renamed:
            _remove_quietly(final)
        if isinstance(error, OSError):
            if current is not None and current.suffix == ".npz":
                raise OutputError(
                    f"The .npz files of image `{image}` could not be written to "
                    f"{Path(run_folder) / NPZ_FOLDER_NAME}: {error}"
                ) from error
            raise OutputError(
                f"The tables of image `{image}` could not be written to "
                f"{Path(run_folder) / PER_IMAGE_FOLDER_NAME}: {error}"
            ) from error
        raise
    return [final for _, _, final in to_write]


def remove_image_files(run_folder, image, channels=()):
    """Remove every file of an image from `per_image/` and `npz/`, finished or not,
    temporary names included.

    channels: the channel indices of the run, whose `.npz` files are removed.
    """
    paths = [per_image_path(run_folder, image, kind) for kind in TABLE_KINDS]
    paths += [npz_path(run_folder, image, channel) for channel in channels]
    for path in paths:
        _remove_quietly(path)
        _remove_quietly(_temporary_path(path))


def image_is_complete(run_folder, image):
    """True when the image's `_images.csv` exists, so all its files are written."""
    return per_image_path(run_folder, image, "images").is_file()


def combine_tables(run_folder, images):
    """Join the per-image files of finished images into one table per type.

    images: output names of the finished images, in run order.

    Writes `images.csv`, `spots.csv`, `clusters.csv` and `cells.csv` in the
    run folder. Every listed image must have its `_images.csv`; the other
    tables are joined from the images that have them, and a table is written
    only when at least one image has it (so `cells.csv` only when some image
    has cell results). Files are joined as text with one header line, without
    reading them into memory. Nothing is written when `images` is empty.

    Returns a dictionary of table kind to the path written.
    """
    run_folder = Path(run_folder)
    images = list(images)
    written = {}
    for kind in TABLE_KINDS:
        sources = []
        for image in images:
            path = per_image_path(run_folder, image, kind)
            if path.is_file():
                sources.append(path)
            elif kind == "images":
                raise OutputError(f"The results of image `{image}` are not complete: {path} is missing.")
        if not sources:
            continue
        final = run_folder / f"{kind}.csv"
        temporary = _temporary_path(final)
        try:
            _join_csv_files(sources, temporary)
            os.replace(temporary, final)
        except BaseException as error:
            _remove_quietly(temporary)
            if isinstance(error, OSError):
                raise OutputError(f"The table {final} could not be written: {error}") from error
            raise
        written[kind] = final
    return written


def _join_csv_files(sources, destination):
    """Copy the CSV files into one, keeping only the first file's header line."""
    header = None
    with open(destination, "w", encoding="utf-8", newline="") as out:
        for source in sources:
            with open(source, "r", encoding="utf-8", newline="") as part:
                first_line = part.readline()
                if not first_line:
                    raise OutputError(f"The table {source} is empty; it should at least have a header line.")
                if header is None:
                    header = first_line
                    out.write(header)
                elif first_line != header:
                    raise OutputError(
                        f"The table {source} has other columns than {sources[0]}, "
                        "so they cannot be joined."
                    )
                shutil.copyfileobj(part, out)


# ---------------------------------------------------------------------------
# Run folder
# ---------------------------------------------------------------------------


def output_root(config):
    """Folder that holds the run folders.

    The config's output folder, or `<input folder>/bigfish_results/` when it
    is empty. An OMERO run must name an output folder.
    """
    output_folder = config.full_output_folder()
    if output_folder is not None:
        return output_folder
    if config.run.input.source == "omero":
        raise OutputError("OMERO runs need an output folder: set `run.output_folder`.")
    input_folder = config.full_input_folder()
    if input_folder is None:
        raise OutputError(
            "There is no output folder and no input folder: set `run.output_folder` "
            "or `run.input.folder`."
        )
    return input_folder / RESULTS_FOLDER_NAME


def check_writable(folder):
    """Check that files can be made in `folder`, by creating and removing a small file.

    When the folder does not exist yet, the nearest folder above it that exists
    is checked instead, and nothing is created. Raises OutputError when the
    folder cannot be written.
    """
    folder = Path(folder)
    existing = folder
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    if not existing.is_dir():
        raise OutputError(f"The output folder {folder} cannot be made: {existing} is not a folder.")
    probe = existing / f".bigfish_write_check_{os.getpid()}"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        _remove_quietly(probe)
        raise OutputError(
            f"The output folder {folder} cannot be written to; choose another output "
            "folder (`run.output_folder`)."
        ) from None


def safe_run_name(name):
    """Run name with characters that Windows does not allow in file names replaced by `_`.

    Spaces and dots at the end, which Windows also does not allow, are removed.
    An empty name becomes `run`.
    """
    name = _UNSAFE_CHARACTERS.sub("_", str(name)).rstrip(" .")
    return name or "run"


def make_run_folder(config, now=None):
    """Create the run folder `<root>/<YYYY-MM-DD_HHMM>_<run name>/` and its `per_image/` folder.

    The root is given by `output_root`. When the folder already exists, a
    number is added (`_2`, `_3`, ...). The root is checked for writing before
    anything is created. `now` sets the time used in the name (default: now).

    Returns the path of the run folder.
    """
    root = output_root(config)
    check_writable(root)
    now = datetime.now() if now is None else now
    base = f"{now:%Y-%m-%d_%H%M}_{safe_run_name(config.run.name)}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        number = 1
        while True:
            run_folder = root / (base if number == 1 else f"{base}_{number}")
            try:
                run_folder.mkdir()
                break
            except FileExistsError:
                number += 1
        (run_folder / PER_IMAGE_FOLDER_NAME).mkdir()
    except OSError as error:
        raise OutputError(f"The run folder could not be made in {root}: {error}") from None
    return run_folder


def write_run_config(run_folder, config, images, thresholds=None):
    """Write `run_config.yaml`: the config with every default filled in, full paths,
    and the `resolved` block.

    images: names of the images of the run, in order.
    thresholds: channel index to calibrated threshold. When None, the
        thresholds already in the config's `resolved` block are kept.

    Returns the path written.
    """
    if thresholds is None:
        thresholds = config.resolved.thresholds if config.resolved is not None else {}
    thresholds = {int(index): float(value) for index, value in thresholds.items()}
    images = [str(image) for image in images]
    full = config.with_full_paths().with_resolved(images, thresholds)
    path = Path(run_folder) / RUN_CONFIG_NAME
    _save_config_replacing(full, path)
    return path


def add_thresholds_to_run_config(run_folder, thresholds):
    """Add calibrated thresholds to the run folder's `run_config.yaml`.

    thresholds: channel index to calibrated threshold; they replace any
    thresholds already in the file. Returns the path written.
    """
    path = Path(run_folder) / RUN_CONFIG_NAME
    config = load_config(path)
    images = config.resolved.images if config.resolved is not None else []
    return write_run_config(run_folder, config, images, thresholds)


def write_calibration(run_folder, calibration):
    """Write `calibration.csv` in the run folder.

    calibration: a table from `make_calibration_table`, or rows for it.
    Returns the path written.
    """
    if not isinstance(calibration, pd.DataFrame):
        calibration = make_calibration_table(calibration)
    path = Path(run_folder) / CALIBRATION_NAME
    temporary = _temporary_path(path)
    try:
        _write_csv(calibration[CALIBRATION_COLUMNS], temporary)
        os.replace(temporary, path)
    except OSError as error:
        _remove_quietly(temporary)
        raise OutputError(f"The table {path} could not be written: {error}") from error
    return path


def write_text_replacing(path, text):
    """Write a text file under a temporary name, then put it in place of the old one.

    A program reading the file sees either the old or the new text, never a
    half-written file.
    """
    path = Path(path)
    temporary = _temporary_path(path)
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except BaseException:
        _remove_quietly(temporary)
        raise
    return path


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------


def package_versions():
    """Version of each package of RUN_INFO_PACKAGES, or "not installed".

    The versions are read from the installed package details, so no package
    is loaded (a run without Cellpose never loads `cellpose` or `torch`).
    """
    versions = {}
    for shown, installed in RUN_INFO_PACKAGES:
        try:
            versions[shown] = importlib.metadata.version(installed)
        except importlib.metadata.PackageNotFoundError:
            versions[shown] = NOT_INSTALLED
        except Exception:
            versions[shown] = NOT_AVAILABLE
    return versions


def git_commit(package_folder=None):
    """The git commit of the pipeline's code, or None.

    Given only when the package runs from the source folder of a git copy
    (`src/bigfish_pypeline/` of a repository) and git is installed. Changes
    not yet committed are mentioned after the commit.
    """
    package_folder = Path(package_folder or Path(__file__).parent).resolve()
    git = shutil.which("git")
    if git is None:
        return None

    def ask(*arguments):
        done = subprocess.run(
            [git, "-C", str(package_folder), *arguments], capture_output=True, text=True,
            timeout=GIT_TIMEOUT_S, stdin=subprocess.DEVNULL,
        )
        if done.returncode != 0:
            raise OSError(done.stderr.strip())
        return done.stdout.strip()

    try:
        top = Path(ask("rev-parse", "--show-toplevel")).resolve()
        if top / "src" / package_folder.name != package_folder:
            return None
        commit = ask("rev-parse", "HEAD")
        if ask("status", "--porcelain", "--untracked-files=no"):
            commit += " (with changes not yet committed)"
        return commit
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def operating_system():
    """Name and version of the operating system, e.g. "macOS 15.1 (arm64)"."""
    try:
        system = platform.system()
        machine = platform.machine()
        if system == "Darwin":
            name = f"macOS {platform.mac_ver()[0]}"
        elif system == "Windows":
            name = f"Windows {platform.release()} (version {platform.version()})"
        elif system == "Linux":
            try:
                name = platform.freedesktop_os_release()["PRETTY_NAME"]
            except (OSError, KeyError):
                name = f"Linux {platform.release()}"
        else:
            name = platform.platform()
        return f"{name} ({machine})" if machine else name
    except Exception:
        return NOT_AVAILABLE


def computer_memory():
    """Memory of the computer, e.g. "17.2 GB"."""
    try:
        return f"{psutil.virtual_memory().total / 1e9:.1f} GB"
    except Exception:
        return NOT_AVAILABLE


def run_info_text(info):
    """Text of `run_info.yaml` for `info`, a dictionary whose keys keep their order."""
    body = yaml.safe_dump(info, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000)
    return RUN_INFO_HEADER + body


def write_run_info(run_folder, info):
    """Write `run_info.yaml` in the run folder, under a temporary name first.

    info: a dictionary of plain values, written in the order given.
    Returns the path written; raises OutputError when it cannot be written.
    """
    path = Path(run_folder) / RUN_INFO_NAME
    try:
        write_text_replacing(path, run_info_text(info))
    except OSError as error:
        raise OutputError(f"{path} could not be written: {error}") from error
    return path


def read_run_info(run_folder):
    """The contents of a run folder's `run_info.yaml`, as a dictionary."""
    path = Path(run_folder) / RUN_INFO_NAME
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_ndim(ndim):
    if ndim not in (2, 3):
        raise ValueError(f"ndim must be 2 or 3, not {ndim}.")


def _axes(ndim):
    return ("z", "y", "x") if ndim == 3 else ("y", "x")


def _voxel_sizes(ndim, voxel_size_yx, voxel_size_z):
    """Pixel size in nm along each axis, in the order of the coordinates."""
    if ndim == 3:
        if voxel_size_z is None:
            raise ValueError("voxel_size_z is needed for 3D coordinates.")
        return (float(voxel_size_z), float(voxel_size_yx), float(voxel_size_yx))
    return (float(voxel_size_yx), float(voxel_size_yx))


def _as_rows(coord, width, what):
    """Coordinates as a 2D array with one row per object; an empty input gives zero rows."""
    coord = np.asarray(coord)
    if coord.size == 0:
        return np.zeros((0, max(width, coord.shape[1] if coord.ndim == 2 else 0)), dtype=np.int64)
    if coord.ndim != 2 or coord.shape[1] < width:
        raise ValueError(
            f"{what} must have one row per object and at least {width} columns; "
            f"got shape {coord.shape}."
        )
    return coord


def _check_length(values, n, what):
    if len(values) != n:
        raise ValueError(f"{what} has {len(values)} rows but there are {n} spots.")


def _ids_or_minus_one(values, n, what):
    if values is None:
        return np.full(n, -1, dtype=np.int64)
    values = np.asarray(values).ravel().astype(np.int64)
    if len(values) != n:
        raise ValueError(f"{what} has {len(values)} values but there are {n} rows.")
    return values


def _in_column_order(table, columns, n, what):
    """DataFrame with exactly `columns`; listed columns not in `table` stay empty."""
    extra = [name for name in table if name not in columns]
    if extra:
        raise ValueError(f"The {what} table has values for {extra}, which are not in its columns.")
    data = {}
    for name in columns:
        data[name] = table[name] if name in table else np.full(n, np.nan)
    return pd.DataFrame(data, columns=columns)


def _temporary_path(path):
    path = Path(path)
    return path.with_name(path.name + TEMPORARY_SUFFIX)


def _csv_writer(table):
    return lambda path: _write_csv(table, path)


def _npz_writer(named):
    def write(path):
        # written through an open file, so that numpy does not add `.npz` to the name
        with open(path, "wb") as npz_file:
            np.savez(npz_file, **named)
    return write


def _write_csv(table, path):
    """Write a table as UTF-8 CSV with empty values left blank."""
    table.to_csv(path, index=False, encoding="utf-8", na_rep="", lineterminator="\n")


def _save_config_replacing(config, path):
    temporary = _temporary_path(path)
    try:
        save_config(config, temporary)
        os.replace(temporary, path)
    except OSError as error:
        _remove_quietly(temporary)
        raise OutputError(f"{path} could not be written: {error}") from error


def _remove_quietly(path):
    try:
        Path(path).unlink()
    except OSError:
        pass
