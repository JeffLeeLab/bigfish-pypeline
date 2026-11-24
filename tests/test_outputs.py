"""Tests for outputs.py: result tables, per-image files, combined tables and the run folder."""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from bigfish_pypeline import outputs
from bigfish_pypeline.cells import assign_cells
from bigfish_pypeline.config import load_config, parse_config
from bigfish_pypeline.outputs import (
    OutputError,
    add_thresholds_to_run_config,
    check_writable,
    combine_tables,
    image_is_complete,
    image_row,
    join_tables,
    make_calibration_table,
    make_cells_table,
    make_clusters_table,
    make_images_table,
    make_run_folder,
    make_spots_table,
    output_root,
    safe_run_name,
    spot_columns,
    write_calibration,
    write_image_tables,
    write_run_config,
    write_text_replacing,
)

# Columns of spec section 8.2, written out in full.
SPOTS_3D = [
    "image", "channel", "channel_name", "spot_id",
    "z_px", "y_px", "x_px", "z_nm", "y_nm", "x_nm",
    "cluster_id", "cell_id",
]
SPOTS_3D_ALL = [
    "image", "channel", "channel_name", "spot_id",
    "z_px", "y_px", "x_px", "z_nm", "y_nm", "x_nm",
    "z_sub_px", "y_sub_px", "x_sub_px", "z_sub_nm", "y_sub_nm", "x_sub_nm",
    "cluster_id", "cell_id", "snr", "log_intensity",
]
SPOTS_2D = [
    "image", "channel", "channel_name", "spot_id",
    "y_px", "x_px", "y_nm", "x_nm",
    "cluster_id", "cell_id",
]
SPOTS_2D_ALL = [
    "image", "channel", "channel_name", "spot_id",
    "y_px", "x_px", "y_nm", "x_nm",
    "y_sub_px", "x_sub_px", "y_sub_nm", "x_sub_nm",
    "cluster_id", "cell_id", "snr", "log_intensity",
]
CLUSTERS_3D = [
    "image", "channel", "channel_name", "cluster_id",
    "z_px", "y_px", "x_px", "z_nm", "y_nm", "x_nm",
    "n_spots", "cell_id",
]
CLUSTERS_2D = [
    "image", "channel", "channel_name", "cluster_id",
    "y_px", "x_px", "y_nm", "x_nm",
    "n_spots", "cell_id",
]
CELLS = [
    "image", "channel", "channel_name", "cell_id", "area_px", "area_um2",
    "centroid_y_px", "centroid_x_px", "touches_border", "n_spots",
    "n_spots_in_clusters", "n_spots_outside_clusters", "n_clusters", "mean_spots_per_cluster",
]
IMAGES = [
    "image", "channel", "channel_name", "status", "reason", "threshold_mode", "threshold",
    "n_spots_detected", "n_spots", "n_clusters", "n_cells", "segmentation_source",
    "segmentation_status", "warnings", "runtime_s",
]
CALIBRATION = ["image", "channel", "auto_threshold", "used", "reason"]

VOXEL_Z = 200
VOXEL_YX = 65

# (z, y, x) spot positions in pixels
SPOTS = np.array([[0, 3, 3], [1, 3, 4], [2, 8, 2], [0, 9, 9]])
# (z, y, x, n_spots, cluster_id)
CLUSTERS = np.array([[1, 3, 4, 2, 0]])


def _masks():
    masks = np.zeros((10, 12), dtype=np.uint32)
    masks[2:5, 2:6] = 1
    masks[7:10, 0:4] = 2
    return masks


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ndim, switches, expected",
    [
        (3, {}, SPOTS_3D),
        (3, {"subpixel": True, "snr": True, "intensity": True}, SPOTS_3D_ALL),
        (2, {}, SPOTS_2D),
        (2, {"subpixel": True, "snr": True, "intensity": True}, SPOTS_2D_ALL),
        (
            3,
            {"subpixel": True},
            SPOTS_3D[:10]
            + ["z_sub_px", "y_sub_px", "x_sub_px", "z_sub_nm", "y_sub_nm", "x_sub_nm"]
            + ["cluster_id", "cell_id"],
        ),
        (3, {"snr": True}, SPOTS_3D + ["snr"]),
        (3, {"intensity": True}, SPOTS_3D + ["log_intensity"]),
        (2, {"snr": True, "intensity": True}, SPOTS_2D + ["snr", "log_intensity"]),
    ],
)
def test_spot_columns(ndim, switches, expected):
    assert spot_columns(ndim, **switches) == expected


