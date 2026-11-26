"""Tests for the functions the Optimise notebook calls in its later steps: calibration
over several images, segmentation of one image with Cellpose or from its label file,
the Cellpose QC figure, the final QC, and the settings file saved for a batch run.

Each function is tested alone and against what the batch itself does with the same
settings. Cellpose is replaced by the stand-in model of tests/cellpose_standin.py,
except in the tests marked `cellpose`, which use the real model (skipped when the
model file is missing). OMERO is replaced by stand-ins; no server is contacted.
"""

import numpy as np
import pandas as pd
import pytest
import tifffile
from matplotlib.figure import Figure

from bigfish_pypeline import batch, cli, io, outputs, qc, segmentation, steps
from bigfish_pypeline.config import ConfigError, batch_settings, load_config, save_config
from cellpose_standin import StandInModel
from conftest import CROP_NAME, FISH_CHANNEL, TEST_DATA
from test_batch_cellpose import run_cellpose, with_cellpose
from test_batch_run import FakeConn, generated_image, local_config, log_text, with_changes
from test_save_image import (  # noqa: F401 (omero_stand_ins is a fixture)
    CULTURE,
    CULTURE_NAME,
    QC_OFF,
    assert_same_results,
    batch_of_one,
    omero_settings,
    omero_stand_ins,
)

CROP = TEST_DATA / f"{CROP_NAME}.tif"
CROP_LABELS = TEST_DATA / f"{CROP_NAME}_seglabels.tif"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def kit_config(output=None, change=None):
    """The tissue crop's settings (label file in the test kit), with its output folder set."""
    def edit(data):
        if output is not None:
            data["run"]["output_folder"] = str(output)
        if change is not None:
            change(data)

    return with_changes(load_config(TEST_DATA / f"{CROP_NAME}_config.yaml"), edit)


def channel_steps(config, channel, image_name, image, masks):
    """Steps 2 to 8 and 10 of one channel, one call at a time, as the notebook makes them."""
    radius = steps.spot_radius(config, channel)
    filtered = steps.filter_image(config, channel, image, radius["spot_radius_px"])
    detected = steps.detect(config, channel, filtered["rna_log"], radius["spot_radius_px"])
    decomposed = steps.decompose(config, channel, image_name, filtered["rna"], detected["spots"],
                                 radius["spot_radius_nm"])
    spots = decomposed["spots_post_decomposition"]
    fitted = steps.fit_subpixel(config, channel, filtered["rna"], spots, radius["spot_radius_nm"])
    clustered = steps.find_clusters(config, channel, spots, fitted["spots_subpixel"])
    measured = steps.measure(config, channel, filtered["rna"], filtered["rna_log"], spots,
                             radius["spot_radius_px"])
    assigned = steps.assign_to_cells(config, channel, masks, spots, clustered)
    return steps.make_tables(config, channel, image_name, spots, fitted, clustered, measured, assigned)


def assert_tables_saved(config, image_name, tables_by_channel, run_folder, tmp_path):
    """The tables shown in memory, written as the batch writes them, equal byte for byte
    those saved in the run folder's `per_image/` folder."""
    shown = tmp_path / "shown"
    (shown / outputs.PER_IMAGE_FOLDER_NAME).mkdir(parents=True)
    rows = pd.read_csv(outputs.per_image_path(run_folder, image_name, "images"))
    has_cells = any(tables["cells"] is not None for tables in tables_by_channel.values())
    outputs.write_image_tables(
        shown, image_name, rows,
        spots=[tables["spots"] for tables in tables_by_channel.values()],
        clusters=([tables["clusters"] for tables in tables_by_channel.values()]
                  if batch.run_has_clusters(config) else None),
        cells=[tables["cells"] for tables in tables_by_channel.values()] if has_cells else None,
    )
    for kind in ("spots", "clusters", "cells"):
        saved = outputs.per_image_path(run_folder, image_name, kind)
        written = outputs.per_image_path(shown, image_name, kind)
        assert saved.is_file() == written.is_file(), kind
        if saved.is_file():
            assert written.read_bytes() == saved.read_bytes(), kind


def recorder(monkeypatch, module, name):
    """Replace module.name by a function that records its arguments and then calls it."""
    original = getattr(module, name)
    calls = []

    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, record)
    return calls


# ---------------------------------------------------------------------------
# Calibration over several images
# ---------------------------------------------------------------------------


