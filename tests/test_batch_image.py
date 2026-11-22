"""Tests for batch.process_image and batch.calibration_threshold: one image through every step."""

import numpy as np
import pandas as pd
import pytest
import tifffile

from bigfish_pypeline import batch, detection, io, measurements
from bigfish_pypeline.config import load_config, parse_config
from bigfish_pypeline.decomposition import NO_SPOTS_WARNING
from conftest import CROP_NAME, FISH_CHANNEL
from synthetic import make_image

VOXEL_SIZE = (200, 65, 65)  # nm: z, y, x


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


def synthetic_config(axes="ZCYX", voxel_size=None, channels=None, segmentation=None):
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
    np.testing.assert_array_equal(
        clusters[["z_px", "y_px", "x_px", "n_spots", "cluster_id"]].to_numpy(), expected_clusters
    )
    for axis, size in zip("zyx", VOXEL_SIZE):
        np.testing.assert_array_equal(clusters[f"{axis}_nm"], clusters[f"{axis}_px"] * size)

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
    np.testing.assert_array_equal(
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
    channels = [make_image((8, 64, 64), n_spots=10, seed=seed)[0].astype(np.float32) for seed in range(3)]
    channels[1][3, 20, 20] = np.nan
    path = write_image(tmp_path / "nan.tif", stack_channels(channels), "ZCYX")
    config = synthetic_config(channels=[{"index": index} for index in range(3)])
    summary = batch.process_image(config, "nan", path, tmp_path / "run")
    tables = read_tables(tmp_path / "run", "nan")

    statuses = {row["channel"]: row["status"] for row in summary["rows"]}
    assert statuses == {0: "done", 1: "failed", 2: "done"}
    failed = row_of(summary, 1)
    assert failed["reason"] == "nan.tif: channel 1 contains NaN or infinite values"
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

    config = crop_config(crop_config_path, threshold__mode="calibrated",
                         threshold__calibration_filter="crop", threshold__lower_limit=15)
    assert batch.calibration_threshold(config, CROP_NAME, crop_path, FISH_CHANNEL)["threshold"] == 15.0


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
    def __init__(self):
        self.detached = False


@pytest.fixture
def fake_omero(monkeypatch):
    """io's OMERO functions replaced by stand-ins serving one generated image."""
    image = make_image((8, 64, 64), n_spots=8, seed=7)[0]
    calls = {"join": 0, "read": [], "detach": 0}

    def join_session(host, port, key):
        calls["join"] += 1
        return FakeConn()

    def get_omero_image_info(conn, image_id):
        return io.OmeroImageInfo(
            image_id=image_id, name="my image.tif", size_z=8, size_c=2, size_t=1,
            size_y=64, size_x=64, pixel_type="uint16", dtype=np.dtype("uint16"),
            voxel_size_z=200.0, voxel_size_y=65.0, voxel_size_x=65.0,
            channel_names=["a", "b"],
        )

    def read_omero_channels_with_retry(conn, image_id, layout, channels, host, port, key):
        calls["read"].append((image_id, tuple(channels), host, port, key))
        return {channel: image for channel in channels}, conn

    def detach_session(conn):
        calls["detach"] += 1

    monkeypatch.setattr(io, "join_session", join_session)
    monkeypatch.setattr(io, "get_omero_image_info", get_omero_image_info)
    monkeypatch.setattr(io, "read_omero_channels_with_retry", read_omero_channels_with_retry)
    monkeypatch.setattr(io, "detach_session", detach_session)
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
    assert files[0] == "123_my image.tif_clusters.csv"
    assert len(files) == 6
    assert fake_omero["join"] == 1
    assert fake_omero["read"][0] == (123, (1,), "omero.example", 4064, KEY)
    batch.close_omero_connection()
    assert fake_omero["detach"] == 1


def test_omero_errors_hide_the_session_key(tmp_path, fake_omero, monkeypatch):
    def broken(conn, image_id, layout, channels, host, port, key):
        raise RuntimeError(f"server said no to session {key}")

    monkeypatch.setattr(io, "read_omero_channels_with_retry", broken)
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
    def stop(conn, image_id, layout, channels, host, port, key):
        raise error

    monkeypatch.setattr(io, "read_omero_channels_with_retry", stop)
    with pytest.raises(type(error)):
        batch.process_image(
            omero_config(), "123_x", 123, tmp_path / "run",
            omero_host="omero.example", omero_port=4064, omero_key=KEY,
        )