def test_spots_table_3d_values():
    table = make_spots_table("img", 2, "exon", SPOTS, 3, VOXEL_YX, VOXEL_Z)
    assert list(table.columns) == SPOTS_3D
    assert table["spot_id"].tolist() == [0, 1, 2, 3]
    assert table["cluster_id"].tolist() == [-1] * 4
    assert table["cell_id"].tolist() == [-1] * 4
    assert table["z_px"].tolist() == [0, 1, 2, 0]
    assert table["z_nm"].tolist() == [0, 200, 400, 0]
    assert table["y_nm"].tolist() == [195, 195, 520, 585]
    assert table["x_nm"].tolist() == [195, 260, 130, 585]
    assert (table["image"] == "img").all()
    assert (table["channel"] == 2).all()
    assert (table["channel_name"] == "exon").all()


def test_spots_table_2d_has_no_z():
    table = make_spots_table("img", 0, "a", SPOTS[:, 1:], 2, VOXEL_YX)
    assert list(table.columns) == SPOTS_2D
    assert table["y_nm"].tolist() == [195, 195, 520, 585]


def test_spots_table_with_every_optional_value():
    subpixel = SPOTS + 0.25
    table = make_spots_table(
        "img", 2, "exon", SPOTS, 3, VOXEL_YX, VOXEL_Z,
        cluster_id=[0, 0, -1, -1], cell_id=[1, 1, 2, -1],
        subpixel=subpixel, snr=[1.0, 2.0, 3.0, 4.0], log_intensity=[5.0, 6.0, 7.0, 8.0],
    )
    assert list(table.columns) == SPOTS_3D_ALL
    assert table["cluster_id"].tolist() == [0, 0, -1, -1]
    assert table["cell_id"].tolist() == [1, 1, 2, -1]
    assert table["z_sub_px"].tolist() == [0.25, 1.25, 2.25, 0.25]
    assert table["z_sub_nm"].tolist() == [50, 250, 450, 50]
    assert table["x_sub_nm"].tolist() == pytest.approx([211.25, 276.25, 146.25, 601.25])
    assert table["snr"].tolist() == [1, 2, 3, 4]
    assert table["log_intensity"].tolist() == [5, 6, 7, 8]


def test_spots_table_2d_subpixel():
    table = make_spots_table(
        "img", 0, "a", SPOTS[:, 1:], 2, VOXEL_YX, subpixel=SPOTS[:, 1:] + 0.5,
    )
    assert list(table.columns) == [c for c in SPOTS_2D_ALL if c not in ("snr", "log_intensity")]
    assert table["y_sub_nm"].tolist() == [227.5, 227.5, 552.5, 617.5]


def test_spots_table_without_subpixel_in_a_run_with_subpixel():
    columns = spot_columns(3, subpixel=True, snr=True)
    table = make_spots_table("img", 1, "b", SPOTS, 3, VOXEL_YX, VOXEL_Z, columns=columns)
    assert list(table.columns) == columns
    for name in ("z_sub_px", "y_sub_px", "x_sub_px", "z_sub_nm", "y_sub_nm", "x_sub_nm", "snr"):
        assert table[name].isna().all()
    assert table["cluster_id"].tolist() == [-1] * 4


def test_spots_table_value_outside_run_columns_is_refused():
    with pytest.raises(ValueError):
        make_spots_table("img", 1, "b", SPOTS, 3, VOXEL_YX, VOXEL_Z, snr=[1, 2, 3, 4],
                         columns=spot_columns(3))


