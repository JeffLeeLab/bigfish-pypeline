"""Tests for the Optimise notebook, steps 1 to 9 (`notebooks/bigfish-optimise.ipynb`).

The notebook is run with nbclient in the environment's own `python3` kernel. A run
replaces the values of chosen `values:<step>` cells (as a user would edit them),
adds a last cell that writes the settings and the tables of each channel to a
folder, and returns the executed notebook with the files that cell wrote.
OMERO is replaced by the stand-in connection of `test_io_omero.py`.
"""

import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path
from unittest import mock

import nbformat
import numpy as np
import pytest
import tifffile
import yaml
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

from bigfish_pypeline import io, steps
from bigfish_pypeline.config import load_config, parse_config
from conftest import CROP_NAME, FISH_CHANNEL, TEST_DATA
from test_steps import run_steps

REPOSITORY = Path(__file__).resolve().parent.parent
NOTEBOOK_FOLDER = REPOSITORY / "notebooks"
NOTEBOOK = NOTEBOOK_FOLDER / "bigfish-optimise.ipynb"

# The values cells, in the order of the notebook.
VALUES_STEPS = [
    "source", "image", "channel", "background", "log-picture", "threshold",
    "decomposition", "subpixel", "clusters", "measurements",
]
# The cells from the channel values to the result of a channel (what a user runs again for another channel).
CHANNEL_FIRST_TAG = "values:channel"
CHANNEL_LAST_ID = "summary"

OMERO_IMAGE_ID = 1234
OMERO_IMAGE_NAME = f"{CROP_NAME}.tif"

# The last cell added to every run.
SAVE_RESULTS = """
import pathlib
from bigfish_pypeline.config import save_config
out = pathlib.Path({folder!r})
save_config(config, out / "settings.yaml")
for index, tables in tables_by_channel.items():
    tables["spots"].to_csv(out / f"spots_ch{{index}}.csv", index=False)
    tables["clusters"].to_csv(out / f"clusters_ch{{index}}.csv", index=False)
"""

# A stand-in for the OMERO server, written into the folder the notebook runs in.
OMERO_STAND_IN = """
import json
import sys
from pathlib import Path

import numpy as np
import tifffile

sys.path.insert(0, {tests!r})
from test_io_omero import FakeConn, FakeImage

from bigfish_pypeline import omero_tools


class Conn(FakeConn):
    def close(self, hard=True):
        Path("closed.txt").write_text("closed")


def install():
    stack = tifffile.imread({crop!r})
    conn = Conn(images=[FakeImage({image_id}, {image_name!r}, stack[np.newaxis])])

    def connect_to_omero(username, host, port, password=None, secure=True):
        Path("login.json").write_text(json.dumps(
            dict(username=username, host=host, port=port, password_given=password is not None)
        ))
        return conn

    omero_tools.connect_to_omero = connect_to_omero
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_notebook():
    return nbformat.read(NOTEBOOK, as_version=4)


def tag_of(cell):
    return next((tag for tag in cell.metadata.get("tags", []) if tag.startswith("values:")), None)


def values_cell(notebook, step):
    found = [cell for cell in notebook.cells if tag_of(cell) == f"values:{step}"]
    assert len(found) == 1, f"values:{step} is in {len(found)} cells"
    return found[0]


def set_values(cells, step, **assignments):
    """Replace the right-hand side of named assignments in a values cell, keeping their comments."""
    cell = values_cell(cells, step) if hasattr(cells, "cells") else cells
    lines = cell.source.split("\n")
    for name, value in assignments.items():
        pattern = re.compile(rf"^{re.escape(name)} = (?P<value>.*?)(?P<comment>\s+#.*)?$")
        for position, line in enumerate(lines):
            found = pattern.match(line)
            if found:
                lines[position] = f"{name} = {value!r}{found.group('comment') or ''}"
                break
        else:
            raise AssertionError(f"{name} is not set in the values cell of {step}")
    cell.source = "\n".join(lines)


def repeat_for_channel(notebook, replacements):
    """Run the cells from the channel values to the result of a channel a second time,
    with other values, as a user does for another channel.

    replacements: {step: {name: value}} for the values cells of the repeated cells.
    """
    cells = notebook.cells
    first = next(i for i, cell in enumerate(cells) if tag_of(cell) == CHANNEL_FIRST_TAG)
    last = next(i for i, cell in enumerate(cells) if cell.id == CHANNEL_LAST_ID)
    again = copy.deepcopy(cells[first:last + 1])
    for cell in again:
        cell.id = f"{cell.id}-again"
        step = (tag_of(cell) or "").removeprefix("values:")
        if step in replacements:
            set_values(cell, step, **replacements[step])
    cells[last + 1:last + 1] = again


def insert_before(notebook, cell_id, source):
    position = next(i for i, cell in enumerate(notebook.cells) if cell.id == cell_id)
    cell = nbformat.v4.new_code_cell(source)
    cell.id = f"added-{cell_id}"
    notebook.cells.insert(position, cell)


def insert_after(notebook, cell_id, source):
    position = next(i for i, cell in enumerate(notebook.cells) if cell.id == cell_id)
    cell = nbformat.v4.new_code_cell(source)
    cell.id = f"added-after-{cell_id}"
    notebook.cells.insert(position + 1, cell)


def run_notebook(notebook, work_folder, out_folder, before=None):
    """Execute a notebook in `work_folder` and return the executed copy; the settings and tables
    are written to `out_folder`. Raises nbclient's CellExecutionError when a cell fails."""
    notebook = copy.deepcopy(notebook)
    work_folder, out_folder = Path(work_folder), Path(out_folder)
    out_folder.mkdir(parents=True, exist_ok=True)
    cell = nbformat.v4.new_code_cell(SAVE_RESULTS.format(folder=str(out_folder)))
    cell.id = "test-save-results"
    notebook.cells.append(cell)
    # the kernel of this environment, whatever the shell's PATH
    path = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
    with mock.patch.dict(os.environ, {"PATH": path}):
        client = NotebookClient(
            notebook, kernel_name="python3", timeout=300,
            resources={"metadata": {"path": str(work_folder)}},
        )
        client.execute()
    return notebook