def calibration_config(folder, output):
    return local_config(
        folder, output, workers=1, qc=True,
        channels=[{"index": 0, "name": "exon",
                   "threshold": {"mode": "calibrated", "calibration_filter": "cal", "lower_limit": 5}},
                  {"index": 1}],
    )


@pytest.fixture(scope="module")
def calibration_folder(tmp_path_factory):
    """Images whose names contain `cal`: two with spots, a blank one and one that cannot be read;
    and one more image that is not used for the calibration."""
    folder = tmp_path_factory.mktemp("calibration_input")
    generated_image(folder / "cal_1.tif", seed=10, amplitude=400)
    generated_image(folder / "cal_2.tif", seed=20, amplitude=800)
    generated_image(folder / "cal_3_blank.tif", blank=True)
    (folder / "cal_4_broken.tif").write_bytes(b"not a TIFF file")
    generated_image(folder / "other.tif", seed=30)
    return folder


@pytest.fixture(scope="module")
def calibration_batch(calibration_folder, tmp_path_factory):
    config = calibration_config(calibration_folder, tmp_path_factory.mktemp("calibration_output"))
    result = batch.run_batch(config)
    assert result.status == "finished", result.message
    return config, result


@pytest.fixture(scope="module")
def calibration(calibration_folder, calibration_batch):
    config, _ = calibration_batch
    return batch.calibrate_images(config, 0, io.list_images(calibration_folder, "cal"))


def test_calibration_equals_the_batch(calibration, calibration_batch, tmp_path):
    _, result = calibration_batch
    written = outputs.write_calibration(tmp_path, calibration.table)
    assert written.read_bytes() == (result.run_folder / "calibration.csv").read_bytes()
    run_config = load_config(result.run_folder / "run_config.yaml")
    assert run_config.resolved.thresholds == {0: calibration.threshold}


def test_calibration_table_and_value(calibration, calibration_batch, calibration_folder):
    config, _ = calibration_batch
    table = calibration.table
    assert list(table["image"]) == ["cal_1", "cal_2", "cal_3_blank", "cal_4_broken"]
    assert list(table["used"]) == [True, True, False, False]
    assert table["reason"].iloc[2] == batch.NO_AUTO_THRESHOLD_REASON
    assert table["reason"].iloc[3].startswith("cal_4_broken.tif")
    expected = [batch.calibration_threshold(config, name, calibration_folder / f"{name}.tif", 0)["threshold"]
                for name in ("cal_1", "cal_2")]
    assert calibration.threshold == float(np.median(expected))
    assert calibration.reason is None
    assert calibration.channel == 0
    assert calibration.images == ["cal_1.tif", "cal_2.tif", "cal_3_blank.tif", "cal_4_broken.tif"]
    assert calibration.lower_limit == 5 and calibration.channel_name == "exon"


def test_calibration_into_the_config(calibration, calibration_batch, calibration_folder):
    config, _ = calibration_batch
    calibrated = calibration.with_threshold(config)
    assert calibrated.resolved.thresholds == {0: calibration.threshold}
    assert calibrated.resolved.images == calibration.images
    # the steps then use it
    channel = calibrated.channel(0)
    assert steps.threshold_settings(calibrated, channel) == (calibration.threshold, None)
    # a threshold of another channel already there is kept
    earlier = config.with_resolved([], {1: 33.0})
    assert calibration.with_threshold(earlier).resolved.thresholds == {1: 33.0, 0: calibration.threshold}


def test_calibration_plot(calibration):
    figure = calibration.plot()
    assert isinstance(figure, Figure)
    assert len(figure.axes) >= 1


def test_calibration_shows_each_image(calibration_batch, calibration_folder):
    config, _ = calibration_batch
    shown = []
    batch.calibrate_images(config, 0, [calibration_folder / "cal_1.tif", calibration_folder / "cal_3_blank.tif"],
                           show=shown.append)
    assert shown[0].startswith("cal_1, channel 0 (calibration): automatic threshold ")
    assert shown[1] == f"cal_3_blank, channel 0 (calibration): no value ({batch.NO_AUTO_THRESHOLD_REASON})"