def test_spots_table_without_spots():
    table = make_spots_table("img", 1, "b", np.zeros((0, 3)), 3, VOXEL_YX, VOXEL_Z)
    assert list(table.columns) == SPOTS_3D
    assert len(table) == 0
    table = make_spots_table("img", 1, "b", [], 2, VOXEL_YX, columns=spot_columns(2, snr=True))
    assert list(table.columns) == SPOTS_2D + ["snr"]
    assert len(table) == 0


def test_spots_table_ignores_extra_columns():
    with_cluster = np.column_stack([SPOTS, [0, 0, -1, -1]])
    table = make_spots_table("img", 1, "b", with_cluster, 3, VOXEL_YX, VOXEL_Z)
    assert list(table.columns) == SPOTS_3D
    assert table["cluster_id"].tolist() == [-1] * 4


def test_clusters_table_3d_and_2d():
    table = make_clusters_table("img", 2, "exon", CLUSTERS, 3, VOXEL_YX, VOXEL_Z)
    assert list(table.columns) == CLUSTERS_3D
    assert table.iloc[0][["cluster_id", "z_px", "y_px", "x_px", "n_spots", "cell_id"]].tolist() == [
        0, 1, 3, 4, 2, -1,
    ]
    assert table.iloc[0][["z_nm", "y_nm", "x_nm"]].tolist() == [200, 195, 260]

    table = make_clusters_table("img", 2, "exon", CLUSTERS[:, 1:], 2, VOXEL_YX, cell_id=[1])
    assert list(table.columns) == CLUSTERS_2D
    assert table["cell_id"].tolist() == [1]
    assert table["y_nm"].tolist() == [195]


def test_clusters_table_without_clusters():
    for clusters in (None, np.zeros((0, 5)), []):
        table = make_clusters_table("img", 2, "exon", clusters, 3, VOXEL_YX, VOXEL_Z)
        assert list(table.columns) == CLUSTERS_3D
        assert len(table) == 0


def test_cells_table():
    _, _, cells = assign_cells(_masks(), SPOTS, 3, VOXEL_YX)
    table = make_cells_table("img", 2, "exon", cells)
    assert list(table.columns) == CELLS
    assert table["cell_id"].tolist() == [1, 2]
    assert (table["image"] == "img").all()
    assert (table["channel"] == 2).all()


def test_images_table():
    rows = [
        image_row("img", 2, "exon", "done", threshold_mode="manual", threshold=18,
                  n_spots_detected=10, n_spots=12, n_clusters=1, n_cells=0,
                  segmentation_source="label_files", segmentation_status="done",
                  warnings=["decomposition skipped", "metadata mismatch"], runtime_s=1.5),
        image_row("img", 3, "intron", "failed", reason="bad channel", threshold_mode="auto"),
    ]
    table = make_images_table(rows)
    assert list(table.columns) == IMAGES
    assert table.loc[0, "warnings"] == "decomposition skipped; metadata mismatch"
    assert table.loc[0, "n_cells"] == 0
    assert pd.isna(table.loc[1, "threshold"])
    assert pd.isna(table.loc[1, "n_cells"])
    assert table.loc[1, "warnings"] == ""
    with pytest.raises(ValueError):
        image_row("img", 2, "exon", "finished")


def test_calibration_table():
    table = make_calibration_table([
        ("a", 2, 11.0, True, ""),
        ("b", 2, None, False, "no usable threshold"),
    ])
    assert list(table.columns) == CALIBRATION
    assert table["used"].tolist() == [True, False]
    assert pd.isna(table.loc[1, "auto_threshold"])


def test_join_tables_keeps_order_and_header():
    columns = spot_columns(3)
    first = make_spots_table("img", 1, "a", SPOTS[:2], 3, VOXEL_YX, VOXEL_Z, columns=columns)
    empty = make_spots_table("img", 2, "b", [], 3, VOXEL_YX, VOXEL_Z, columns=columns)
    second = make_spots_table("img", 3, "c", SPOTS, 3, VOXEL_YX, VOXEL_Z, columns=columns)
    joined = join_tables([first, empty, second])
    assert list(joined.columns) == columns
    assert joined["channel"].tolist() == [1, 1, 3, 3, 3, 3]
    assert len(join_tables([empty])) == 0