def cell_by_id(notebook, cell_id):
    return next(cell for cell in notebook.cells if cell.id == cell_id)


def printed(notebook, cell_id):
    """The text a cell printed."""
    cell = cell_by_id(notebook, cell_id)
    return "".join(out.text for out in cell.outputs if out.output_type == "stream")


def mime_types(notebook, cell_id):
    """The richest outputs of a cell, one list of types for each figure or table shown."""
    cell = cell_by_id(notebook, cell_id)
    return [list(out.data) for out in cell.outputs if out.output_type in ("display_data", "execute_result")]


def n_pictures(notebook, cell_id):
    return sum("image/png" in types for types in mime_types(notebook, cell_id))


def assert_everything_ran(notebook):
    for cell in notebook.cells:
        if cell.cell_type == "code":
            assert cell.execution_count is not None, f"cell {cell.id} did not run"
            assert not [out for out in cell.outputs if out.output_type == "error"], cell.id


def reference_config(overrides=None):
    """The test kit's settings with changes to its one channel: nested dictionaries, as in the settings file."""
    data = load_config(TEST_DATA / f"{CROP_NAME}_config.yaml").to_dict()
    for name, value in (overrides or {}).items():
        if isinstance(value, dict):
            data["channels"][0][name] = {**data["channels"][0][name], **value}
        else:
            data["channels"][0][name] = value
    return parse_config(data)


# The channel settings of the pipeline's defaults (the notebook's values as committed), written
# over the test kit's settings, which reproduce the old v1 run (top-hat, manual 18, clusters 600 and 12).
DEFAULT_CHANNEL = {
    "background": {"method": "rolling_ball", "radius_px": 5},
    "threshold": {"mode": "auto", "value": None, "lower_limit": None},
    "clusters": {"radius_nm": 500, "min_spots": 4},
}


def default_config(overrides=None):
    """The settings the notebook gives as committed (the defaults) for the test kit's channel 2,
    with changes to its one channel."""
    merged = {name: dict(value) for name, value in DEFAULT_CHANNEL.items()}
    for name, value in (overrides or {}).items():
        merged[name] = {**merged.get(name, {}), **value} if isinstance(value, dict) else value
    return reference_config(merged)