def test_calibration_without_a_usable_value(tmp_path):
    """No image gives a value: as in the batch, every image is a row, and there is no threshold."""
    folder = tmp_path / "input"
    folder.mkdir()
    generated_image(folder / "cal_blank.tif", blank=True)
    generated_image(folder / "other.tif", seed=3)
    config = calibration_config(folder, tmp_path / "out")
    found = batch.calibrate_images(config, 0, io.list_images(folder, "cal"))
    assert found.threshold is None
    assert found.reason == (
        "No calibrated threshold for channel 0: none of the calibration images gave a usable automatic "
        "threshold (see the table). Change the calibration images or the threshold settings and "
        "calibrate again."
    )
    result = batch.run_batch(config)
    assert result.status == "stopped"
    written = outputs.write_calibration(tmp_path, found.table)
    assert written.read_bytes() == (result.run_folder / "calibration.csv").read_bytes()
    with pytest.raises(batch.BatchError) as error:
        found.with_threshold(config)
    assert str(error.value) == found.reason
    assert isinstance(found.plot(), Figure)


def test_calibration_without_images(calibration_batch):
    config, _ = calibration_batch
    with pytest.raises(batch.BatchError) as error:
        batch.calibrate_images(config, 0, [])
    assert str(error.value) == "No calibration images were given for channel 0."


def test_calibration_of_a_channel_not_in_the_settings(calibration_batch, calibration_folder):
    config, _ = calibration_batch
    with pytest.raises(ConfigError, match="Channel 5 is not in the settings"):
        batch.calibrate_images(config, 5, [calibration_folder / "cal_1.tif"])


def test_calibration_of_omero_images(tmp_path, omero_stand_ins):
    conn = FakeConn([(123, "a.tif"), (124, "b.tif")])
    config = with_changes(omero_settings(tmp_path / "out"),
                          lambda data: data["run"]["input"].update(source="local"))
    before = dict(batch._omero)
    found = batch.calibrate_images(config, 0, [123, 124], omero_conn=conn)
    assert list(found.table["image"]) == ["123_a", "124_b"]
    assert found.images == ["123_a", "124_b"]
    assert omero_stand_ins and all(read is conn for read in omero_stand_ins)
    assert batch._omero == before
    assert not conn.closed


def test_calibration_of_an_omero_image_not_on_the_server(tmp_path, omero_stand_ins):
    with pytest.raises(batch.BatchError) as error:
        batch.calibrate_images(omero_settings(tmp_path / "out"), 0, [999], omero_conn=FakeConn([(123, "a.tif")]))
    assert "999" in str(error.value) and not str(error.value).startswith("ValueError")
    assert omero_stand_ins == []


def test_calibration_of_omero_images_needs_a_connection(tmp_path, omero_stand_ins):
    with pytest.raises(batch.BatchError, match="need the OMERO connection that is already logged in"):
        batch.calibrate_images(omero_settings(tmp_path / "out"), 0, [123])


# ---------------------------------------------------------------------------
# Segmentation of one image with Cellpose (stand-in model)
# ---------------------------------------------------------------------------


@pytest.fixture
def cellpose_image(tmp_path):
    folder = tmp_path / "input"
    folder.mkdir()
    image = generated_image(folder / "cells.tif", shape=(8, 64, 64), n_channels=2)
    config = with_cellpose(local_config(folder, tmp_path / "out", qc=True), channel=1)
    config = with_changes(config, lambda data: data["segmentation"].update(
        z_planes={"first": 2, "last": 5}, median_px=3, cellpose={"diameter": 30, "flow_threshold": 0.5}))
    return config, image


def segmentation_channel(config, image):
    return io.read_channel(image, config.image.axes, config.segmentation.channel)


def test_segment_pretreats_and_segments_as_set(cellpose_image):
    config, image = cellpose_image
    model = StandInModel(n_cells=3)
    found = steps.segment(config, segmentation_channel(config, image), model, "cells")
    settings = steps.pretreatment_settings(config)
    expected = segmentation.pretreat_channel(segmentation_channel(config, image), **settings)
    [call] = model.calls
    np.testing.assert_array_equal(call["x"], expected.astype(np.float32))
    assert call["diameter"] == 30 and call["flow_threshold"] == 0.5
    assert call["max_size_fraction"] == config.segmentation.cellpose.max_size_fraction
    assert found["n_cells"] == 3
    assert found["masks"].shape == (64, 64)
    assert found["pretreatment"] == "max projection of planes 2–5 | rolling ball 200 px | median 3 px"
    assert set(found) >= {"masks", "model_input", "flows", "n_cells", "seconds", "warning"}


