"""Tests for batch.process_image and batch.calibration_threshold: one image through every step."""

import numpy as np
import pandas as pd
import pytest
import tifffile

from bigfish_pypeline import batch, detection, io, measurements, outputs
from bigfish_pypeline.config import load_config, parse_config
from bigfish_pypeline.decomposition import NO_SPOTS_WARNING
from conftest import CROP_NAME, FISH_CHANNEL, assert_clusters_as_v1
from synthetic import make_image

VOXEL_SIZE = (200, 65, 65)  # nm: z, y, x

# Most tests do not look at QC files, so their configs draw none; the tests that do ask for them with `with_qc`.
QC_OFF = {"elbow_plot": False, "detection": False, "reference_spot": False, "cellpose": False,
          "final": "none"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_tables(run_folder, image):
    """The image's per-image tables that exist, by kind."""
    tables = {}
    for kind in ("spots", "clusters", "cells", "images"):
        path = run_folder / "per_image" / f"{image}_{kind}.csv"
        if path.is_file():
            tables[kind] = pd.read_csv(path, keep_default_na=True)
    return tables


def crop_config(crop_config_path, **channel_changes):
    """The test kit config with some channel settings changed (dotted names)."""
    config = load_config(crop_config_path)
    data = config.to_dict()
    data["outputs"]["qc"] = dict(QC_OFF)
    channel = data["channels"][0]
    for name, value in channel_changes.items():
        group, setting = name.split("__")
        channel[group][setting] = value
    return parse_config(data, config.config_folder)


def run_crop(config, run_folder, crop_path):
    summary = batch.process_image(
        config, CROP_NAME, crop_path, run_folder, label_folder=config.full_label_folder()
    )
    return summary, read_tables(run_folder, CROP_NAME)


def v1_reference(folder):
    return np.load(next(folder.glob("*_bfoutput.npz")))


def check_cells_as_v1(cells, folder, with_clusters=True):
    expected = pd.read_csv(folder / "per_cell_counts.csv")
    assert len(cells) == 44
    np.testing.assert_array_equal(cells["cell_id"], expected["label"])
    np.testing.assert_array_equal(cells["touches_border"], expected["touches_border"])
    np.testing.assert_array_equal(cells["n_spots"], expected["n_spots"])
    if with_clusters:
        for column in ("n_spots_in_clusters", "n_spots_outside_clusters", "n_clusters"):
            np.testing.assert_array_equal(cells[column], expected[column], err_msg=column)


def synthetic_config(axes="ZCYX", voxel_size=None, channels=None, segmentation=None, qc=False):
    """Config for generated images: top-hat background, manual thresholds."""
    if voxel_size is None:
        voxel_size = {"z": 200, "yx": 65} if "Z" in axes else {"yx": 65}
    if channels is None:
        channels = [{"index": 0}]
    full_channels = []
    for channel in channels:
        full = {
            "background": {"method": "tophat", "radius_px": 5},
            "threshold": {"mode": "manual", "value": 50},
        }
        full.update(channel)
        full_channels.append(full)
    data = {
        "config_version": 1,
        "run": {"name": "test", "input": {"source": "local"}},
        "image": {"axes": axes, "voxel_size_nm": voxel_size},
        "channels": full_channels,
    }
    if segmentation is not None:
        data["segmentation"] = segmentation
    if not qc:
        data["outputs"] = {"qc": dict(QC_OFF)}
    return parse_config(data)


def write_image(path, array, axes, voxel_um=(0.2, 0.065, 0.065)):
    """Write an ImageJ TIFF with voxel sizes in its metadata."""
    z, y, x = voxel_um
    metadata = {"axes": axes, "unit": "um"}
    if "Z" in axes:
        metadata["spacing"] = z
    tifffile.imwrite(path, array, imagej=True, metadata=metadata, resolution=(1 / x, 1 / y))
    return path


def stack_channels(channels):
    """ZCYX array from a list of ZYX channels."""
    return np.stack(channels, axis=1)


def write_with_damaged_channel(path, channels, damaged, voxel_um=(0.2, 0.065, 0.065)):
    """A compressed ImageJ TIFF (ZCYX) in which one plane of channel `damaged` cannot be read."""
    z, y, x = voxel_um
    tifffile.imwrite(path, stack_channels(channels), imagej=True, compression="zlib",
                     metadata={"axes": "ZCYX", "unit": "um", "spacing": z}, resolution=(1 / x, 1 / y))
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[damaged]
        start, length = page.dataoffsets[0], page.databytecounts[0]
    data = bytearray(path.read_bytes())
    data[start:start + length] = bytes(length)
    path.write_bytes(bytes(data))
    return path


def row_of(summary, channel):
    rows = [row for row in summary["rows"] if row["channel"] == channel]
    assert len(rows) == 1
    return rows[0]


# ---------------------------------------------------------------------------
# Test kit against v1
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manual18_run(crop_config_path, crop_path, tmp_path_factory):
    config = crop_config(crop_config_path)
    return run_crop(config, tmp_path_factory.mktemp("manual18"), crop_path)


def test_kit_as_configured(manual18_run, crop_reference_folder):
    summary, tables = manual18_run
    folder = crop_reference_folder / "general_manual18_subpixel-off"
    reference = v1_reference(folder)

    spots = tables["spots"]
    expected = reference["spots_post_clustering"]
    assert len(spots) == 692
    np.testing.assert_array_equal(spots[["z_px", "y_px", "x_px", "cluster_id"]].to_numpy(), expected)
    np.testing.assert_array_equal(spots["spot_id"], np.arange(692))
    for axis, size in zip("zyx", VOXEL_SIZE):
        np.testing.assert_array_equal(spots[f"{axis}_nm"], spots[f"{axis}_px"] * size)
    assert "z_sub_px" not in spots.columns
    assert "snr" not in spots.columns

    clusters = tables["clusters"]
    expected_clusters = reference["clusters"]
    assert_clusters_as_v1(clusters[["z_px", "y_px", "x_px", "n_spots", "cluster_id"]].to_numpy(),
                          expected_clusters)
    for axis, size in zip("zyx", VOXEL_SIZE):
        np.testing.assert_allclose(clusters[f"{axis}_nm"], clusters[f"{axis}_px"] * size, rtol=1e-12)

    check_cells_as_v1(tables["cells"], folder)
    assert (tables["cells"]["channel"] == FISH_CHANNEL).all()
    assert (tables["cells"]["channel_name"] == "jim-exon").all()

    images = tables["images"]
    assert len(images) == 1
    row = images.iloc[0]
    assert row["image"] == CROP_NAME
    assert row["channel"] == FISH_CHANNEL
    assert row["channel_name"] == "jim-exon"
    assert row["status"] == "done"
    assert pd.isna(row["reason"])
    assert row["threshold_mode"] == "manual"
    assert row["threshold"] == 18
    assert row["n_spots_detected"] == 473
    assert row["n_spots"] == 692
    assert row["n_clusters"] == 6
    assert row["n_cells"] == 44
    assert row["segmentation_source"] == "label_files"
    assert row["segmentation_status"] == "done"
    assert pd.isna(row["warnings"])
    assert row["runtime_s"] > 0

    assert summary["image"] == CROP_NAME
    assert summary["rows"][0]["status"] == "done"
    assert summary["log_lines"] == []


def test_kit_auto_threshold(crop_config_path, crop_path, crop_reference_folder, tmp_path):
    config = crop_config(crop_config_path, threshold__mode="auto", threshold__value=None)
    summary, tables = run_crop(config, tmp_path, crop_path)
    folder = crop_reference_folder / "general_auto_subpixel-off"
    reference = v1_reference(folder)

    row = row_of(summary, FISH_CHANNEL)
    assert row["status"] == "done"
    assert row["threshold_mode"] == "auto"
    assert row["threshold"] == 13.0
    assert row["n_spots"] == 869
    assert row["n_clusters"] == 6
    np.testing.assert_array_equal(
        tables["spots"][["z_px", "y_px", "x_px", "cluster_id"]].to_numpy(),
        reference["spots_post_clustering"],
    )
    assert_clusters_as_v1(
        tables["clusters"][["z_px", "y_px", "x_px", "n_spots", "cluster_id"]].to_numpy(),
        reference["clusters"],
    )
    check_cells_as_v1(tables["cells"], folder)


@pytest.mark.parametrize("mode, name, n_spots", [
    ("manual", "hcr_manual18_subpixel-off", 473),
    ("auto", "hcr_auto_subpixel-off", 610),
])
def test_kit_decomposition_and_clusters_off(crop_config_path, crop_path, crop_reference_folder,
                                            tmp_path, mode, name, n_spots):
    changes = {"decomposition__enabled": False, "clusters__enabled": False, "threshold__mode": mode}
    if mode == "auto":
        changes["threshold__value"] = None
    config = crop_config(crop_config_path, **changes)
    summary, tables = run_crop(config, tmp_path, crop_path)
    folder = crop_reference_folder / name

    row = row_of(summary, FISH_CHANNEL)
    assert row["status"] == "done"
    assert row["n_spots_detected"] == n_spots
    assert row["n_spots"] == n_spots
    assert row["n_clusters"] == 0
    spots = tables["spots"]
    np.testing.assert_array_equal(spots[["z_px", "y_px", "x_px"]].to_numpy(), v1_reference(folder)["spots"])
    assert (spots["cluster_id"] == -1).all()
    # no channel has clustering on, so no clusters file
    assert "clusters" not in tables
    check_cells_as_v1(tables["cells"], folder, with_clusters=False)
    assert (tables["cells"]["n_clusters"] == 0).all()


def test_kit_subpixel_on(manual18_run, crop_config_path, crop_path, test_kit_folder, tmp_path):
    config = crop_config(crop_config_path, subpixel__enabled=True)
    summary, tables = run_crop(config, tmp_path, crop_path)
    reference = v1_reference(test_kit_folder / "reference_v1_new_env" / "general_manual18_subpixel-on")
    spots_off = manual18_run[1]["spots"]

    row = row_of(summary, FISH_CHANNEL)
    assert row["status"] == "done"
    assert row["n_spots"] == 692
    assert row["n_clusters"] == 6

    spots = tables["spots"]
    expected = reference["spots_post_clustering"]
    subpixel = spots[["z_sub_px", "y_sub_px", "x_sub_px"]].to_numpy()
    assert np.all(np.abs(subpixel - expected[:, :3]) <= 1e-6)
    for axis, size in zip("zyx", VOXEL_SIZE):
        np.testing.assert_allclose(spots[f"{axis}_sub_nm"], spots[f"{axis}_sub_px"] * size, rtol=1e-12)
    for column in ("z_px", "y_px", "x_px", "cell_id"):
        np.testing.assert_array_equal(spots[column], spots_off[column], err_msg=column)

    # Clusters are found on the subpixel positions, as in v1: spot 622 then
    # falls outside cluster 4, in v1 (both envs) as here.
    np.testing.assert_array_equal(spots["cluster_id"], expected[:, 3])
    changed = np.nonzero(spots["cluster_id"].to_numpy() != spots_off["cluster_id"].to_numpy())[0]
    assert list(changed) == [622]
    clusters = tables["clusters"][["z_px", "y_px", "x_px", "n_spots", "cluster_id"]].to_numpy()
    assert np.all(np.abs(clusters - reference["clusters"]) <= 1e-6)

    cells, cells_off = tables["cells"], manual18_run[1]["cells"]
    for column in ("cell_id", "area_px", "touches_border", "n_spots"):
        np.testing.assert_array_equal(cells[column], cells_off[column], err_msg=column)
    assert cells["n_spots_in_clusters"].sum() == cells_off["n_spots_in_clusters"].sum() - (
        spots_off["cell_id"][622] != -1
    )


def with_npz(config):
    """Copy of a config with `outputs.npz` switched on."""
    data = config.to_dict()
    data["outputs"]["npz"] = True
    return parse_config(data, config.config_folder)


def read_npz(path):
    with np.load(path) as saved:
        return {name: saved[name] for name in saved.files}


@pytest.mark.parametrize("reference, changes", [
    ("reference_v1/general_manual18_subpixel-off", {}),
    ("reference_v1/hcr_manual18_subpixel-off", {"decomposition__enabled": False, "clusters__enabled": False}),
    ("reference_v1_new_env/general_manual18_subpixel-on", {"subpixel__enabled": True}),
    ("reference_v1_new_env/hcr_manual18_subpixel-on",
     {"decomposition__enabled": False, "clusters__enabled": False, "subpixel__enabled": True}),
])
def test_kit_npz_files_as_v1(crop_config_path, crop_path, test_kit_folder, tmp_path, reference, changes):
    config = with_npz(crop_config(crop_config_path, **changes))
    run_crop(config, tmp_path, crop_path)
    assert sorted(path.name for path in (tmp_path / "npz").iterdir()) == [f"{CROP_NAME}_ch{FISH_CHANNEL}.npz"]
    saved = read_npz(tmp_path / "npz" / f"{CROP_NAME}_ch{FISH_CHANNEL}.npz")
    expected = read_npz(next((test_kit_folder / reference).glob("*_bfoutput.npz")))
    assert list(saved) == list(expected)
    for name, array in expected.items():
        assert saved[name].shape == array.shape, name
        if name == "clusters":
            # exact centres: decimal numbers, where v1 cut them to whole pixels
            assert saved[name].dtype == np.float64
            assert_clusters_as_v1(saved[name], array)
            continue
        assert saved[name].dtype == array.dtype, name
        np.testing.assert_array_equal(saved[name], array, err_msg=name)


def test_no_npz_folder_when_switched_off(tmp_path):
    image = make_image((8, 64, 64), n_spots=8, seed=2)[0]
    path = write_image(tmp_path / "off.tif", stack_channels([image, image]), "ZCYX")
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}], qc=True)
    assert config.outputs.npz is False
    summary = batch.process_image(config, "off", path, tmp_path / "run")
    assert [row["status"] for row in summary["rows"]] == ["done", "done"]
    assert sorted(path.name for path in (tmp_path / "run").iterdir()) == ["per_image", "qc"]