# ---------------------------------------------------------------------------
# Per-image files and combining
# ---------------------------------------------------------------------------


def _image_tables(image, n_spots, with_cells):
    """Tables of one image with two channels (2 and 3), in a run where channel 2 has subpixel fitting."""
    columns = spot_columns(3, subpixel=True)
    spots = SPOTS[:n_spots]
    masks = _masks()
    spot_tables, cluster_tables, cell_tables, rows = [], [], [], []
    for channel, name in ((2, "exon"), (3, "intron")):
        clusters = CLUSTERS if n_spots else np.zeros((0, 5))
        cluster_id = np.array([0, 0, -1, -1][:n_spots])
        cell_id = cluster_cell_id = None
        if with_cells:
            spot_cell_id, cluster_cell_id, cells = assign_cells(
                masks, np.column_stack([spots, cluster_id]) if n_spots else [], 3, VOXEL_YX,
                clusters=clusters,
            )
            cell_id = spot_cell_id
            cell_tables.append(make_cells_table(image, channel, name, cells))
        subpixel = spots + 0.5 if channel == 2 else None
        spot_tables.append(make_spots_table(
            image, channel, name, spots, 3, VOXEL_YX, VOXEL_Z,
            cluster_id=cluster_id, cell_id=cell_id, subpixel=subpixel, columns=columns,
        ))
        cluster_tables.append(make_clusters_table(
            image, channel, name, clusters, 3, VOXEL_YX, VOXEL_Z, cell_id=cluster_cell_id,
        ))
        rows.append(image_row(
            image, channel, name, "done", threshold_mode="manual", threshold=18,
            n_spots_detected=n_spots, n_spots=n_spots, n_clusters=len(clusters),
            n_cells=len(cell_tables[-1]) if with_cells else None,
            segmentation_source="label_files" if with_cells else "",
            segmentation_status="done" if with_cells else "",
            warnings=[] if n_spots else ["no candidate spots"], runtime_s=0.5,
        ))
    return {
        "spots": join_tables(spot_tables),
        "clusters": join_tables(cluster_tables),
        "cells": join_tables(cell_tables) if with_cells else None,
        "images": make_images_table(rows),
    }


def _write(run_folder, image, tables):
    return write_image_tables(
        run_folder, image, tables["images"],
        spots=tables["spots"], clusters=tables["clusters"], cells=tables["cells"],
    )


def _leftovers(folder):
    return [path.name for path in folder.rglob("*") if path.name.endswith(".tmp")]


def test_write_image_tables(tmp_path):
    (tmp_path / "per_image").mkdir()
    image = "çell plate 1 é"
    tables = _image_tables(image, 4, with_cells=True)
    written = _write(tmp_path, image, tables)
    names = sorted(path.name for path in (tmp_path / "per_image").iterdir())
    assert names == sorted(f"{image}_{kind}.csv" for kind in ("spots", "clusters", "cells", "images"))
    assert [path.name for path in written][-1] == f"{image}_images.csv"
    assert image_is_complete(tmp_path, image)
    assert _leftovers(tmp_path) == []

    spots = pd.read_csv(tmp_path / "per_image" / f"{image}_spots.csv")
    assert list(spots.columns) == list(tables["spots"].columns)
    pd.testing.assert_frame_equal(spots, tables["spots"], check_dtype=False)
    # channel 3 has no subpixel fitting: its subpixel values are written as nothing
    text = (tmp_path / "per_image" / f"{image}_spots.csv").read_text(encoding="utf-8")
    last_line = text.splitlines()[-1]
    assert ",,,,,," in last_line
    assert last_line.startswith(f"{image},3,intron,3,")