def test_segment_refuses_planes_the_image_lacks(cellpose_image):
    config, image = cellpose_image
    config = with_changes(config, lambda data: data["segmentation"].update(z_planes={"first": 2, "last": 20}))
    model = StandInModel()
    with pytest.raises(io.ImageReadError) as error:
        steps.segment(config, segmentation_channel(config, image), model, "cells.tif")
    assert str(error.value) == (
        "cells.tif: the image has 8 planes (numbered 0 to 7), so plane 20 does not exist "
        "(`segmentation.z_planes`)"
    )
    assert str(error.value) == batch._plane_problem(config, "cells.tif", 8)
    assert model.calls == []


def test_segment_passes_on_cellpose_failures(cellpose_image):
    config, image = cellpose_image
    with pytest.raises(segmentation.SegmentationError, match="Cellpose could not segment the image"):
        steps.segment(config, segmentation_channel(config, image), StandInModel(error=RuntimeError("boom")))


def test_batch_segments_through_the_same_function(cellpose_image, monkeypatch):
    config, image = cellpose_image
    calls = recorder(monkeypatch, steps, "segment")
    model = StandInModel(n_cells=2)
    result = run_cellpose(batch_of_one(config, image), model)
    assert result.status == "finished", result.message
    assert len(calls) == 1
    args, _ = calls[0]
    assert args[2] is model and args[3] == "cells.tif"
    found = steps.segment(config, segmentation_channel(config, image), StandInModel(n_cells=2))
    labels = tifffile.imread(result.run_folder / "labels" / "cells_seglabels.tif")
    np.testing.assert_array_equal(labels, found["masks"])
    assert found["pretreatment"] in log_text(result.run_folder)


def test_cellpose_qc_settings(cellpose_image):
    config, _ = cellpose_image
    config = with_changes(config, lambda data: data["channels"][1].update(name="cell mask"))
    assert steps.cellpose_qc_settings(config) == {
        "channel": 1, "channel_name": "cell mask",
        "pretreatment": "max projection of planes 2–5 | rolling ball 200 px | median 3 px",
        "diameter": 30,
    }
    config = with_changes(config, lambda data: data["segmentation"].update(channel=3))
    assert steps.cellpose_qc_settings(config)["channel_name"] is None


def test_cellpose_qc_figure_has_the_batchs_title(cellpose_image, monkeypatch):
    config, image = cellpose_image
    found = steps.segment(config, segmentation_channel(config, image), StandInModel(n_cells=2), "cells")
    figure = steps.draw_cellpose_qc(config, "cells", found)
    assert isinstance(figure, Figure)
    assert len(figure.axes) == 4

    titles = []
    original = qc.draw_cellpose_qc

    def record(*args, **kwargs):
        drawn = original(*args, **kwargs)
        titles.append(drawn._suptitle.get_text())
        return drawn

    monkeypatch.setattr(qc, "draw_cellpose_qc", record)
    saved = batch.save_image_results(config, image, cellpose_result=found)
    assert saved.status == "finished", saved.message
    assert titles == [figure._suptitle.get_text()]
    assert "cells | channel 1 | max projection of planes 2–5" in titles[0]


# ---------------------------------------------------------------------------
# Label files
# ---------------------------------------------------------------------------


def test_read_labels_from_the_config(tmp_path):
    masks = steps.read_labels(kit_config(), CROP_NAME, (384, 384))
    np.testing.assert_array_equal(masks, tifffile.imread(CROP_LABELS))
    assert masks.dtype == np.uint32
    masks, data, details = steps.read_labels_contents(kit_config(), CROP_NAME, (384, 384))
    assert data == CROP_LABELS.read_bytes()
    assert details.st_size == len(data)


def test_read_labels_from_another_folder(tmp_path):
    (tmp_path / f"{CROP_NAME}_seglabels.tif").write_bytes(CROP_LABELS.read_bytes())
    config = kit_config(change=lambda data: data["segmentation"].update(label_folder="/nowhere"))
    masks = steps.read_labels(config, CROP_NAME, (384, 384), label_folder=tmp_path)
    np.testing.assert_array_equal(masks, tifffile.imread(CROP_LABELS))