def test_npz_files_of_done_channels_only(tmp_path):
    many = make_image((8, 64, 64), n_spots=30, min_spacing=5, seed=1)[0]
    few = make_image((8, 64, 64), n_spots=8, seed=2)[0]
    path = write_with_damaged_channel(tmp_path / "mixed.tif", [few, few, many], damaged=1)
    bailout = {"enabled": True, "max_spots": 20}
    config = with_npz(synthetic_config(channels=[
        {"index": 0, "clusters": {"enabled": False}},
        {"index": 1},
        {"index": 2, "bailout": bailout},
    ]))
    summary = batch.process_image(config, "mixed", path, tmp_path / "run")
    assert [row["status"] for row in summary["rows"]] == ["done", "failed", "skipped"]
    assert sorted(path.name for path in (tmp_path / "run" / "npz").iterdir()) == ["mixed_ch0.npz"]
    saved = read_npz(tmp_path / "run" / "npz" / "mixed_ch0.npz")
    assert list(saved) == ["spots"]
    assert saved["spots"].shape == (8, 3)
    assert saved["spots"].dtype == np.int64


def test_kit_measurements(crop_config_path, crop_path, tmp_path):
    config = crop_config(crop_config_path, measurements__snr=True, measurements__intensity=True)
    summary, tables = run_crop(config, tmp_path, crop_path)
    spots = tables["spots"]
    assert row_of(summary, FISH_CHANNEL)["status"] == "done"
    assert list(spots.columns[-2:]) == ["snr", "log_intensity"]

    image = io.read_channel(crop_path, "ZCYX", FISH_CHANNEL)
    spot_radius_px = detection.get_spot_radius_px(VOXEL_SIZE, 570, 610, 1.45, 1.45, "confocal")
    filtered = detection.filter_channel(image, spot_radius_px, bg_radius=5, bg_method="tophat")
    positions = spots[["z_px", "y_px", "x_px"]].to_numpy()
    snr = measurements.compute_snr_spots_individual(filtered["rna"], positions, spot_radius_px)
    log_intensity = measurements.compute_log_intensity(filtered["rna_log"], positions)
    np.testing.assert_allclose(spots["snr"], snr, rtol=1e-12, equal_nan=True)
    np.testing.assert_array_equal(spots["log_intensity"], log_intensity)


# ---------------------------------------------------------------------------
# Generated images
# ---------------------------------------------------------------------------


def test_three_channels_with_own_thresholds(tmp_path):
    channels = [make_image((8, 64, 64), n_spots=n, amplitude=300, seed=n)[0] for n in (5, 10, 15)]
    path = write_image(tmp_path / "three.tif", stack_channels(channels), "ZCYX")
    thresholds = {0: 20, 1: 40, 2: 150}
    config = synthetic_config(channels=[
        {"index": index, "name": f"probe{index}", "threshold": {"mode": "manual", "value": value}}
        for index, value in thresholds.items()
    ])
    summary = batch.process_image(config, "three", path, tmp_path / "run")
    tables = read_tables(tmp_path / "run", "three")

    spot_radius_px = detection.get_spot_radius_px(VOXEL_SIZE, 570, 610, 1.45, 1.45, "confocal")
    assert [row["channel"] for row in summary["rows"]] == [0, 1, 2]
    for index, value in thresholds.items():
        row = row_of(summary, index)
        assert row["status"] == "done"
        assert row["channel_name"] == f"probe{index}"
        assert row["threshold"] == value
        filtered = detection.filter_channel(channels[index], spot_radius_px, bg_method="tophat")
        expected = detection.detect_spots(filtered["rna_log"], spot_radius_px, "manual", value, elbow=False)
        assert row["n_spots_detected"] == len(expected["spots"])
        assert (tables["spots"]["channel"] == index).sum() == row["n_spots"]
        assert row["segmentation_source"] == "" and row["segmentation_status"] == ""
        assert row["n_cells"] is None
    assert "cells" not in tables
    assert (tables["spots"]["cell_id"] == -1).all()
    assert list(tables["images"]["status"]) == ["done"] * 3


def test_one_channel_fails_others_kept(tmp_path):
    channels = [make_image((8, 64, 64), n_spots=10, seed=seed)[0] for seed in range(3)]
    path = write_with_damaged_channel(tmp_path / "damaged.tif", channels, damaged=1)
    config = synthetic_config(channels=[{"index": index} for index in range(3)])
    summary = batch.process_image(config, "damaged", path, tmp_path / "run")
    tables = read_tables(tmp_path / "run", "damaged")

    statuses = {row["channel"]: row["status"] for row in summary["rows"]}
    assert statuses == {0: "done", 1: "failed", 2: "done"}
    failed = row_of(summary, 1)
    assert failed["reason"].startswith("damaged.tif: the pixel data cannot be read (")
    assert "\n" not in failed["reason"]
    assert failed["n_spots"] is None
    assert any("channel 1: failed" in line for line in summary["log_lines"])
    assert any("Traceback" in line for line in summary["log_lines"])
    assert set(tables["spots"]["channel"]) == {0, 2}
    assert len(tables["spots"]) == row_of(summary, 0)["n_spots"] + row_of(summary, 2)["n_spots"]
    assert list(tables["images"]["status"]) == ["done", "failed", "done"]