def test_write_image_tables_without_cells(tmp_path):
    (tmp_path / "per_image").mkdir()
    tables = _image_tables("b", 4, with_cells=False)
    _write(tmp_path, "b", tables)
    names = sorted(path.name for path in (tmp_path / "per_image").iterdir())
    assert names == ["b_clusters.csv", "b_images.csv", "b_spots.csv"]


@pytest.mark.parametrize("fail_at", [1, 2, 4])
def test_failure_while_writing_leaves_nothing(tmp_path, monkeypatch, fail_at):
    (tmp_path / "per_image").mkdir()
    tables = _image_tables("a", 4, with_cells=True)
    calls = {"n": 0}
    original = outputs._write_csv

    def failing_write(table, path):
        calls["n"] += 1
        if calls["n"] == fail_at:
            raise OSError("disk full")
        original(table, path)

    monkeypatch.setattr(outputs, "_write_csv", failing_write)
    with pytest.raises(OutputError, match="disk full"):
        _write(tmp_path, "a", tables)
    assert list((tmp_path / "per_image").iterdir()) == []


def test_failure_while_renaming_leaves_nothing(tmp_path, monkeypatch):
    (tmp_path / "per_image").mkdir()
    tables = _image_tables("a", 4, with_cells=True)
    calls = {"n": 0}
    original = os.replace

    def failing_replace(source, destination):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("no space")
        original(source, destination)

    monkeypatch.setattr(outputs.os, "replace", failing_replace)
    with pytest.raises(OutputError):
        _write(tmp_path, "a", tables)
    assert list((tmp_path / "per_image").iterdir()) == []
    assert not image_is_complete(tmp_path, "a")


def test_combine_three_images(tmp_path):
    (tmp_path / "per_image").mkdir()
    # written out of order, combined in run order
    sets = {
        "image 1 é": _image_tables("image 1 é", 4, with_cells=True),
        "image_2": _image_tables("image_2", 4, with_cells=False),
        "image_3": _image_tables("image_3", 0, with_cells=True),
    }
    for image in ("image_3", "image 1 é", "image_2"):
        _write(tmp_path, image, sets[image])
    order = ["image 1 é", "image_2", "image_3"]

    written = combine_tables(tmp_path, order)
    assert set(written) == {"spots", "clusters", "cells", "images"}
    assert _leftovers(tmp_path) == []

    for kind in ("spots", "clusters", "cells", "images"):
        text = (tmp_path / f"{kind}.csv").read_text(encoding="utf-8")
        header = text.splitlines()[0]
        assert text.count(header) == 1

        combined = pd.read_csv(tmp_path / f"{kind}.csv", keep_default_na=False, na_values=[""])
        parts = [sets[image][kind] for image in order if sets[image][kind] is not None]
        expected = pd.concat([part for part in parts if len(part)], ignore_index=True)
        # empty text is written as nothing and read back as missing
        expected = expected.replace("", np.nan)
        assert list(combined.columns) == list(parts[0].columns)
        assert len(combined) == len(expected)
        pd.testing.assert_frame_equal(combined, expected, check_dtype=False)

    spots = pd.read_csv(tmp_path / "spots.csv")
    assert spots["image"].tolist() == ["image 1 é"] * 8 + ["image_2"] * 8
    assert spots["spot_id"].tolist() == [0, 1, 2, 3] * 4
    cells = pd.read_csv(tmp_path / "cells.csv")
    assert cells["image"].unique().tolist() == ["image 1 é", "image_3"]
    images = pd.read_csv(tmp_path / "images.csv")
    assert images["image"].tolist() == ["image 1 é"] * 2 + ["image_2"] * 2 + ["image_3"] * 2


def test_combine_without_cell_results(tmp_path):
    (tmp_path / "per_image").mkdir()
    _write(tmp_path, "a", _image_tables("a", 4, with_cells=False))
    written = combine_tables(tmp_path, ["a"])
    assert "cells" not in written
    assert not (tmp_path / "cells.csv").exists()