def groups(config):
    """The groups of settings that steps 1 to 9 of the notebook set."""
    data = config.to_dict()
    return {name: data[name] for name in ("image", "microscope", "channels")}


def expected_tables(config, image_name, channel_index=FISH_CHANNEL):
    """The spots and clusters tables of the steps called one by one, as csv text."""
    image = io.read_channel(TEST_DATA / f"{CROP_NAME}.tif", "ZCYX", channel_index)
    tables = run_steps(config, image_name, image, None)
    return (
        tables["spots"].to_csv(index=False),
        tables["clusters"].to_csv(index=False),
    )


def assert_tables(out_folder, config, image_name, channel_index=FISH_CHANNEL):
    spots, clusters = expected_tables(config, image_name, channel_index)
    assert (Path(out_folder) / f"spots_ch{channel_index}.csv").read_text() == spots
    assert (Path(out_folder) / f"clusters_ch{channel_index}.csv").read_text() == clusters


@pytest.fixture(scope="module")
def committed():
    return load_notebook()


# ---------------------------------------------------------------------------
# The committed file
# ---------------------------------------------------------------------------


def test_the_notebook_is_valid_nbformat_with_the_python3_kernel(committed):
    nbformat.validate(committed)
    assert committed.nbformat == 4
    assert committed.metadata["kernelspec"]["name"] == "python3"


def test_the_notebook_is_committed_without_outputs_or_execution_counts(committed):
    for cell in committed.cells:
        if cell.cell_type == "code":
            assert cell.outputs == [], cell.id
            assert cell.execution_count is None, cell.id


def test_the_values_tags_are_unique_and_cover_every_step(committed):
    tags = [tag_of(cell) for cell in committed.cells if tag_of(cell)]
    assert len(tags) == len(set(tags))
    assert tags == [f"values:{step}" for step in VALUES_STEPS]
    assert all(cell.cell_type == "code" for cell in committed.cells if tag_of(cell))


def test_the_notebook_has_no_path_outside_the_repository(committed):
    text = NOTEBOOK.read_text(encoding="utf-8")
    assert not re.search(r"/(Users|home|private|tmp|var|Volumes)/|[A-Za-z]:\\\\|~/", text)
    folders = re.findall(r'^folder = "([^"]*)"', values_cell(committed, "source").source, re.M)
    assert folders == ["../tests/data"]
    assert (NOTEBOOK_FOLDER / folders[0]).resolve() == TEST_DATA.resolve()
    for password in ("password =", "password="):
        assert password not in text


def test_every_values_cell_holds_only_commented_assignments(committed):
    import ast

    for step in VALUES_STEPS:
        source = values_cell(committed, step).source
        lines = source.split("\n")
        assert lines[0].startswith("# Values for step"), step
        for line in lines[1:]:
            assert line.startswith("# ") or re.match(r"^\w+ = .+\s+# \S", line), (step, line)
        names = [node.targets[0].id for node in ast.parse(source).body]
        assert len(names) == len(set(names)), step


def test_the_notebook_leaves_the_pipeline_to_the_package(committed):
    code = "\n".join(cell.source for cell in committed.cells if cell.cell_type == "code")
    for lower_level in (
        "detect_spots", "filter_channel", "decompose_dense_regions", "detect_clusters",
        "measure_spots", "bigfish.detection", "bigfish.stack", "get_seed",
        "tifffile",
    ):
        assert lower_level not in code, lower_level
    assert not re.search(r"(?<!steps\.)\bfit_subpixel\(", code)


def test_the_values_helper_changes_only_the_value_and_keeps_the_comment(committed):
    cell = copy.deepcopy(values_cell(committed, "threshold"))
    before = cell.source.split("\n")

    set_values(cell, "threshold", threshold_mode="auto", lower_limit=5)

    after = cell.source.split("\n")
    changed = [line for line, old in zip(after, before) if line != old]
    assert [line.split("  ")[0] for line in changed] == ['threshold_mode = \'auto\'', "lower_limit = 5"]
    assert all("  # " in line for line in changed)
    with pytest.raises(AssertionError, match="not set"):
        set_values(cell, "threshold", no_such_value=1)