def test_bailout_skips_one_channel(tmp_path):
    many = make_image((8, 64, 64), n_spots=30, min_spacing=5, seed=1)[0]
    few = make_image((8, 64, 64), n_spots=8, seed=2)[0]
    path = write_image(tmp_path / "bailout.tif", stack_channels([many, few]), "ZCYX")
    bailout = {"enabled": True, "max_spots": 20}
    config = synthetic_config(channels=[{"index": 0, "bailout": bailout}, {"index": 1, "bailout": bailout}])
    summary = batch.process_image(config, "bailout", path, tmp_path / "run")
    tables = read_tables(tmp_path / "run", "bailout")

    skipped = row_of(summary, 0)
    assert skipped["status"] == "skipped"
    assert skipped["n_spots_detected"] == 30
    assert skipped["threshold"] == 50
    assert skipped["reason"] == "bailout: 30 spots detected, above the limit of 20"
    assert skipped["n_spots"] is None and skipped["n_clusters"] is None
    assert any("channel 0: skipped" in line for line in summary["log_lines"])
    kept = row_of(summary, 1)
    assert kept["status"] == "done"
    assert kept["n_spots_detected"] == 8
    assert set(tables["spots"]["channel"]) == {1}
    assert set(tables["clusters"]["channel"]) <= {1}


def test_blank_image(tmp_path):
    blank = make_image((8, 64, 64), blank=True)[0]
    path = write_image(tmp_path / "blank.tif", stack_channels([blank, blank]), "ZCYX")
    config = synthetic_config(channels=[
        {"index": 0, "subpixel": {"enabled": True}},
        {"index": 1, "threshold": {"mode": "auto", "lower_limit": 10}},
    ])
    summary = batch.process_image(config, "blank", path, tmp_path / "run")
    tables = read_tables(tmp_path / "run", "blank")

    manual = row_of(summary, 0)
    assert manual["status"] == "done"
    assert manual["threshold"] == 50
    assert manual["n_spots"] == 0 and manual["n_clusters"] == 0
    assert NO_SPOTS_WARNING in manual["warnings"]
    auto = row_of(summary, 1)
    assert auto["status"] == "done"
    assert auto["threshold"] is None
    assert auto["n_spots_detected"] == 0 and auto["n_spots"] == 0
    assert detection.NO_THRESHOLD_WARNING in auto["warnings"]
    assert any(detection.NO_THRESHOLD_WARNING in line for line in summary["log_lines"])
    assert len(tables["spots"]) == 0
    assert "z_sub_px" in tables["spots"].columns
    assert len(tables["clusters"]) == 0
    assert pd.isna(tables["images"]["threshold"][1])


def test_2d_image(tmp_path):
    image, planted, _ = make_image((96, 96), n_spots=12, seed=3)
    path = write_image(tmp_path / "flat.tif", image, "YX")
    labels = np.zeros((96, 96), dtype=np.uint16)
    labels[:48] = 1
    labels[48:] = 2
    tifffile.imwrite(tmp_path / "flat_seglabels.tif", labels)
    config = synthetic_config(
        axes="YX",
        channels=[{"index": 0, "subpixel": {"enabled": True}, "measurements": {"snr": True, "intensity": True}}],
    )
    summary = batch.process_image(config, "flat", path, tmp_path / "run", label_folder=tmp_path)
    tables = read_tables(tmp_path / "run", "flat")

    row = row_of(summary, 0)
    assert row["status"] == "done", row["reason"]
    assert row["n_spots_detected"] == 12
    assert row["n_cells"] == 2
    for kind in ("spots", "clusters"):
        assert not [column for column in tables[kind].columns if column.startswith("z_")]
    spots = tables["spots"]
    assert sorted(map(tuple, spots[["y_px", "x_px"]].to_numpy())) == sorted(map(tuple, planted))
    np.testing.assert_array_equal(spots["y_nm"], spots["y_px"] * 65)
    np.testing.assert_array_equal(spots["cell_id"], np.where(spots["y_px"] < 48, 1, 2))
    assert spots["snr"].notna().all()
    assert tables["cells"]["n_spots"].sum() == 12


def test_corrupt_file(tmp_path):
    image = make_image((8, 64, 64), n_spots=5)[0]
    path = write_image(tmp_path / "broken.tif", stack_channels([image, image]), "ZCYX")
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}])
    summary = batch.process_image(config, "broken", path, tmp_path / "run", label_folder=tmp_path)

    assert [row["status"] for row in summary["rows"]] == ["failed", "failed"]
    for row in summary["rows"]:
        assert row["reason"].startswith("broken.tif: the file is damaged or incomplete")
        assert row["threshold_mode"] == "manual"
    assert any("image failed" in line for line in summary["log_lines"])
    files = sorted(path.name for path in (tmp_path / "run" / "per_image").iterdir())
    assert files == ["broken_images.csv"]
    assert list(read_tables(tmp_path / "run", "broken")["images"]["status"]) == ["failed", "failed"]


def test_channel_not_in_image(tmp_path):
    image = make_image((8, 64, 64), n_spots=5)[0]
    path = write_image(tmp_path / "two.tif", stack_channels([image, image]), "ZCYX")
    config = synthetic_config(channels=[{"index": 0}, {"index": 3}])
    summary = batch.process_image(config, "two", path, tmp_path / "run")
    assert [row["status"] for row in summary["rows"]] == ["failed", "failed"]
    assert summary["rows"][0]["reason"] == "two.tif: channel 3 does not exist; the image has 2 channels (0–1)"


def test_layout_differs_from_config(tmp_path):
    image = make_image((8, 64, 64), n_spots=5)[0]
    path = write_image(tmp_path / "zyx.tif", image, "ZYX")
    config = synthetic_config(channels=[{"index": 0}])
    summary = batch.process_image(config, "zyx", path, tmp_path / "run")
    row = row_of(summary, 0)
    assert row["status"] == "failed"
    assert "the layout ZCYX needs 4" in row["reason"]


def test_axes_in_the_file_differ_from_the_layout(tmp_path):
    image = make_image((8, 64, 64), n_spots=5)[0]
    path = tmp_path / "czyx.tif"
    tifffile.imwrite(path, np.stack([image, image]), metadata={"axes": "CZYX"}, photometric="minisblack")
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}])
    summary = batch.process_image(config, "czyx", path, tmp_path / "run")
    assert [row["status"] for row in summary["rows"]] == ["failed", "failed"]
    assert row_of(summary, 0)["reason"].startswith(
        "czyx.tif: the file's own information says its axes are stored in the order CZYX, "
        "which does not match the layout ZCYX of this run"
    )


@pytest.mark.parametrize("dtype", [np.float32, np.int16, np.int32, np.uint32])
def test_other_pixel_types_refused_before_any_work(tmp_path, monkeypatch, dtype):
    image = make_image((8, 64, 64), n_spots=5)[0]
    path = tmp_path / "other.tif"
    tifffile.imwrite(path, stack_channels([image, image]).astype(dtype), metadata={"axes": "ZCYX"},
                     photometric="minisblack")

    def no_work(*arguments, **keywords):
        raise AssertionError("the image was worked on")

    monkeypatch.setattr(io, "read_channel", no_work)
    monkeypatch.setattr(batch, "filter_channel", no_work)
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}])
    summary = batch.process_image(config, "other", path, tmp_path / "run")
    assert [row["status"] for row in summary["rows"]] == ["failed", "failed"]
    expected = io.pixel_type_problem(io.get_image_info(path))
    assert expected.startswith("other.tif: the pixel type is ")
    assert np.dtype(dtype).name in expected
    for row in summary["rows"]:
        assert row["reason"] == expected
    assert any(line == f"other: image failed: {expected}" for line in summary["log_lines"])
    assert sorted(path.name for path in (tmp_path / "run" / "per_image").iterdir()) == ["other_images.csv"]


def test_image_refused_by_cellpose_fails_with_the_reason_only(tmp_path):
    """With Cellpose, the main process refuses the image first when it reads the
    segmentation channel; the image fails with the plain reason, without the same
    message again as a segmentation warning."""
    image = make_image((8, 64, 64), n_spots=5)[0]
    path = tmp_path / "other.tif"
    tifffile.imwrite(path, stack_channels([image, image]).astype(np.float32), metadata={"axes": "ZCYX"},
                     photometric="minisblack")
    reason = io.pixel_type_problem(io.get_image_info(path))
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}],
                              segmentation={"enabled": True, "source": "cellpose"})
    summary = batch.process_image(config, "other", path, tmp_path / "run", label_folder=tmp_path / "labels",
                                  segmentation_error=reason)
    for row in summary["rows"]:
        assert row["status"] == "failed"
        assert row["reason"] == reason
        assert row["segmentation_status"] == "failed"
        assert row["warnings"] == ""

    # a segmentation that failed for another reason is still given
    summary = batch.process_image(config, "other", path, tmp_path / "run2", label_folder=tmp_path / "labels",
                                  segmentation_error="Cellpose ran out of memory")
    for row in summary["rows"]:
        assert row["warnings"] == "no cell results: segmentation failed: Cellpose ran out of memory"