def test_combine_refuses_incomplete_image(tmp_path):
    (tmp_path / "per_image").mkdir()
    _write(tmp_path, "a", _image_tables("a", 4, with_cells=False))
    with pytest.raises(OutputError, match="not complete"):
        combine_tables(tmp_path, ["a", "missing"])


def test_combine_refuses_different_headers(tmp_path):
    (tmp_path / "per_image").mkdir()
    tables = _image_tables("a", 4, with_cells=False)
    _write(tmp_path, "a", tables)
    other = _image_tables("b", 4, with_cells=False)
    other["spots"] = other["spots"].drop(columns=["z_sub_px"])
    _write(tmp_path, "b", other)
    with pytest.raises(OutputError, match="other columns"):
        combine_tables(tmp_path, ["a", "b"])
    assert _leftovers(tmp_path) == []


# ---------------------------------------------------------------------------
# Run folder
# ---------------------------------------------------------------------------

NOW = datetime(2026, 11, 22, 9, 5)


def _config(input_folder="", output_folder="", source="local", name="my_run"):
    return parse_config({
        "config_version": 1,
        "run": {
            "name": name,
            "input": {"source": source, "folder": str(input_folder)},
            "output_folder": str(output_folder),
        },
        "image": {"axes": "ZCYX", "voxel_size_nm": {"z": 200, "yx": 65}},
        "channels": [{"index": 2}],
    })


def test_run_folder_name_and_number(tmp_path):
    config = _config(output_folder=tmp_path / "out")
    first = make_run_folder(config, now=NOW)
    assert first == tmp_path / "out" / "2026-11-22_0905_my_run"
    assert (first / "per_image").is_dir()
    second = make_run_folder(config, now=NOW)
    third = make_run_folder(config, now=NOW)
    assert second.name == "2026-11-22_0905_my_run_2"
    assert third.name == "2026-11-22_0905_my_run_3"
    assert _leftovers(tmp_path) == []
    assert [path.name for path in (tmp_path / "out").iterdir() if path.name.startswith(".")] == []


def test_default_root(tmp_path):
    config = _config(input_folder=tmp_path / "images ü")
    (tmp_path / "images ü").mkdir()
    assert output_root(config) == tmp_path / "images ü" / "bigfish_results"
    run_folder = make_run_folder(config, now=NOW)
    assert run_folder.parent == tmp_path / "images ü" / "bigfish_results"


def test_omero_needs_output_folder():
    config = _config(source="omero")
    with pytest.raises(OutputError, match="OMERO runs need an output folder"):
        output_root(config)


def test_no_input_and_no_output_folder():
    with pytest.raises(OutputError):
        output_root(_config())