def committed_values(committed):
    """Every value of every values cell as committed, by name."""
    import ast

    found = {}
    for step in VALUES_STEPS:
        for node in ast.parse(values_cell(committed, step).source).body:
            found[node.targets[0].id] = ast.literal_eval(node.value)
    return found


def test_the_values_as_committed_are_the_defaults_of_the_settings(committed):
    from bigfish_pypeline import config as models

    channel = models.ChannelSettings(index=0)
    microscope = models.MicroscopeSettings()
    defaults = {
        # step 3
        "extension": models.InputSettings().extension,
        "omero_port": models.OMERO_PORT,
        # step 4
        "microscope_type": microscope.type,
        "numerical_aperture": microscope.NA,
        "refractive_index": microscope.RI,
        # step 5
        "excitation_nm": channel.ex,
        "emission_nm": channel.em,
        "assay_type": models.ASSAY_SMFISH,  # the smFISH preset equals the defaults
        # step 6
        "background_method": channel.background.method,
        "background_radius_px": channel.background.radius_px,
        # step 7
        "threshold_mode": channel.threshold.mode,
        "threshold_value": channel.threshold.value,
        "lower_limit": channel.threshold.lower_limit,
        "calibration_filter": channel.threshold.calibration_filter,
        "bailout_max_spots": channel.bailout.max_spots,
        # step 8
        "alpha": channel.decomposition.alpha,
        "beta": channel.decomposition.beta,
        "use_subpixel": channel.subpixel.enabled,
        "cluster_radius_nm": channel.clusters.radius_nm,
        "cluster_min_spots": channel.clusters.min_spots,
        "measure_snr": channel.measurements.snr,
        "measure_intensity": channel.measurements.intensity,
    }
    # the facts of the test kit's image, a choice made for the run, and values that are not settings
    not_settings = {
        "image_source", "cell_results", "folder", "name_filter", "image_number", "omero_host",
        "omero_username", "omero_image_id", "layout", "voxel_size_yx_nm", "voxel_size_z_nm",
        "show_previews", "channel_index", "channel_name", "profile_start", "profile_end",
        "save_log_picture", "log_picture_file", "run_calibration",
        # None keeps the choice of the assay type
        "use_decomposition", "use_clusters",
    }
    values = committed_values(committed)

    assert set(values) == set(defaults) | not_settings
    for name, default in defaults.items():
        assert values[name] == default, name
    assert values["use_decomposition"] is None and values["use_clusters"] is None
    # the test kit's own facts
    assert (values["layout"], values["voxel_size_yx_nm"], values["voxel_size_z_nm"]) == ("ZCYX", 65, 200)
    assert (values["channel_index"], values["channel_name"]) == (FISH_CHANNEL, "jim-exon")


# ---------------------------------------------------------------------------
# The notebook as committed, run from its own folder on the tissue crop
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def committed_run(committed, tmp_path_factory):
    out = tmp_path_factory.mktemp("committed_out")
    executed = run_notebook(committed, NOTEBOOK_FOLDER, out)
    return executed, out


def test_the_committed_notebook_runs_top_to_bottom_on_the_tissue_crop(committed_run):
    executed, _ = committed_run

    assert_everything_ran(executed)
    assert "0  sypN_DAPI_Phal_jim-exon_crop.tif" in printed(executed, "list-images")
    assert "Layout: ZCYX (11 planes, 3 channels)" in printed(executed, "image-info")
    assert "Channel 2 read: (11, 384, 384)" in printed(executed, "channel")
    # the folder of the notebook is left as it was found
    assert not list(NOTEBOOK_FOLDER.glob("*.tif"))


def test_the_committed_notebook_shows_its_figures(committed_run):
    executed, _ = committed_run

    # the figures of matplotlib are pictures; the interactive LoG view is a plotly output
    assert n_pictures(executed, "previews") == 1
    assert n_pictures(executed, "log-picture") == 2
    assert n_pictures(executed, "detect") == 3  # elbow plot, histogram, detection plot
    assert n_pictures(executed, "decomposition") == 1
    assert n_pictures(executed, "summary") == 1
    log_view = mime_types(executed, "log-view")
    assert log_view and all("application/vnd.plotly.v1+json" in types for types in log_view)
    assert "text/html" in mime_types(executed, "summary")[-1]  # the first rows of the spots table