def test_image_segmented_then_refused_by_its_worker_keeps_its_segmentation(tmp_path):
    """With Cellpose, an image segmented in the main process that its worker cannot
    open (here a FISH channel is missing) keeps its segmentation status and warnings."""
    image = make_image((8, 64, 64), n_spots=5)[0]
    path = write_image(tmp_path / "two.tif", stack_channels([image, image]), "ZCYX")
    labels = tmp_path / "labels"
    labels.mkdir()
    tifffile.imwrite(labels / "two_seglabels.tif", np.ones((64, 64), dtype=np.uint32))
    config = synthetic_config(channels=[{"index": 0}, {"index": 3}],
                              segmentation={"enabled": True, "source": "cellpose"})
    reason = "two.tif: channel 3 does not exist; the image has 2 channels (0–1)"
    summary = batch.process_image(config, "two", path, tmp_path / "run", label_folder=labels,
                                  segmentation_warnings=["Cellpose found few cells"])
    for row in summary["rows"]:
        assert row["status"] == "failed"
        assert row["reason"] == reason
        assert row["segmentation_source"] == "cellpose"
        assert row["segmentation_status"] == "done"
        assert row["warnings"] == "Cellpose found few cells"

    # a segmentation that failed for another reason
    summary = batch.process_image(config, "two", path, tmp_path / "run2", label_folder=labels,
                                  segmentation_error="Cellpose ran out of memory")
    for row in summary["rows"]:
        assert row["segmentation_status"] == "failed"
        assert row["warnings"] == "no cell results: segmentation failed: Cellpose ran out of memory"

    # with label files, no label file has been read when the image is refused
    config = synthetic_config(channels=[{"index": 0}, {"index": 3}],
                              segmentation={"enabled": True, "source": "label_files",
                                            "label_folder": str(labels)})
    summary = batch.process_image(config, "two", path, tmp_path / "run3", label_folder=labels)
    for row in summary["rows"]:
        assert row["segmentation_source"] == "label_files"
        assert row["segmentation_status"] == ""


def test_packed_12_bit_image(tmp_path):
    image = make_image((8, 64, 64), n_spots=8, seed=4)[0]
    assert image.max() < 4096
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}])
    (tmp_path / "16").mkdir()
    (tmp_path / "12").mkdir()
    path_16 = write_image(tmp_path / "16" / "image.tif", stack_channels([image, image]), "ZCYX")
    path_12 = tmp_path / "12" / "image.tif"
    tifffile.imwrite(path_12, stack_channels([image, image]), bitspersample=12, imagej=True,
                     metadata={"axes": "ZCYX", "unit": "um", "spacing": 0.2}, resolution=(1 / 0.065, 1 / 0.065))
    with tifffile.TiffFile(path_12) as tif:
        assert tif.pages[0].bitspersample == 12
    # the same output name, so that decomposition uses the same seed
    batch.process_image(config, "image", path_16, tmp_path / "run_16")
    summary = batch.process_image(config, "image", path_12, tmp_path / "run_12")
    assert [row["status"] for row in summary["rows"]] == ["done", "done"]
    for kind in ("spots", "clusters"):
        sixteen = read_tables(tmp_path / "run_16", "image")[kind]
        twelve = read_tables(tmp_path / "run_12", "image")[kind]
        pd.testing.assert_frame_equal(twelve, sixteen)
    assert len(read_tables(tmp_path / "run_12", "image")["spots"]) > 0


def test_opening_an_image_reads_no_pixel_data(tmp_path, monkeypatch):
    # A compressed file holding each channel's Z stack in one page cannot be mapped from the disk.
    image = make_image((8, 64, 64), n_spots=5)[0]
    path = tmp_path / "packed.tif"
    tifffile.imwrite(path, np.stack([image, image]), volumetric=True, tile=(8, 16, 16), compression="zlib",
                     metadata={"axes": "CZYX"}, photometric="minisblack")
    with tifffile.TiffFile(path) as tif:
        assert len(tif.series[0].pages) == 2 and tif.series[0].dataoffset is None

    def refuse(*arguments, **keywords):
        raise AssertionError("pixel data were read")

    monkeypatch.setattr(tifffile, "memmap", refuse)
    monkeypatch.setattr(tifffile.TiffFile, "asarray", refuse)
    monkeypatch.setattr(tifffile.TiffPage, "asarray", refuse)
    config = synthetic_config(axes="CZYX", channels=[{"index": 0}, {"index": 1}])
    info, _ = batch._open_image(config, path, [0, 1])
    assert info.shape == (2, 8, 64, 64)


@pytest.fixture
def labelled_image(tmp_path):
    channels = [make_image((8, 64, 64), n_spots=8, seed=seed)[0] for seed in (1, 2)]
    return write_image(tmp_path / "cells.tif", stack_channels(channels), "ZCYX")


def test_missing_label_file(tmp_path, labelled_image):
    label_folder = tmp_path / "labels"
    label_folder.mkdir()
    config = synthetic_config(
        channels=[{"index": 0}, {"index": 1}],
        segmentation={"enabled": True, "source": "label_files", "label_folder": str(label_folder)},
    )
    summary = batch.process_image(config, "cells", labelled_image, tmp_path / "run", label_folder=label_folder)
    tables = read_tables(tmp_path / "run", "cells")
    for row in summary["rows"]:
        assert row["status"] == "done"
        assert row["segmentation_source"] == "label_files"
        assert row["segmentation_status"] == "no_labels"
        assert row["n_cells"] is None
        assert "Label file not found" in row["warnings"]
    assert any("Label file not found" in line for line in summary["log_lines"])
    assert "cells" not in tables
    assert len(tables["spots"]) > 0
    assert (tables["spots"]["cell_id"] == -1).all()
    assert (tables["clusters"]["cell_id"] == -1).all()


def test_label_file_of_wrong_size(tmp_path, labelled_image):
    tifffile.imwrite(tmp_path / "cells_seglabels.tif", np.ones((32, 32), dtype=np.uint16))
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}])
    summary = batch.process_image(config, "cells", labelled_image, tmp_path / "run", label_folder=tmp_path)
    tables = read_tables(tmp_path / "run", "cells")
    for row in summary["rows"]:
        assert row["status"] == "done"
        assert row["segmentation_status"] == "no_labels"
        assert "labels are 32 x 32 px, but the image is 64 x 64 px" in row["warnings"]
    assert "cells" not in tables
    assert (tables["spots"]["cell_id"] == -1).all()


def test_label_file_used(tmp_path, labelled_image):
    labels = np.zeros((64, 64), dtype=np.uint16)
    labels[:, :32] = 7
    tifffile.imwrite(tmp_path / "cells_seglabels.tif", labels)
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}])
    summary = batch.process_image(config, "cells", labelled_image, tmp_path / "run", label_folder=tmp_path)
    tables = read_tables(tmp_path / "run", "cells")
    for row in summary["rows"]:
        assert row["segmentation_status"] == "done"
        assert row["n_cells"] == 1
    assert list(tables["cells"]["channel"]) == [0, 1]
    spots = tables["spots"]
    np.testing.assert_array_equal(spots["cell_id"], np.where(spots["x_px"] < 32, 7, -1))


def test_label_file_recorded_and_border_cells_counted(tmp_path, labelled_image):
    labels = np.zeros((64, 64), dtype=np.uint16)
    labels[:, :20] = 7       # touches the border
    labels[30:40, 30:40] = 3
    labels[45:50, 25:35] = 9
    label_path = tmp_path / "cells_seglabels.tif"
    tifffile.imwrite(label_path, labels)
    segmentation = {"enabled": True, "source": "label_files", "label_folder": str(tmp_path),
                    "drop_border_cells": True}
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}], segmentation=segmentation)
    summary = batch.process_image(config, "cells", labelled_image, tmp_path / "run", label_folder=tmp_path)
    assert row_of(summary, 0)["n_cells"] == 2
    assert ("cells: 3 cells in the label image, 2 kept (1 touching the image border left out, "
            "as `segmentation.drop_border_cells` is on)") in summary["log_lines"]
    [record] = summary["files_read"]
    assert record == outputs.file_record(label_path, "label file")
    assert record["size_bytes"] == label_path.stat().st_size

    # without drop_border_cells, no line about border cells
    segmentation["drop_border_cells"] = False
    config = synthetic_config(channels=[{"index": 0}], segmentation=segmentation)
    summary = batch.process_image(config, "cells", labelled_image, tmp_path / "run2", label_folder=tmp_path)
    assert not any("label image" in line for line in summary["log_lines"])
    assert len(summary["files_read"]) == 1

    # a label file that cannot be used is not recorded
    tifffile.imwrite(label_path, np.ones((32, 32), dtype=np.uint16))
    summary = batch.process_image(config, "cells", labelled_image, tmp_path / "run3", label_folder=tmp_path)
    assert summary["files_read"] == []


def label_files_config(label_folder):
    segmentation = {"enabled": True, "source": "label_files", "label_folder": str(label_folder)}
    return synthetic_config(channels=[{"index": 0}, {"index": 1}], segmentation=segmentation)