@pytest.mark.skipif(sys.platform == "win32", reason="folder permissions work differently on Windows")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anywhere")
def test_unwritable_root(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        config = _config(output_folder=locked / "results")
        with pytest.raises(OutputError, match="cannot be written") as error:
            make_run_folder(config, now=NOW)
        assert str(locked / "results") in str(error.value)
        with pytest.raises(OutputError):
            check_writable(locked)
        assert list(locked.iterdir()) == []
    finally:
        locked.chmod(0o700)


def test_unsafe_characters_in_run_name(tmp_path):
    assert safe_run_name('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"
    assert safe_run_name("trial run ü. ") == "trial run ü"
    assert safe_run_name("") == "run"
    config = _config(output_folder=tmp_path, name="exp 1/2: test?")
    run_folder = make_run_folder(config, now=NOW)
    assert run_folder.name == "2026-11-22_0905_exp 1_2_ test_"
    assert run_folder.parent == tmp_path


def test_run_config_round_trip(tmp_path, crop_config_path):
    config = load_config(crop_config_path)
    images = ["sypN_DAPI_Phal_jim-exon_crop.tif"]
    path = write_run_config(tmp_path, config, images)
    assert path == tmp_path / "run_config.yaml"
    loaded = load_config(path)
    assert loaded == config.with_full_paths().with_resolved(images)
    assert loaded.run.input.folder == str(crop_config_path.parent.resolve())
    assert loaded.segmentation.label_folder == str(crop_config_path.parent.resolve())
    assert loaded.resolved.images == images
    assert loaded.resolved.thresholds == {}
    # every default is written out
    text = path.read_text(encoding="utf-8")
    assert "cellprob_threshold" in text and "drop_border_cells" in text


def test_run_config_with_thresholds(tmp_path, crop_config_path):
    config = load_config(crop_config_path)
    images = ["a.tif", "b ä.tif"]
    write_run_config(tmp_path, config, images, thresholds={2: np.float64(12.5)})
    loaded = load_config(tmp_path / "run_config.yaml")
    assert loaded == config.with_full_paths().with_resolved(images, {2: 12.5})

    write_run_config(tmp_path, config, images)
    assert load_config(tmp_path / "run_config.yaml").resolved.thresholds == {}
    add_thresholds_to_run_config(tmp_path, {2: 14.0})
    loaded = load_config(tmp_path / "run_config.yaml")
    assert loaded == config.with_full_paths().with_resolved(images, {2: 14.0})
    assert _leftovers(tmp_path) == []

    # a repeated run keeps the thresholds already in its config
    write_run_config(tmp_path, loaded, images)
    assert load_config(tmp_path / "run_config.yaml").resolved.thresholds == {2: 14.0}


def test_write_calibration(tmp_path):
    path = write_calibration(tmp_path, [("a", 2, 11.0, True, ""), ("b", 2, None, False, "too few spots")])
    assert path == tmp_path / "calibration.csv"
    table = pd.read_csv(path)
    assert list(table.columns) == CALIBRATION
    assert table["used"].tolist() == [True, False]
    assert path.read_text(encoding="utf-8").splitlines()[2] == "b,2,,False,too few spots"
    assert _leftovers(tmp_path) == []


def test_write_text_replacing(tmp_path):
    path = tmp_path / "progress.json"
    write_text_replacing(path, '{"done": 1}')
    write_text_replacing(path, '{"done": 2}')
    assert path.read_text(encoding="utf-8") == '{"done": 2}'
    assert [p.name for p in tmp_path.iterdir()] == ["progress.json"]


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------


def test_package_versions_without_loading_the_packages(monkeypatch):
    import importlib.metadata

    real_version = importlib.metadata.version

    def version(name):
        if name == "omero-py":
            raise importlib.metadata.PackageNotFoundError(name)
        return real_version(name)

    monkeypatch.setattr(importlib.metadata, "version", version)
    versions = outputs.package_versions()
    assert list(versions) == [shown for shown, _ in outputs.RUN_INFO_PACKAGES]
    assert versions["omero-py"] == outputs.NOT_INSTALLED
    assert versions["numpy"] == np.__version__
    assert all(isinstance(value, str) and value for value in versions.values())


def test_git_commit(tmp_path, monkeypatch):
    commit = outputs.git_commit()
    if commit is not None:
        assert len(commit.split()[0]) == 40
    # a package folder outside a git copy, and a computer without git
    assert outputs.git_commit(tmp_path / "bigfish_pypeline") is None
    monkeypatch.setattr(outputs.shutil, "which", lambda name: None)
    assert outputs.git_commit() is None


def test_computer_details():
    assert isinstance(outputs.operating_system(), str) and outputs.operating_system()
    memory = outputs.computer_memory()
    assert memory.endswith(" GB") and float(memory.split()[0]) > 0


def test_write_run_info_keeps_the_order(tmp_path):
    info = {"status": "finished", "started": "2026-11-24 10:00:00+00:00", "workers": 2,
            "package_versions": {"numpy": "2.0"}, "calibrated_thresholds": {"channel 2": 14.0}}
    path = outputs.write_run_info(tmp_path, info)
    assert path == tmp_path / "run_info.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Run record")
    assert outputs.read_run_info(tmp_path) == info
    assert list(outputs.read_run_info(tmp_path)) == list(info)
    assert _leftovers(tmp_path) == []