def test_the_committed_notebook_ends_with_the_default_settings_for_the_test_kit_image(committed_run):
    executed, out = committed_run

    saved = load_config(out / "settings.yaml")
    assert groups(saved) == groups(default_config())
    assert [channel.index for channel in saved.channels] == [FISH_CHANNEL]
    assert saved.segmentation.enabled  # cell_results is on in the values
    assert saved.resolved is None
    text = printed(executed, "settings")
    channel = yaml.safe_load(text)["channels"][0]
    assert channel["threshold"]["mode"] == "auto" and channel["threshold"]["value"] is None
    assert "segmentation" not in text


def test_the_committed_notebook_gives_the_spots_and_clusters_of_the_steps(committed_run):
    executed, out = committed_run

    assert_tables(out, default_config(), CROP_NAME)
    assert "Threshold used: 12.0 (automatic)." in printed(executed, "detect")
    assert "601 spots found." in printed(executed, "detect")
    assert "Spots before decomposition: 601; after: 868." in printed(executed, "decomposition")
    assert "29 clusters, holding 230 of the 868 spots." in printed(executed, "clusters")


def test_steps_that_are_switched_off_print_one_line(committed_run):
    executed, _ = committed_run

    assert printed(executed, "subpixel") == "Subpixel fitting is switched off for this channel.\n"
    assert printed(executed, "measurements") == "Measurements are switched off for this channel.\n"
    assert printed(executed, "calibration") == "Calibration is switched off (run_calibration = False).\n"
    assert printed(executed, "omero-login") == "The image is in a local folder, so there is no OMERO log-in.\n"
    assert printed(executed, "omero-close") == "There is no OMERO session to close.\n"


# ---------------------------------------------------------------------------
# Values replaced: calibrated threshold, the amplified preset, subpixel fitting and measurements
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def calibrated_run(committed, tmp_path_factory):
    base = tmp_path_factory.mktemp("calibrated")
    images = base / "images"
    images.mkdir()
    for name in ("crop_a", "crop_b"):
        shutil.copy(TEST_DATA / f"{CROP_NAME}.tif", images / f"{name}.tif")
    (images / "other.tif").write_bytes(b"not an image")  # listed, but not named by the calibration filter

    notebook = copy.deepcopy(committed)
    set_values(notebook, "source", folder=str(images), name_filter="", cell_results=False)
    set_values(notebook, "channel", assay_type="amplified")
    set_values(notebook, "background", background_radius_px=6)
    set_values(notebook, "log-picture", save_log_picture=True, log_picture_file="log.tif")
    set_values(
        notebook, "threshold", threshold_mode="calibrated", lower_limit=5, calibration_filter="crop_",
        run_calibration=True, bailout_max_spots=100000,
    )
    set_values(notebook, "subpixel", use_subpixel=True)
    set_values(notebook, "measurements", measure_snr=True, measure_intensity=True)
    work = base / "work"
    work.mkdir()
    executed = run_notebook(notebook, work, base / "out")
    return executed, base, work


def test_calibration_gives_the_median_of_the_images_and_records_it_in_the_settings(calibrated_run):
    executed, base, work = calibrated_run

    # the automatic value of the crop with the same background and lower limit
    auto = default_config({"background": {"radius_px": 6}, "threshold": {"lower_limit": 5}})
    image = io.read_channel(TEST_DATA / f"{CROP_NAME}.tif", "ZCYX", FISH_CHANNEL)
    radius = steps.spot_radius(auto, auto.channels[0])
    filtered = steps.filter_image(auto, auto.channels[0], image, radius["spot_radius_px"])
    value = steps.detect(auto, auto.channels[0], filtered["rna_log"], radius["spot_radius_px"])["threshold"]

    saved = load_config(base / "out" / "settings.yaml")
    assert saved.resolved.thresholds == {FISH_CHANNEL: pytest.approx(value)}
    assert saved.resolved.images == ["crop_a.tif", "crop_b.tif"]
    assert f"Calibrated threshold of channel 2: {value:.1f}, the median of 2 image(s)." in printed(executed, "calibration")
    assert n_pictures(executed, "calibration") == 1
    assert f"Threshold used: {value:.1f} (calibrated)." in printed(executed, "detect")