def test_label_file_recorded_from_the_bytes_the_labels_come_from(tmp_path, labelled_image, monkeypatch):
    """The label file is replaced just after its labels are read: the record
    describes the file the labels came from."""
    import hashlib

    labels = np.zeros((64, 64), dtype=np.uint16)
    labels[30:40, 30:40] = 3
    label_path = tmp_path / "cells_seglabels.tif"
    tifffile.imwrite(label_path, labels)
    original = label_path.read_bytes()
    imread = tifffile.imread

    def read_then_replace(*arguments, **keywords):
        result = imread(*arguments, **keywords)
        if label_path.read_bytes() == original:
            replacement = np.zeros((64, 64), dtype=np.uint16)
            replacement[5:60, 5:60] = 8
            tifffile.imwrite(label_path, replacement)
        return result

    monkeypatch.setattr(tifffile, "imread", read_then_replace)
    summary = batch.process_image(label_files_config(tmp_path), "cells", labelled_image, tmp_path / "run",
                                  label_folder=tmp_path)
    assert row_of(summary, 0)["n_cells"] == 1
    [record] = summary["files_read"]
    assert record["sha256"] == hashlib.sha256(original).hexdigest()
    assert record["size_bytes"] == len(original)


def test_labels_kept_when_the_label_file_cannot_be_recorded(tmp_path, labelled_image, monkeypatch):
    labels = np.zeros((64, 64), dtype=np.uint16)
    labels[30:40, 30:40] = 3
    tifffile.imwrite(tmp_path / "cells_seglabels.tif", labels)

    def broken(*arguments, **keywords):
        raise OSError("the disk went away")

    monkeypatch.setattr(outputs, "file_record", broken)
    summary = batch.process_image(label_files_config(tmp_path), "cells", labelled_image, tmp_path / "run",
                                  label_folder=tmp_path)
    for row in summary["rows"]:
        assert row["segmentation_status"] == "done"
        assert row["n_cells"] == 1
        assert "label file" not in row["warnings"]
    assert summary["files_read"] == []
    assert ("cells: warning: the label file could not be recorded in run_info.yaml "
            "(OSError: the disk went away)") in summary["log_lines"]


def test_voxel_sizes_differ_from_config(tmp_path):
    image = make_image((8, 64, 64), n_spots=8)[0]
    path = write_image(tmp_path / "voxels.tif", stack_channels([image, image]), "ZCYX", voxel_um=(0.3, 0.065, 0.065))
    config = synthetic_config(channels=[{"index": 0}, {"index": 1}])
    summary = batch.process_image(config, "voxels", path, tmp_path / "run")
    message = "voxels.tif: voxel sizes differ (Z 300 nm in the file, 200 nm in the config); the config values are used"
    for row in summary["rows"]:
        assert row["status"] == "done"
        assert message in row["warnings"]
    assert sum(message in line for line in summary["log_lines"]) == 1


def test_voxel_size_not_whole(tmp_path):
    image = make_image((8, 64, 64), n_spots=8, seed=4)[0]
    path = write_image(tmp_path / "decimal.tif", image, "ZYX", voxel_um=(0.2, 0.0645, 0.0645))
    config = synthetic_config(axes="ZYX", voxel_size={"z": 200, "yx": 64.5}, channels=[{"index": 0}])
    summary = batch.process_image(config, "decimal", path, tmp_path / "run")
    row = row_of(summary, 0)
    assert row["status"] == "done", row["reason"]
    assert "voxel sizes differ" not in row["warnings"]
    assert row["n_spots_detected"] == 8
    assert row["n_clusters"] == 0
    spots = read_tables(tmp_path / "run", "decimal")["spots"]
    np.testing.assert_allclose(spots["y_nm"], spots["y_px"] * 64.5)


def test_calibrated_threshold(tmp_path):
    image = make_image((8, 64, 64), n_spots=8, amplitude=300, seed=5)[0]
    path = write_image(tmp_path / "calibrated.tif", stack_channels([image, image]), "ZCYX")
    calibrated = {"mode": "calibrated", "calibration_filter": "cal"}
    config = synthetic_config(channels=[{"index": 0, "threshold": calibrated}, {"index": 1, "threshold": calibrated}])

    summary = batch.process_image(config, "calibrated", path, tmp_path / "run1")
    for row in summary["rows"]:
        assert row["status"] == "failed"
        assert row["reason"].startswith("no calibrated threshold for channel")

    config = config.with_resolved(["calibrated.tif"], {0: 150, 1: 20})
    summary = batch.process_image(config, "calibrated", path, tmp_path / "run2")
    spot_radius_px = detection.get_spot_radius_px(VOXEL_SIZE, 570, 610, 1.45, 1.45, "confocal")
    rna_log = detection.filter_channel(image, spot_radius_px, bg_method="tophat")["rna_log"]
    for index, value in ((0, 150), (1, 20)):
        row = row_of(summary, index)
        assert row["status"] == "done"
        assert row["threshold_mode"] == "calibrated"
        assert row["threshold"] == value
        expected = detection.detect_spots(rna_log, spot_radius_px, "manual", value, elbow=False)
        assert row["n_spots_detected"] == len(expected["spots"])
    assert row_of(summary, 0)["n_spots_detected"] < row_of(summary, 1)["n_spots_detected"]


def test_cluster_ids_minus_one_when_clustering_off(tmp_path):
    image = make_image((8, 64, 64), n_spots=8, seed=6)[0]
    path = write_image(tmp_path / "noclusters.tif", stack_channels([image, image]), "ZCYX")
    config = synthetic_config(channels=[
        {"index": 0, "clusters": {"enabled": False}},
        {"index": 1, "clusters": {"enabled": True, "radius_nm": 5000, "min_spots": 2}},
    ])
    summary = batch.process_image(config, "noclusters", path, tmp_path / "run")
    tables = read_tables(tmp_path / "run", "noclusters")
    assert row_of(summary, 0)["n_clusters"] == 0
    assert row_of(summary, 1)["n_clusters"] > 0
    spots = tables["spots"]
    assert (spots.loc[spots["channel"] == 0, "cluster_id"] == -1).all()
    assert (spots.loc[spots["channel"] == 1, "cluster_id"] >= 0).any()
    assert set(tables["clusters"]["channel"]) == {1}


# ---------------------------------------------------------------------------
# Calibration pass
# ---------------------------------------------------------------------------


def test_calibration_on_crop(crop_config_path, crop_path):
    config = crop_config(crop_config_path, threshold__mode="calibrated", threshold__calibration_filter="crop")
    result = batch.calibration_threshold(config, CROP_NAME, crop_path, FISH_CHANNEL)
    assert result["threshold"] == 13.0
    assert result["reason"] is None
    assert result["image"] == CROP_NAME and result["channel"] == FISH_CHANNEL

    assert result["elbow_threshold"] == 13.0

    config = crop_config(crop_config_path, threshold__mode="calibrated",
                         threshold__calibration_filter="crop", threshold__lower_limit=15)
    result = batch.calibration_threshold(config, CROP_NAME, crop_path, FISH_CHANNEL)
    assert result["threshold"] == 15.0
    assert result["elbow_threshold"] == 13.0


def test_calibration_blank_and_unreadable(tmp_path):
    blank = make_image((8, 64, 64), blank=True)[0]
    path = write_image(tmp_path / "blank.tif", blank, "ZYX")
    config = synthetic_config(axes="ZYX", channels=[{"index": 0, "threshold": {"mode": "calibrated", "calibration_filter": "b"}}])

    result = batch.calibration_threshold(config, "blank", path, 0)
    assert result["threshold"] is None
    assert result["reason"] == batch.NO_AUTO_THRESHOLD_REASON

    broken = tmp_path / "broken.tif"
    broken.write_text("not an image")
    result = batch.calibration_threshold(config, "broken", broken, 0)
    assert result["threshold"] is None
    assert result["reason"].startswith("broken.tif: not a readable TIFF file")
    assert result["log_lines"]

    threshold, table = detection.calibrate_threshold([
        {"image": "a", "threshold": 12.0, "reason": None},
        batch.calibration_threshold(config, "blank", path, 0),
        result,
    ])
    assert threshold == 12.0
    assert [entry["used"] for entry in table] == [True, False, False]


# ---------------------------------------------------------------------------
# OMERO
# ---------------------------------------------------------------------------


class FakeConn:
    """Stand-in connection; `number` counts the joins in this test."""

    def __init__(self, number):
        self.number = number
        self.detached = False


def lost_connection(image_id):
    """The error io raises when the connection drops while an OMERO image is read."""
    error = io.OmeroConnectionLost(
        f"OMERO image {image_id}: lost the connection to OMERO (ConnectionLostException: session {KEY})"
    )
    error.reason = f"ConnectionLostException: session {KEY}"
    return error