def test_read_labels_without_a_label_folder(tmp_path):
    config = kit_config(change=lambda data: data["segmentation"].update(enabled=False, label_folder=""))
    with pytest.raises(segmentation.LabelFileError) as error:
        steps.read_labels(config, CROP_NAME, (384, 384))
    assert str(error.value) == "There is no label folder: set `segmentation.label_folder`."
    missing = tmp_path / "missing"
    config = kit_config(change=lambda data: data["segmentation"].update(label_folder=str(missing)))
    with pytest.raises(segmentation.LabelFileError) as error:
        steps.read_labels(config, CROP_NAME, (384, 384))
    assert str(error.value) == f"The label folder {missing} does not exist (`segmentation.label_folder`)."


def write_labels(folder, labels):
    folder.mkdir(exist_ok=True)
    tifffile.imwrite(folder / f"{CROP_NAME}_seglabels.tif", labels)


@pytest.mark.parametrize("problem", ["missing", "other size", "negative", "not whole", "3d"])
def test_label_file_problems_have_the_batchs_messages(tmp_path, problem):
    folder = tmp_path / "labels"
    folder.mkdir()
    labels = tifffile.imread(CROP_LABELS).astype(np.int32)
    if problem == "other size":
        write_labels(folder, labels[:300])
    elif problem == "negative":
        labels[0, 0] = -1
        write_labels(folder, labels)
    elif problem == "not whole":
        write_labels(folder, labels.astype(np.float32) + 0.5)
    elif problem == "3d":
        write_labels(folder, np.stack([labels, labels]))
    config = kit_config(change=lambda data: (data["segmentation"].update(label_folder=str(folder)),
                                             data["outputs"].update(qc=dict(QC_OFF))))
    with pytest.raises(segmentation.LabelFileError) as error:
        steps.read_labels(config, CROP_NAME, (384, 384))
    summary = batch.process_image(config, CROP_NAME, CROP, tmp_path / "run", label_folder=folder)
    [row] = summary["rows"]
    assert row["segmentation_status"] == "no_labels"
    assert f"no cell results: {error.value}" in row["warnings"]


def test_process_image_reads_labels_through_the_same_function(tmp_path, monkeypatch):
    calls = recorder(monkeypatch, steps, "read_labels_contents")
    config = kit_config(change=lambda data: data["outputs"].update(qc=dict(QC_OFF)))
    summary = batch.process_image(config, CROP_NAME, CROP, tmp_path / "run", label_folder=TEST_DATA)
    assert [row["segmentation_status"] for row in summary["rows"]] == ["done"]
    assert len(calls) == 1
    args, _ = calls[0]
    assert args[1] == CROP_NAME and tuple(args[2]) == (384, 384) and args[3] == TEST_DATA


# ---------------------------------------------------------------------------
# Final QC
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("final, change", [
    ("png", None),
    ("html", None),
    ("png", lambda data: data["channels"][0]["clusters"].update(enabled=False)),
    ("png", lambda data: data["segmentation"].update(drop_border_cells=True)),
], ids=["png", "html", "clusters-off", "drop-border-cells"])
def test_final_qc_drawn_from_what_the_batch_uses(tmp_path, monkeypatch, final, change):
    def edit(data):
        data["outputs"]["qc"] = dict(QC_OFF, final=final)
        if change is not None:
            change(data)

    config = kit_config(tmp_path / "out", edit)
    channel = config.channel(FISH_CHANNEL)
    image = io.read_channel(CROP, config.image.axes, FISH_CHANNEL)
    masks = steps.read_labels(config, CROP_NAME, image.shape[-2:])
    tables = channel_steps(config, channel, CROP_NAME, image, masks)

    figure = steps.draw_final_qc(config, channel, CROP_NAME, image, tables, masks)
    drawn = recorder(monkeypatch, qc, "draw_final_html" if final == "html" else "draw_final_qc")
    saved = batch.save_image_results(config, CROP)
    assert saved.status == "finished", saved.message
    [(args, kwargs)] = drawn
    picture, spots, clusters, cells, labels, image_name, index, channel_name = args
    np.testing.assert_array_equal(picture, image.max(axis=0))
    shown_spots, shown_clusters, shown_cells = steps.final_qc_tables(channel, tables)
    pd.testing.assert_frame_equal(spots, shown_spots)
    pd.testing.assert_frame_equal(cells, shown_cells)
    if channel.clusters.enabled:
        pd.testing.assert_frame_equal(clusters, shown_clusters)
    else:
        assert clusters is None and shown_clusters is None
    np.testing.assert_array_equal(labels, masks)
    assert (image_name, index, channel_name) == (CROP_NAME, FISH_CHANNEL, channel.name)

    if final == "html":
        assert figure.layout.title.text == drawn_title(args, kwargs, html=True)
    else:
        assert isinstance(figure, Figure)
        assert figure._suptitle.get_text() == drawn_title(args, kwargs)