def test_the_amplified_preset_switches_decomposition_and_clusters_off(calibrated_run):
    executed, base, _ = calibrated_run

    assert printed(executed, "decomposition") == "Decomposition is switched off for this channel.\n"
    assert printed(executed, "clusters") == "Clusters are switched off for this channel.\n"
    assert n_pictures(executed, "decomposition") == 0
    saved = load_config(base / "out" / "settings.yaml")
    channel = saved.channels[0]
    assert not channel.decomposition.enabled and not channel.clusters.enabled
    assert channel.subpixel.enabled
    assert channel.measurements.snr and channel.measurements.intensity
    assert not saved.segmentation.enabled  # cell_results is off
    assert channel.bailout.enabled and channel.bailout.max_spots == 100000


def test_the_settings_and_tables_with_calibration_subpixel_and_measurements(calibrated_run):
    executed, base, _ = calibrated_run

    saved = load_config(base / "out" / "settings.yaml")
    value = saved.resolved.thresholds[FISH_CHANNEL]
    expected = default_config({
        "background": {"radius_px": 6},
        "threshold": {"mode": "calibrated", "lower_limit": 5, "calibration_filter": "crop_"},
        "bailout": {"enabled": True, "max_spots": 100000},
        "decomposition": {"enabled": False},
        "clusters": {"enabled": False},
        "subpixel": {"enabled": True},
        "measurements": {"snr": True, "intensity": True},
    }).with_resolved(["crop_a.tif", "crop_b.tif"], {FISH_CHANNEL: value})
    assert groups(saved) == groups(expected)
    assert_tables(base / "out", expected, "crop_a")
    spots = (base / "out" / f"spots_ch{FISH_CHANNEL}.csv").read_text().split("\n")[0]
    assert {"snr", "log_intensity"} <= set(spots.split(","))
    assert printed(executed, "measurements") == "Measured for each spot: snr, log_intensity\n"
    assert_everything_ran(executed)


def test_the_log_picture_is_saved_as_a_tiff_with_the_pixel_size(calibrated_run):
    _, _, work = calibrated_run

    with tifffile.TiffFile(work / "log.tif") as tif:
        assert tif.series[0].shape == (384, 384)
        assert tif.series[0].dtype == np.float32
    assert io.get_image_info(work / "log.tif").voxel_size_x == pytest.approx(65)


# ---------------------------------------------------------------------------
# Values replaced: an automatic threshold, and a second channel after the first
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def two_channel_run(committed, tmp_path_factory):
    base = tmp_path_factory.mktemp("two_channels")
    notebook = copy.deepcopy(committed)
    # the first channel has the values of the test kit's settings file (the old v1 run)
    set_values(notebook, "source", folder=str(TEST_DATA))
    set_values(notebook, "image", show_previews=False)
    set_values(notebook, "background", background_method="tophat")
    set_values(notebook, "threshold", threshold_mode="manual", threshold_value=18)
    set_values(notebook, "clusters", cluster_radius_nm=600, cluster_min_spots=12)
    # the second is channel 0, with the defaults, an automatic threshold with a lower limit, amplified FISH
    repeat_for_channel(notebook, {
        "channel": {"channel_index": 0, "channel_name": "DAPI", "assay_type": "amplified"},
        "background": {"background_method": "rolling_ball", "background_radius_px": 8},
        "threshold": {"threshold_mode": "auto", "threshold_value": None, "lower_limit": 10},
        "clusters": {"cluster_radius_nm": 500, "cluster_min_spots": 4},
    })
    # the first channel's pictures, followed before the second channel is read and looked for after it
    insert_before(notebook, "channel-again", """
import weakref
first_channel = [weakref.ref(item) for item in (image, filtered["rna"], filtered["rna_log"])]
""")
    insert_after(notebook, "channel-again", "print([reference() is None for reference in first_channel], filtered is None)")
    executed = run_notebook(notebook, base, base / "out")
    return executed, base / "out"