@pytest.fixture
def fake_omero(monkeypatch):
    """io's OMERO functions replaced by stand-ins serving one generated image.

    `calls["drops"]` sets how often the connection drops: {"info": n, "channels": n}
    makes the next n reads of that kind fail. `calls["ended"]` makes rejoining fail
    because the session has ended. `calls["read"]` records each channel read with the
    number of the connection used.
    """
    image = make_image((8, 64, 64), n_spots=8, seed=7)[0]
    calls = {"join": 0, "read": [], "info": [], "detach": [], "drops": {}, "ended": False}

    def drop(kind, image_id):
        if calls["drops"].get(kind, 0) > 0:
            calls["drops"][kind] -= 1
            raise lost_connection(image_id)

    def join_session(host, port, key):
        if calls["ended"]:
            raise io.OmeroSessionEnded("The OMERO session has ended. Log in again and start a new run.")
        calls["join"] += 1
        return FakeConn(calls["join"])

    def get_omero_image_info(conn, image_id):
        calls["info"].append((image_id, conn.number))
        drop("info", image_id)
        return io.OmeroImageInfo(
            image_id=image_id, name="my image.tif", size_z=8, size_c=2, size_t=1,
            size_y=64, size_x=64, pixel_type="uint16", dtype=np.dtype("uint16"),
            voxel_size_z=200.0, voxel_size_y=65.0, voxel_size_x=65.0,
            channel_names=["a", "b"],
        )

    def read_omero_channels(conn, image_id, layout, channels):
        calls["read"].append((image_id, tuple(channels), conn.number))
        drop("channels", image_id)
        return {channel: image for channel in channels}

    def detach_session(conn):
        conn.detached = True
        calls["detach"].append(conn.number)

    monkeypatch.setattr(io, "join_session", join_session)
    monkeypatch.setattr(io, "get_omero_image_info", get_omero_image_info)
    monkeypatch.setattr(io, "read_omero_channels", read_omero_channels)
    monkeypatch.setattr(io, "detach_session", detach_session)
    batch.close_omero_connection()
    yield calls
    batch.close_omero_connection()


def omero_config():
    config = synthetic_config(channels=[{"index": 1}])
    data = config.to_dict()
    data["run"]["input"]["source"] = "omero"
    data["run"]["input"]["omero"]["image_ids"] = [123, 124]
    return parse_config(data)


KEY = "1b2c3d4e-0000-1111-2222-333344445555"


def test_omero_image(tmp_path, fake_omero):
    config = omero_config()
    for image_id in (123, 124):
        name = io.omero_output_name(image_id, "my image.tif")
        summary = batch.process_image(
            config, name, image_id, tmp_path / "run",
            omero_host="omero.example", omero_port=4064, omero_key=KEY,
        )
        row = row_of(summary, 1)
        assert row["status"] == "done", row["reason"]
        assert row["image"] == name
        assert row["n_spots_detected"] == 8
        tables = read_tables(tmp_path / "run", name)
        assert set(tables) == {"spots", "clusters", "images"}
        assert (tables["spots"]["image"] == name).all()
    files = sorted(path.name for path in (tmp_path / "run" / "per_image").iterdir())
    assert files[0] == "123_my image_clusters.csv"
    assert len(files) == 6
    assert fake_omero["join"] == 1
    assert fake_omero["read"] == [(123, (1,), 1), (124, (1,), 1)]
    batch.close_omero_connection()
    assert fake_omero["detach"] == [1]


def test_omero_errors_hide_the_session_key(tmp_path, fake_omero, monkeypatch):
    def broken(conn, image_id, layout, channels):
        raise RuntimeError(f"server said no to session {KEY}")

    monkeypatch.setattr(io, "read_omero_channels", broken)
    summary = batch.process_image(
        omero_config(), "123_x", 123, tmp_path / "run",
        omero_host="omero.example", omero_port=4064, omero_key=KEY,
    )
    row = row_of(summary, 1)
    assert row["status"] == "failed"
    assert KEY not in row["reason"]
    assert "[hidden]" in row["reason"]
    assert not any(KEY in line for line in summary["log_lines"])


@pytest.mark.parametrize("error", [io.OmeroSessionEnded("ended"), MemoryError(), KeyboardInterrupt()])
def test_run_stopping_errors_pass_through(tmp_path, fake_omero, monkeypatch, error):
    def stop(conn, image_id, layout, channels):
        raise error

    monkeypatch.setattr(io, "read_omero_channels", stop)
    with pytest.raises(type(error)):
        batch.process_image(
            omero_config(), "123_x", 123, tmp_path / "run",
            omero_host="omero.example", omero_port=4064, omero_key=KEY,
        )


def omero_image(config, image_id, run_folder):
    return batch.process_image(
        config, f"{image_id}_x", image_id, run_folder,
        omero_host="omero.example", omero_port=4064, omero_key=KEY,
    )


def assert_no_key_in_files(folder):
    for path in folder.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes(), path.name


def test_omero_drop_while_reading_information(tmp_path, fake_omero):
    fake_omero["drops"] = {"info": 1}
    summary = omero_image(omero_config(), 123, tmp_path / "run")
    assert row_of(summary, 1)["status"] == "done", row_of(summary, 1)["reason"]
    # joined once for the first image, then rejoined once after the drop
    assert fake_omero["join"] == 2
    assert fake_omero["detach"] == [1]
    assert fake_omero["info"] == [(123, 1), (123, 2)]
    assert fake_omero["read"] == [(123, (1,), 2)]
    notes = [line for line in summary["log_lines"] if "rejoining the session" in line]
    assert notes == [
        "123_x: OMERO image 123: lost the connection to OMERO "
        "(ConnectionLostException: session [hidden]); rejoining the session and trying again"
    ]

    # the next image goes on with the new connection, without joining again
    summary = omero_image(omero_config(), 124, tmp_path / "run")
    assert row_of(summary, 1)["status"] == "done"
    assert fake_omero["join"] == 2
    assert fake_omero["info"][-1] == (124, 2)
    assert fake_omero["read"][-1] == (124, (1,), 2)
    assert_no_key_in_files(tmp_path / "run")


def test_omero_drop_twice_fails_the_image(tmp_path, fake_omero):
    fake_omero["drops"] = {"info": 2}
    summary = omero_image(omero_config(), 123, tmp_path / "run")
    row = row_of(summary, 1)
    assert row["status"] == "failed"
    assert row["reason"] == (
        "OMERO image 123: lost the connection to OMERO twice (ConnectionLostException: session [hidden])"
    )
    assert fake_omero["join"] == 2
    assert fake_omero["read"] == []
    assert not any(KEY in line for line in summary["log_lines"])
    assert_no_key_in_files(tmp_path / "run")

    # the next image is read with the rejoined connection
    summary = omero_image(omero_config(), 124, tmp_path / "run")
    assert row_of(summary, 1)["status"] == "done"
    assert fake_omero["join"] == 2


def test_omero_one_rejoin_for_the_whole_image(tmp_path, fake_omero):
    fake_omero["drops"] = {"info": 1, "channels": 1}
    summary = omero_image(omero_config(), 123, tmp_path / "run")
    row = row_of(summary, 1)
    assert row["status"] == "failed"
    assert "lost the connection to OMERO twice" in row["reason"]
    assert fake_omero["join"] == 2


def test_omero_drop_while_reading_a_channel(tmp_path, fake_omero):
    fake_omero["drops"] = {"channels": 1}
    summary = omero_image(omero_config(), 123, tmp_path / "run")
    assert row_of(summary, 1)["status"] == "done"
    assert fake_omero["read"] == [(123, (1,), 1), (123, (1,), 2)]
    assert any("rejoining the session" in line for line in summary["log_lines"])


def test_omero_drop_and_session_ended(tmp_path, fake_omero):
    fake_omero["drops"] = {"info": 1}
    omero_image(omero_config(), 122, tmp_path / "run")  # joins the session first
    fake_omero["drops"] = {"info": 1}
    fake_omero["ended"] = True
    with pytest.raises(io.OmeroSessionEnded, match="Log in again"):
        omero_image(omero_config(), 123, tmp_path / "run")


def test_omero_drop_and_server_unreachable(tmp_path, fake_omero, monkeypatch):
    omero_image(omero_config(), 122, tmp_path / "run")
    join = io.join_session

    def no_server(host, port, key):
        raise ConnectionError("cannot reach the OMERO server at omero.example:4064")

    monkeypatch.setattr(io, "join_session", no_server)
    fake_omero["drops"] = {"info": 1}
    summary = omero_image(omero_config(), 123, tmp_path / "run")
    row = row_of(summary, 1)
    assert row["status"] == "failed"
    assert "could not reconnect" in row["reason"]
    assert fake_omero["detach"] == [1]

    # the next image joins the session again
    monkeypatch.setattr(io, "join_session", join)
    summary = omero_image(omero_config(), 124, tmp_path / "run")
    assert row_of(summary, 1)["status"] == "done"
    assert fake_omero["join"] == 2
    assert fake_omero["info"][-1] == (124, 2)


REAL_JOIN_SESSION = io.join_session
REAL_DETACH_SESSION = io.detach_session


def test_omero_drop_and_rejoin_timeout(tmp_path, fake_omero, monkeypatch):
    """The real omero-py gateway answers "not joined" when the server does not answer in time;
    the image fails and the run is not stopped as if the session had ended."""
    Ice = pytest.importorskip("Ice")
    omero_clients = pytest.importorskip("omero.clients")
    omero_image(omero_config(), 122, tmp_path / "run")
    communicators = []

    def no_answer(client, communicator):
        communicators.append(communicator)
        raise Ice.ConnectTimeoutException()

    monkeypatch.setattr(omero_clients.BaseClient, "getRouter", no_answer)
    monkeypatch.setattr(io, "join_session", REAL_JOIN_SESSION)
    monkeypatch.setattr(io, "detach_session", REAL_DETACH_SESSION)
    fake_omero["drops"] = {"info": 1}
    try:
        summary = omero_image(omero_config(), 123, tmp_path / "run")
        row = row_of(summary, 1)
        assert row["status"] == "failed"
        assert row["reason"].startswith(
            "OMERO image 123: lost the connection to OMERO and could not reconnect "
            "(cannot reach the OMERO server at omero.example:4064"
        )
        assert "session has ended" not in row["reason"]

        # the next image tries to join again, and fails on its own
        summary = omero_image(omero_config(), 124, tmp_path / "run")
        row = row_of(summary, 1)
        assert row["status"] == "failed"
        assert "cannot reach the OMERO server" in row["reason"]
    finally:
        batch.close_omero_connection()
        for communicator in communicators:
            try:
                communicator.destroy()
            except Exception:
                pass
    assert_no_key_in_files(tmp_path / "run")