def drawn_title(args, kwargs, html=False):
    if html:
        return qc.draw_final_html(*args, **kwargs).layout.title.text
    return qc.draw_final_qc(*args, **kwargs)._suptitle.get_text()


def test_final_qc_kind_follows_the_settings_or_the_caller():
    config = kit_config(change=lambda data: data["outputs"]["qc"].update(final="none"))
    channel = config.channel(FISH_CHANNEL)
    image = io.read_channel(CROP, config.image.axes, FISH_CHANNEL)
    tables = channel_steps(config, channel, CROP_NAME, image, None)
    assert isinstance(steps.draw_final_qc(config, channel, CROP_NAME, image, tables, None), Figure)
    figure = steps.draw_final_qc(config, channel, CROP_NAME, image, tables, None, interactive=True)
    assert not isinstance(figure, Figure) and "no cells" in figure.layout.title.text.lower()


# ---------------------------------------------------------------------------
# The settings file for a batch
# ---------------------------------------------------------------------------


def test_batch_settings_run_every_image_and_calibrate_again(calibration, calibration_batch, calibration_folder,
                                                            tmp_path, monkeypatch):
    config, first = calibration_batch
    calibrated = calibration.with_threshold(config)
    output = tmp_path / "results"
    monkeypatch.chdir(tmp_path)
    settings = batch_settings(calibrated, input_folder=calibration_folder, filter="", output_folder="results")
    assert settings.resolved is None
    assert settings.run.input.source == "local"
    assert settings.run.input.folder == str(calibration_folder)
    assert settings.run.output_folder == str(output)
    assert settings.run.workers == "auto"
    assert settings.channels == calibrated.channels

    path = tmp_path / "settings" / "my_settings.yaml"
    save_config(settings, path)
    assert cli.command_line(["batch", str(path)]) == f"bigfish-pypeline batch {path}"
    loaded = load_config(path)
    assert loaded == settings
    loaded = with_changes(loaded, lambda data: data["run"].update(workers=1))
    result = batch.run_batch(loaded)
    assert result.status == "finished", result.message
    images = pd.read_csv(result.run_folder / "images.csv")
    assert sorted(set(images["image"])) == ["cal_1", "cal_2", "cal_3_blank", "cal_4_broken", "other"]
    assert (result.run_folder / "calibration.csv").read_bytes() == (first.run_folder / "calibration.csv").read_bytes()
    assert load_config(result.run_folder / "run_config.yaml").resolved.thresholds == {0: calibration.threshold}


def test_batch_settings_defaults_and_full_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(TEST_DATA.parent)
    config = kit_config(change=lambda data: data["segmentation"].update(label_folder="data"))
    config = config.with_config_folder(None).with_resolved([f"{CROP_NAME}.tif"], {})
    settings = batch_settings(config, input_folder="data")
    assert settings.resolved is None
    assert settings.run.input.folder == str(TEST_DATA)
    assert settings.segmentation.label_folder == str(TEST_DATA)
    assert settings.run.input.filter == ""
    assert settings.run.output_folder == ""
    assert settings.run.workers == "auto"
    assert settings.run.input.extension == config.run.input.extension
    assert batch_settings(config, input_folder="data", extension=".tiff", workers=3).run.workers == 3


def test_batch_settings_for_omero():
    config = kit_config()
    settings = batch_settings(config, dataset_id=5)
    assert settings.run.input.source == "omero"
    assert settings.run.input.omero.dataset_id == 5 and settings.run.input.omero.image_ids == []
    settings = batch_settings(config, image_ids=[3, "4"])
    assert settings.run.input.omero.dataset_id is None and settings.run.input.omero.image_ids == [3, 4]
    with pytest.raises(ConfigError, match="not both"):
        batch_settings(config, dataset_id=5, image_ids=[3])


def test_batch_settings_need_an_input_folder():
    with pytest.raises(ConfigError) as error:
        batch_settings(kit_config())
    assert error.value.messages == ["Give the input folder: the folder holding the images to analyse."]
    with pytest.raises(ConfigError, match="workers"):
        batch_settings(kit_config(), input_folder=TEST_DATA, workers="many")