def test_a_second_channel_tuned_after_the_first_gives_a_config_with_two_channels(two_channel_run):
    executed, out = two_channel_run

    saved = load_config(out / "settings.yaml")
    assert [channel.index for channel in saved.channels] == [2, 0]
    first, second = saved.channels
    assert (first.name, first.threshold.mode, first.threshold.value) == ("jim-exon", "manual", 18)
    assert first.decomposition.enabled and first.clusters.enabled
    assert (second.name, second.threshold.mode, second.threshold.lower_limit) == ("DAPI", "auto", 10)
    assert not second.decomposition.enabled and not second.clusters.enabled
    assert (first.background.method, second.background.method) == ("tophat", "rolling_ball")
    assert (first.background.radius_px, second.background.radius_px) == (5, 8)
    assert saved.image.axes == "ZCYX" and saved.image.voxel_size_nm.yx == 65
    assert_everything_ran(executed)


def test_the_first_channel_with_the_kits_values_gives_the_kits_settings_and_numbers(two_channel_run):
    executed, out = two_channel_run

    # the settings file of the test kit, which reproduces the v1 run: image, microscope and the channel
    kit = load_config(TEST_DATA / f"{CROP_NAME}_config.yaml").to_dict()
    saved = load_config(out / "settings.yaml").to_dict()
    assert saved["image"] == kit["image"]
    assert saved["microscope"] == kit["microscope"]
    assert saved["channels"][0] == kit["channels"][0]
    # its spots and clusters are those of the steps for that file, and of the v1 run's numbers
    assert_tables(out, reference_config(), CROP_NAME, channel_index=2)
    assert "Threshold used: 18.0 (manual)." in printed(executed, "detect")
    assert "473 spots found." in printed(executed, "detect")
    assert "The automatic threshold of this image would be 13.0." in printed(executed, "detect")
    assert "Spots before decomposition: 473; after: 692." in printed(executed, "decomposition")
    assert "6 clusters, holding 94 of the 692 spots." in printed(executed, "clusters")


def test_each_channel_of_the_run_gives_the_tables_of_the_steps(two_channel_run):
    _, out = two_channel_run

    second = default_config({
        "index": 0, "name": "DAPI",
        "background": {"radius_px": 8},
        "threshold": {"lower_limit": 10},
        "decomposition": {"enabled": False},
        "clusters": {"enabled": False},
    })
    assert_tables(out, second, CROP_NAME, channel_index=0)


def test_the_threshold_used_is_shown_for_each_channel(two_channel_run):
    executed, _ = two_channel_run

    assert "(automatic)." in printed(executed, "detect-again")
    assert printed(executed, "previews") == "Previews are switched off.\n"


def test_only_one_channel_is_in_memory_when_the_next_is_read(two_channel_run):
    executed, _ = two_channel_run

    # the first channel's picture and its filtered copies are gone
    assert printed(executed, "added-after-channel-again") == "[True, True, True] True\n"


def test_the_second_channel_is_read_and_its_settings_written_while_the_first_stay(two_channel_run):
    executed, _ = two_channel_run

    assert "Channel 0 read:" in printed(executed, "channel-again")
    assert "Spots before decomposition" in printed(executed, "decomposition")
    assert printed(executed, "decomposition-again") == "Decomposition is switched off for this channel.\n"


# ---------------------------------------------------------------------------
# Values that cannot be used
# ---------------------------------------------------------------------------


def run_with_a_bad_value(committed, tmp_path, step, stops_in, **assignments):
    """Run the notebook with a value that cannot be used, up to the cell that finds out.

    Returns what that cell wrote to the error stream, and the error nbclient raised for it.
    """
    notebook = copy.deepcopy(committed)
    set_values(notebook, "source", folder=str(TEST_DATA))
    set_values(notebook, step, **assignments)
    with pytest.raises(CellExecutionError) as stopped:
        run_notebook(notebook, tmp_path, tmp_path / "out")
    # the same run, up to the cell that stops, to see what the user sees
    stop = next(i for i, cell in enumerate(notebook.cells) if cell.id == stops_in)
    notebook.cells = notebook.cells[:stop + 1]
    NotebookClient(
        notebook, kernel_name="python3", allow_errors=True, resources={"metadata": {"path": str(tmp_path)}},
    ).execute()
    outputs = notebook.cells[-1].outputs
    assert [out.output_type for out in outputs] == ["stream"]  # no traceback
    return outputs[0], stopped.value