@pytest.mark.parametrize("pixel_type, dtype", [("float", "float32"), ("int16", "int16"), ("uint32", "uint32")])
def test_omero_other_pixel_type_refused(tmp_path, fake_omero, monkeypatch, pixel_type, dtype):
    def other_info(conn, image_id):
        return io.OmeroImageInfo(
            image_id=image_id, name="my image.tif", size_z=8, size_c=2, size_t=1,
            size_y=64, size_x=64, pixel_type=pixel_type, dtype=np.dtype(dtype),
            voxel_size_z=200.0, voxel_size_y=65.0, voxel_size_x=65.0, channel_names=["a", "b"],
        )

    monkeypatch.setattr(io, "get_omero_image_info", other_info)
    summary = omero_image(omero_config(), 123, tmp_path / "run")
    row = row_of(summary, 1)
    assert row["status"] == "failed"
    assert row["reason"].startswith("OMERO image 123: the pixel type is ")
    assert f"({dtype})" in row["reason"] and "Image › Type › 16-bit" in row["reason"]
    assert fake_omero["read"] == []


def test_omero_calibration_drop(tmp_path, fake_omero):
    config = omero_config()
    arguments = dict(omero_host="omero.example", omero_port=4064, omero_key=KEY)

    fake_omero["drops"] = {"info": 1}
    result = batch.calibration_threshold(config, "123_x", 123, 1, **arguments)
    assert result["threshold"] is not None, result["reason"]
    assert fake_omero["join"] == 2
    assert result["log_lines"] == [
        "123_x: OMERO image 123: lost the connection to OMERO "
        "(ConnectionLostException: session [hidden]); rejoining the session and trying again"
    ]

    fake_omero["drops"] = {"channels": 2}
    result = batch.calibration_threshold(config, "124_x", 124, 1, **arguments)
    assert result["threshold"] is None
    assert result["reason"] == (
        "OMERO image 124: lost the connection to OMERO twice (ConnectionLostException: session [hidden])"
    )
    assert fake_omero["join"] == 3
    assert not any(KEY in line for line in result["log_lines"])

    fake_omero["drops"] = {"info": 1}
    fake_omero["ended"] = True
    with pytest.raises(io.OmeroSessionEnded):
        batch.calibration_threshold(config, "125_x", 125, 1, **arguments)


# ---------------------------------------------------------------------------
# QC files
# ---------------------------------------------------------------------------

def with_qc(config, **switches):
    """Copy of a config with every QC file switched off, then `switches` switched on."""
    data = config.to_dict()
    data["outputs"]["qc"] = {**QC_OFF, **switches}
    return parse_config(data, config.config_folder)


def qc_files(run_folder):
    folder = run_folder / "qc"
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


def spotty_image(tmp_path, name="qc", n_channels=2):
    """A generated image with spots in each channel; the config of a test may use only the first."""
    channels = [make_image((8, 64, 64), n_spots=12, seed=seed)[0] for seed in range(n_channels)]
    return write_image(tmp_path / f"{name}.tif", stack_channels(channels), "ZCYX")


ALL_QC = dict(elbow_plot=True, detection=True, reference_spot=True, cellpose=True, final="png")


@pytest.mark.parametrize("switch, value, names", [
    ("elbow_plot", True, ["qc_ch0_elbow.png"]),
    ("detection", True, ["qc_ch0_detection.png"]),
    ("reference_spot", True, ["qc_ch0_referencespot.tif"]),
    ("final", "png", ["qc_ch0_final.png"]),
    ("final", "html", ["qc_ch0_final.html"]),
    ("cellpose", True, []),
])
def test_each_qc_switch_alone(tmp_path, switch, value, names):
    path = spotty_image(tmp_path)
    config = with_qc(synthetic_config(), **{switch: value})
    summary = batch.process_image(config, "qc", path, tmp_path / "run")
    row = row_of(summary, 0)
    assert row["status"] == "done"
    assert "QC file" not in row["warnings"]
    assert qc_files(tmp_path / "run") == names
    assert not (tmp_path / "run" / batch.QC_TEMPORARY_FOLDER_NAME).exists()


def test_tables_equal_with_qc_on_and_off(tmp_path):
    path = spotty_image(tmp_path, n_channels=2)
    base = synthetic_config(channels=[{"index": 0, "subpixel": {"enabled": True}}, {"index": 1}])
    tables = {}
    for name, config in (("on", with_qc(base, **ALL_QC)), ("off", with_qc(base))):
        summary = batch.process_image(config, "qc", path, tmp_path / name)
        assert [row["status"] for row in summary["rows"]] == ["done", "done"]
        tables[name] = read_tables(tmp_path / name, "qc")
    for kind in ("spots", "clusters", "images"):
        on, off = tables["on"][kind], tables["off"][kind]
        if kind == "images":
            on, off = on.drop(columns="runtime_s"), off.drop(columns="runtime_s")
        pd.testing.assert_frame_equal(on, off)
    assert qc_files(tmp_path / "off") == []
    assert not (tmp_path / "off" / "qc").exists()
    assert qc_files(tmp_path / "on") == [
        f"qc_ch{channel}_{kind}" for channel in (0, 1)
        for kind in ("detection.png", "elbow.png", "final.png", "referencespot.tif")
    ]


@pytest.mark.parametrize("threshold", [
    {"mode": "manual", "value": 50},
    {"mode": "auto"},
    {"mode": "auto", "lower_limit": 400},
    {"mode": "calibrated", "calibration_filter": "cal"},
])
def test_elbow_plot_in_each_threshold_mode(tmp_path, threshold, monkeypatch):
    from bigfish_pypeline import qc

    drawn = []
    original = qc.draw_elbow_plot

    def keep(detected, image_name, channel, threshold_mode, lower_limit=None, channel_name=None):
        drawn.append((detected, threshold_mode, lower_limit))
        return original(detected, image_name, channel, threshold_mode, lower_limit, channel_name)

    monkeypatch.setattr(qc, "draw_elbow_plot", keep)
    path = spotty_image(tmp_path)
    config = with_qc(synthetic_config(channels=[{"index": 0, "threshold": threshold}]), elbow_plot=True)
    if threshold["mode"] == "calibrated":
        config = config.with_resolved(["qc.tif"], {0: 60})
    summary = batch.process_image(config, "qc", path, tmp_path / "run")
    row = row_of(summary, 0)
    assert row["status"] == "done"
    assert "QC file" not in row["warnings"] and batch.NO_ELBOW_PLOT_WARNING not in row["warnings"]
    assert qc_files(tmp_path / "run") == ["qc_ch0_elbow.png"]
    [(detected, mode, lower_limit)] = drawn
    assert mode == threshold["mode"]
    assert lower_limit == threshold.get("lower_limit")
    assert detected["threshold"] == row["threshold"]
    assert len(detected["elbow_thresholds"]) > 0


def drawn_elbow_plots(monkeypatch):
    """A list that receives (detected, legend texts) of each elbow plot drawn."""
    from bigfish_pypeline import qc

    drawn = []
    original = qc.draw_elbow_plot

    def keep(detected, *args, **kwargs):
        figure = original(detected, *args, **kwargs)
        legend = [text.get_text() for text in figure.axes[0].get_legend().get_texts()]
        drawn.append((detected, legend))
        return figure

    monkeypatch.setattr(qc, "draw_elbow_plot", keep)
    return drawn


def test_elbow_curve_of_one_point_in_a_run(tmp_path, monkeypatch):
    """A channel whose elbow curve has a single point: automatic mode gives no threshold
    with the usual warning; a manual threshold finds the same spots with the elbow plot
    on and off, and the plot is drawn without an automatic value."""
    from test_detection import one_point_elbow_image

    image = one_point_elbow_image()
    path = write_image(tmp_path / "few.tif", stack_channels([image, image]), "ZCYX")
    drawn = drawn_elbow_plots(monkeypatch)

    config = with_qc(synthetic_config(channels=[{"index": 0, "threshold": {"mode": "auto"}}]), elbow_plot=True)
    row = row_of(batch.process_image(config, "few", path, tmp_path / "auto"), 0)
    assert row["status"] == "done"
    assert row["threshold"] is None and row["n_spots"] == 0
    assert detection.NO_THRESHOLD_WARNING in row["warnings"]
    assert qc_files(tmp_path / "auto") == ["few_ch0_elbow.png"]
    [(detected, legend)] = drawn
    assert detected["auto_threshold"] is None
    assert legend == ["No automatic threshold found"]

    spots = {}
    for elbow in (True, False):
        drawn.clear()
        manual = synthetic_config(channels=[{"index": 0, "threshold": {"mode": "manual", "value": 2}}])
        folder = tmp_path / f"manual_{elbow}"
        summary = batch.process_image(with_qc(manual, elbow_plot=elbow), "few", path, folder)
        row = row_of(summary, 0)
        assert row["status"] == "done", row["reason"]
        assert row["n_spots_detected"] == 9
        assert "threshold" not in row["warnings"] and "elbow" not in row["warnings"]
        spots[elbow] = read_tables(folder, "few")["spots"]
        if elbow:
            [(detected, legend)] = drawn
            assert detected["auto_threshold"] is None
            assert legend == ["Selected threshold = 2.0", "No automatic threshold found"]
            assert qc_files(folder) == ["few_ch0_elbow.png"]
        else:
            assert drawn == [] and qc_files(folder) == []
    pd.testing.assert_frame_equal(spots[True], spots[False])