# ---------------------------------------------------------------------------
# The notebook's chain, from the steps of a channel to the saved results
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cells", [True, False], ids=["label-file", "no-cells"])
def test_notebook_chain_with_label_files(tmp_path, cells):
    config = kit_config(tmp_path / "out", lambda data: (
        data["segmentation"].update(enabled=cells),
        data["outputs"]["qc"].update(final="png"),
    ))
    channel = config.channel(FISH_CHANNEL)
    image = io.read_channel(CROP, config.image.axes, FISH_CHANNEL)
    masks = steps.read_labels(config, CROP_NAME, image.shape[-2:]) if cells else None
    tables = channel_steps(config, channel, CROP_NAME, image, masks)
    figure = steps.draw_final_qc(config, channel, CROP_NAME, image, tables, masks)
    assert isinstance(figure, Figure)

    saved = batch.save_image_results(config, CROP, command="notebook test")
    assert saved.status == "finished", saved.message
    assert_tables_saved(config, CROP_NAME, {FISH_CHANNEL: tables}, saved.run_folder, tmp_path)
    assert (tables["cells"] is not None) == cells


def test_notebook_chain_with_cellpose(cellpose_image, tmp_path):
    config, image = cellpose_image
    name = io.output_name(image)
    model = StandInModel(n_cells=3)
    found = steps.segment(config, segmentation_channel(config, image), model, name)
    assert isinstance(steps.draw_cellpose_qc(config, name, found), Figure)
    masks = found["masks"]
    shown = {}
    for channel in config.channels:
        channel_image = io.read_channel(image, config.image.axes, channel.index)
        shown[channel.index] = channel_steps(config, channel, name, channel_image, masks)
        steps.draw_final_qc(config, channel, name, channel_image, shown[channel.index], masks)

    saved = batch.save_image_results(config, image, cellpose_result=found, cellpose_model=model)
    assert saved.status == "finished", saved.message
    assert len(model.calls) == 1
    labels = tifffile.imread(saved.run_folder / "labels" / f"{name}_seglabels.tif")
    np.testing.assert_array_equal(labels, masks)
    assert_tables_saved(config, name, shown, saved.run_folder, tmp_path)


# ---------------------------------------------------------------------------
# Cultured-cell crop with the real Cellpose model
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def culture(tmp_path_factory):
    base = tmp_path_factory.mktemp("notebook_culture")

    def change(data):
        data["run"]["output_folder"] = str(base / "out")
        data["outputs"]["qc"].update(elbow_plot=False, detection=False, reference_spot=False)

    config = with_changes(load_config(TEST_DATA / f"{CULTURE_NAME}_config.yaml"), change)
    return config, base


@pytest.mark.cellpose
def test_culture_notebook_chain_with_the_real_model(culture, tmp_path):
    config, _ = culture
    torch_before = _torch_threads()
    setup = batch.prepare_cellpose(config)
    try:
        channel_image = io.read_channel(CULTURE, config.image.axes, config.segmentation.channel)
        found = steps.segment(config, channel_image, setup.model, CULTURE_NAME)
        assert found["n_cells"] > 0
        assert isinstance(steps.draw_cellpose_qc(config, CULTURE_NAME, found), Figure)
        channel = config.channels[0]
        image = io.read_channel(CULTURE, config.image.axes, channel.index)
        tables = channel_steps(config, channel, CULTURE_NAME, image, found["masks"])
        assert isinstance(steps.draw_final_qc(config, channel, CULTURE_NAME, image, tables, found["masks"]), Figure)
        saved = batch.save_image_results(config, CULTURE, cellpose_result=found, cellpose_model=setup.model)
    finally:
        setup.release()
        _restore_torch_threads(torch_before)
    assert saved.status == "finished", saved.message
    assert_tables_saved(config, CULTURE_NAME, {channel.index: tables}, saved.run_folder, tmp_path)

    # the same as a batch run that runs Cellpose itself
    result = batch.run_batch(config)
    assert result.status == "finished", result.message
    labels = tifffile.imread(result.run_folder / "labels" / f"{CULTURE_NAME}_seglabels.tif")
    np.testing.assert_array_equal(labels, found["masks"])
    assert_same_results(saved.run_folder, result.run_folder)


def _torch_threads():
    import sys
    torch = sys.modules.get("torch")
    return None if torch is None else torch.get_num_threads()


def _restore_torch_threads(threads):
    if threads is not None:
        import torch
        torch.set_num_threads(threads)