def test_a_threshold_mode_that_does_not_exist_stops_with_the_packages_plain_message(committed, tmp_path):
    shown, error = run_with_a_bad_value(
        committed, tmp_path, "threshold", "threshold-write", threshold_mode="automatic",
    )

    assert error.ename == "ConfigError"
    assert shown.name == "stderr"
    assert shown.text == (
        "Problem: `channels[0].threshold.mode` must be one of `manual`, `auto` or `calibrated` "
        "(found `automatic`).\n"
    )


def test_a_layout_that_does_not_fit_the_image_stops_with_a_plain_message(committed, tmp_path):
    shown, error = run_with_a_bad_value(committed, tmp_path, "image", "previews", layout="ZYX")

    assert error.ename == "ImageReadError"
    assert shown.text == (
        "Problem: sypN_DAPI_Phal_jim-exon_crop.tif: the file has 4 axes (11 \u00d7 3 \u00d7 384 \u00d7 384) "
        "but the layout ZYX needs 3\n"
    )


def test_a_manual_threshold_without_a_value_is_refused(committed, tmp_path):
    shown, _ = run_with_a_bad_value(
        committed, tmp_path, "threshold", "threshold-write", threshold_mode="manual",
    )

    assert "`channels[0].threshold.value` is needed when `mode` is `manual`" in shown.text


def test_a_calibrated_threshold_that_was_not_calibrated_says_so(committed, tmp_path):
    shown, error = run_with_a_bad_value(
        committed, tmp_path, "threshold", "detect", threshold_mode="calibrated", calibration_filter="crop",
    )

    assert error.ename == "ChannelError"
    assert shown.text == (
        "Problem: no calibrated threshold for channel 2: the calibration has not been run or gave no value\n"
    )


# ---------------------------------------------------------------------------
# OMERO, with a stand-in for the server
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def omero_run(committed, tmp_path_factory):
    pytest.importorskip("Ice")
    pytest.importorskip("omero.gateway")
    base = tmp_path_factory.mktemp("omero")
    (base / "omero_stand_in.py").write_text(OMERO_STAND_IN.format(
        tests=str(Path(__file__).resolve().parent), crop=str(TEST_DATA / f"{CROP_NAME}.tif"),
        image_id=OMERO_IMAGE_ID, image_name=OMERO_IMAGE_NAME,
    ), encoding="utf-8")
    notebook = copy.deepcopy(committed)
    set_values(notebook, "source", image_source="omero", omero_username="someone", omero_image_id=OMERO_IMAGE_ID)
    set_values(notebook, "threshold", run_calibration=True)
    insert_before(notebook, "omero-login", "import omero_stand_in\nomero_stand_in.install()")
    work = base / "work"
    work.mkdir()
    shutil.copy(base / "omero_stand_in.py", work)
    executed = run_notebook(notebook, work, base / "out")
    return executed, base, work


def test_an_omero_image_runs_through_the_notebook(omero_run):
    executed, base, _ = omero_run

    name = io.omero_output_name(OMERO_IMAGE_ID, OMERO_IMAGE_NAME)
    assert_everything_ran(executed)
    assert "Image: sypN_DAPI_Phal_jim-exon_crop.tif (image ID 1234)" in printed(executed, "image-info")
    assert "Channels: 0 ch0, 1 ch1, 2 ch2" in printed(executed, "image-info")
    assert groups(load_config(base / "out" / "settings.yaml")) == groups(default_config())
    assert_tables(base / "out", default_config(), name)
    assert n_pictures(executed, "previews") == 1


def test_the_omero_log_in_asks_for_the_password_and_the_session_is_closed_at_the_end(omero_run):
    _, base, work = omero_run

    login = json.loads((work / "login.json").read_text())
    # no password is passed in, so that the notebook's own password box asks for it
    assert login == {"username": "someone", "host": "10.34.168.89", "port": 4064, "password_given": False}
    assert (work / "closed.txt").read_text() == "closed"
    saved_text = (base / "out" / "settings.yaml").read_text()
    assert "someone" not in saved_text


def test_calibration_is_left_to_the_batch_for_omero_images(omero_run):
    executed, _, _ = omero_run

    assert printed(executed, "calibration").startswith("Calibration here needs images in a local folder.")
    assert printed(executed, "list-images") == "The image comes from OMERO, so there is no list of local images.\n"