def test_no_candidate_spots_gives_no_elbow_plot(tmp_path):
    blank = make_image((8, 64, 64), blank=True)[0]
    path = write_image(tmp_path / "blank.tif", stack_channels([blank, blank]), "ZCYX")
    config = with_qc(synthetic_config(channels=[{"index": 0, "threshold": {"mode": "auto"}}]),
                     elbow_plot=True)
    summary = batch.process_image(config, "blank", path, tmp_path / "run")
    row = row_of(summary, 0)
    assert row["status"] == "done"
    assert batch.NO_ELBOW_PLOT_WARNING in row["warnings"]
    assert f"blank, channel 0: warning: {batch.NO_ELBOW_PLOT_WARNING}" in summary["log_lines"]
    assert qc_files(tmp_path / "run") == []


def test_no_reference_spot_when_decomposition_off_or_skipped(tmp_path):
    spots = make_image((8, 64, 64), n_spots=12, seed=0)[0]
    blank = make_image((8, 64, 64), blank=True)[0]
    path = write_image(tmp_path / "qc.tif", stack_channels([spots, spots, blank]), "ZCYX")
    config = with_qc(synthetic_config(channels=[
        {"index": 0},
        {"index": 1, "decomposition": {"enabled": False}},
        {"index": 2},
    ]), reference_spot=True)
    summary = batch.process_image(config, "qc", path, tmp_path / "run")
    assert [row["status"] for row in summary["rows"]] == ["done", "done", "done"]
    assert NO_SPOTS_WARNING in row_of(summary, 2)["warnings"]
    assert qc_files(tmp_path / "run") == ["qc_ch0_referencespot.tif"]
    reference = tifffile.imread(tmp_path / "run" / "qc" / "qc_ch0_referencespot.tif")
    assert reference.ndim == 3


def test_failed_and_skipped_channels_write_no_qc_files(tmp_path):
    many = make_image((8, 64, 64), n_spots=30, min_spacing=5, seed=1)[0]
    few = make_image((8, 64, 64), n_spots=8, seed=2)[0]
    path = write_with_damaged_channel(tmp_path / "mixed.tif", [few, few, many], damaged=1)
    config = with_qc(synthetic_config(channels=[
        {"index": 0}, {"index": 1}, {"index": 2, "bailout": {"enabled": True, "max_spots": 20}},
    ]), **ALL_QC)
    summary = batch.process_image(config, "mixed", path, tmp_path / "run")
    assert [row["status"] for row in summary["rows"]] == ["done", "failed", "skipped"]
    assert all(name.startswith("mixed_ch0_") for name in qc_files(tmp_path / "run"))
    assert len(qc_files(tmp_path / "run")) == 4


def test_qc_files_of_a_2d_image_with_labels(tmp_path):
    image = make_image((96, 96), n_spots=12, seed=3)[0]
    path = write_image(tmp_path / "flat.tif", image, "YX")
    labels = np.zeros((96, 96), dtype=np.uint16)
    labels[:48] = 1
    labels[48:] = 2
    tifffile.imwrite(tmp_path / "flat_seglabels.tif", labels)
    config = with_qc(synthetic_config(axes="YX", channels=[{"index": 0, "subpixel": {"enabled": True}}]),
                     elbow_plot=True, detection=True, reference_spot=True, final="html")
    summary = batch.process_image(config, "flat", path, tmp_path / "run", label_folder=tmp_path)
    row = row_of(summary, 0)
    assert row["status"] == "done" and "QC file" not in row["warnings"]
    assert qc_files(tmp_path / "run") == [
        "flat_ch0_detection.png", "flat_ch0_elbow.png", "flat_ch0_final.html",
        "flat_ch0_referencespot.tif",
    ]
    page = (tmp_path / "run" / "qc" / "flat_ch0_final.html").read_text(encoding="utf-8")
    assert "2 cells" in page and "12 spots" in page


def test_qc_file_that_fails_leaves_the_channel_done(tmp_path, monkeypatch):
    from bigfish_pypeline import qc

    def broken(*args, **kwargs):
        raise OSError("no space left on the disk")

    monkeypatch.setattr(qc, "write_detection_plot", broken)
    path = spotty_image(tmp_path)
    config = with_qc(synthetic_config(), **ALL_QC)
    summary = batch.process_image(config, "qc", path, tmp_path / "run")
    row = row_of(summary, 0)
    warning = "the QC file qc_ch0_detection.png could not be written: OSError: no space left on the disk"
    assert row["status"] == "done"
    assert row["warnings"].endswith(warning)
    assert f"qc, channel 0: warning: {warning}" in summary["log_lines"]
    assert any(line.startswith("Traceback") and "no space left" in line for line in summary["log_lines"])
    assert read_tables(tmp_path / "run", "qc")["images"]["warnings"][0] == row["warnings"]
    assert qc_files(tmp_path / "run") == ["qc_ch0_elbow.png", "qc_ch0_final.png", "qc_ch0_referencespot.tif"]
    assert not (tmp_path / "run" / batch.QC_TEMPORARY_FOLDER_NAME).exists()


def test_qc_files_that_cannot_be_moved_leave_the_channel_done(tmp_path):
    path = spotty_image(tmp_path)
    run_folder = tmp_path / "run"
    run_folder.mkdir()
    # a file where the `qc` folder should be
    (run_folder / "qc").write_text("", encoding="utf-8")
    config = with_qc(synthetic_config(), elbow_plot=True, final="html")
    summary = batch.process_image(config, "qc", path, run_folder)
    row = row_of(summary, 0)
    assert row["status"] == "done"
    for name in ("qc_ch0_elbow.png", "qc_ch0_final.html"):
        assert f"the QC file {name} could not be written: " in row["warnings"]
    images = read_tables(run_folder, "qc")["images"]
    assert images["warnings"][0] == row["warnings"]
    assert not (run_folder / batch.QC_TEMPORARY_FOLDER_NAME).exists()


def test_qc_files_removed_when_the_tables_cannot_be_written(tmp_path, monkeypatch):
    from bigfish_pypeline import outputs

    def broken(*args, **kwargs):
        raise outputs.OutputError("the tables could not be written")

    monkeypatch.setattr(outputs, "write_image_tables", broken)
    path = spotty_image(tmp_path)
    with pytest.raises(outputs.OutputError):
        batch.process_image(with_qc(synthetic_config(), **ALL_QC), "qc", path, tmp_path / "run")
    assert qc_files(tmp_path / "run") == []
    assert not (tmp_path / "run" / batch.QC_TEMPORARY_FOLDER_NAME).exists()


def test_kit_qc_files(crop_config_path, crop_path, tmp_path, monkeypatch):
    """The crop's detection plot and final QC are drawn on the channel's maximum
    projection, after background subtraction and as read."""
    from bigfish_pypeline import qc

    pictures = {}
    for name in ("draw_detection_plot", "draw_final_qc"):
        original = getattr(qc, name)

        def keep(picture, *args, _name=name, _original=original, **kwargs):
            pictures[_name] = (picture, args, kwargs)
            return _original(picture, *args, **kwargs)

        monkeypatch.setattr(qc, name, keep)
    config = with_qc(crop_config(crop_config_path), **ALL_QC)
    summary, tables = run_crop(config, tmp_path, crop_path)
    assert row_of(summary, FISH_CHANNEL)["warnings"] == ""
    assert qc_files(tmp_path) == [
        f"{CROP_NAME}_ch{FISH_CHANNEL}_{kind}"
        for kind in ("detection.png", "elbow.png", "final.png", "referencespot.tif")
    ]
    raw = io.read_channel(crop_path, "ZCYX", FISH_CHANNEL)
    np.testing.assert_array_equal(pictures["draw_final_qc"][0], raw.max(axis=0))
    spot_radius_px = detection.get_spot_radius_px(VOXEL_SIZE, 570, 610, 1.45, 1.45, "confocal")
    rna = detection.filter_channel(raw, spot_radius_px, bg_radius=5, bg_method="tophat")["rna"]
    np.testing.assert_array_equal(pictures["draw_detection_plot"][0], rna.max(axis=0))
    spots, image_name, channel, radius, clusters, cluster_radius = pictures["draw_detection_plot"][1][:6]
    np.testing.assert_array_equal(spots, tables["spots"][["z_px", "y_px", "x_px"]].to_numpy())
    np.testing.assert_array_equal(clusters, tables["clusters"][["z_px", "y_px", "x_px"]].to_numpy())
    assert cluster_radius == pytest.approx(600 / 65)
    final_args = pictures["draw_final_qc"][1]
    assert len(final_args[2]) == 44  # cells table
    assert final_args[3].max() == 44  # label image
