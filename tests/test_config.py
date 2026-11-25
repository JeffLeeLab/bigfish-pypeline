"""Tests for the configuration file module."""

import copy
import os
from pathlib import Path

import pytest
import yaml

from bigfish_pypeline.config import (
    OMERO_HOST,
    OMERO_PORT,
    Config,
    ConfigError,
    apply_overrides,
    load_config,
    parse_config,
    save_config,
)

MINIMAL = {
    "config_version": 1,
    "image": {"axes": "ZCYX", "voxel_size_nm": {"z": 200, "yx": 65}},
    "channels": [{"index": 2}],
}

# Every setting of spec section 6.2 with its default, for MINIMAL.
EXPECTED_DEFAULTS = {
    "config_version": 1,
    "run": {
        "name": "my_run",
        "input": {
            "source": "local",
            "folder": "",
            "filter": "",
            "extension": ".tif",
            "omero": {
                "host": "10.34.168.89",
                "port": 4064,
                "username": "",
                "dataset_id": None,
                "image_ids": [],
            },
        },
        "output_folder": "",
        "workers": "auto",
        "keep_awake": True,
        "seed": 0,
    },
    "image": {"axes": "ZCYX", "voxel_size_nm": {"z": 200, "yx": 65}},
    "microscope": {"type": "confocal", "NA": 1.45, "RI": 1.45},
    "channels": [
        {
            "index": 2,
            "name": "",
            "ex": 570,
            "em": 610,
            "background": {"method": "rolling_ball", "radius_px": 5},
            "threshold": {
                "mode": "auto",
                "value": None,
                "lower_limit": None,
                "calibration_filter": "",
            },
            "bailout": {"enabled": False, "max_spots": None},
            "decomposition": {"enabled": True, "alpha": 0.5, "beta": 1},
            "subpixel": {"enabled": False},
            "clusters": {"enabled": True, "radius_nm": 500, "min_spots": 4},
            "measurements": {"snr": False, "intensity": False},
        }
    ],
    "segmentation": {
        "enabled": False,
        "source": "cellpose",
        "label_folder": "",
        "channel": 0,
        "projection": "max",
        "clip": {"enabled": False, "value": 100},
        "background": {"enabled": True, "method": "rolling_ball", "radius_px": 200},
        "median_px": None,
        "gaussian_sigma_px": None,
        "cellpose": {
            "model": "cpsam_v2",
            "diameter": None,
            "flow_threshold": 0.4,
            "cellprob_threshold": 0,
            "min_size": 15,
            "max_size_fraction": 0.4,
            "normalize": True,
            "batch_size": 1,
            "niter": None,
        },
        "device": "auto",
        "drop_border_cells": False,
    },
    "outputs": {
        "label_images": True,
        "npz": False,
        "qc": {
            "elbow_plot": True,
            "detection": True,
            "reference_spot": True,
            "cellpose": True,
            "final": "png",
        },
    },
}


def made(**changes):
    """A minimal config as a dictionary, with top-level groups replaced by `changes`."""
    data = copy.deepcopy(MINIMAL)
    data.update(copy.deepcopy(changes))
    return data


def problems(data):
    """The messages of the ConfigError raised for `data`."""
    with pytest.raises(ConfigError) as caught:
        parse_config(data)
    return caught.value.messages


def write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def assert_one_message(data, *parts):
    """Exactly one message, containing every text in `parts`."""
    messages = problems(data)
    assert len(messages) == 1, messages
    for part in parts:
        assert part in messages[0], messages


# --- the test kit config and defaults -----------------------------------------


def test_test_kit_config_loads_unchanged(crop_config_path):
    config = load_config(crop_config_path)
    assert config.config_version == 1
    assert config.image.axes == "ZCYX"
    assert config.image.voxel_size_nm.z == 200
    assert config.image.voxel_size_nm.yx == 65
    assert config.run.input.omero.host == ""
    assert config.run.output_folder == ""
    assert config.run.workers == 1
    channel = config.channels[0]
    assert channel.index == 2
    assert channel.threshold.mode == "manual"
    assert channel.threshold.value == 18
    assert channel.background.method == "tophat"
    assert channel.clusters.min_spots == 12
    assert config.segmentation.source == "label_files"
    assert config.resolved is None


def test_load_save_load_gives_equal_config(crop_config_path, tmp_path):
    config = load_config(crop_config_path)
    saved = tmp_path / "saved.yaml"
    save_config(config, saved)
    assert load_config(saved) == config


def test_saved_file_keeps_the_order_of_the_layout(crop_config_path, tmp_path):
    saved = tmp_path / "saved.yaml"
    save_config(load_config(crop_config_path), saved)
    data = yaml.safe_load(saved.read_text(encoding="utf-8"))
    assert list(data) == [
        "config_version",
        "run",
        "image",
        "microscope",
        "channels",
        "segmentation",
        "outputs",
    ]
    assert list(data["run"]) == [
        "name",
        "input",
        "output_folder",
        "workers",
        "keep_awake",
        "seed",
    ]
    assert list(data["channels"][0]) == [
        "index",
        "name",
        "ex",
        "em",
        "background",
        "threshold",
        "bailout",
        "decomposition",
        "subpixel",
        "clusters",
        "measurements",
    ]


def test_saved_file_writes_empty_settings_as_nothing(tmp_path):
    saved = tmp_path / "saved.yaml"
    save_config(parse_config(MINIMAL), saved)
    lines = saved.read_text(encoding="utf-8").splitlines()
    assert "      dataset_id:" in lines
    assert "    max_spots:" in lines


def test_minimal_config_gets_every_default():
    config = parse_config(MINIMAL)
    assert config.to_dict() == EXPECTED_DEFAULTS


def test_defaults_survive_a_save_and_load(tmp_path):
    saved = tmp_path / "saved.yaml"
    save_config(parse_config(MINIMAL), saved)
    assert load_config(saved).to_dict() == EXPECTED_DEFAULTS


def test_lab_omero_server_is_the_default_host_and_port():
    assert OMERO_HOST == "10.34.168.89"
    assert OMERO_PORT == 4064
    omero = parse_config(MINIMAL).run.input.omero
    assert (omero.host, omero.port) == (OMERO_HOST, OMERO_PORT)


def test_an_empty_omero_host_is_valid():
    data = made(run={"input": {"omero": {"host": ""}}})
    assert parse_config(data).run.input.omero.host == ""


def test_several_channels_and_a_two_dimensional_layout():
    data = made(
        image={"axes": "CYX", "voxel_size_nm": {"yx": 100}},
        channels=[{"index": 0}, {"index": 1}, {"index": 3}, {"index": 7}],
    )
    config = parse_config(data)
    assert [channel.index for channel in config.channels] == [0, 1, 3, 7]
    assert config.image.voxel_size_nm.z is None


def test_a_blank_z_is_accepted_for_a_two_dimensional_layout():
    for blank in (None, ""):
        data = made(image={"axes": "YX", "voxel_size_nm": {"z": blank, "yx": 65}})
        assert parse_config(data).image.voxel_size_nm.z is None


def test_blank_groups_and_values_mean_defaults():
    data = made(microscope=None, segmentation={"median_px": "", "label_folder": None})
    config = parse_config(data)
    assert config.microscope.NA == 1.45
    assert config.segmentation.median_px is None
    assert config.segmentation.label_folder == ""


def test_workers_can_be_a_number():
    assert parse_config(made(run={"workers": 4})).run.workers == 4


# --- unknown settings ---------------------------------------------------------


def test_unknown_setting_with_a_suggestion_nested_in_a_channel():
    data = made(channels=[{"index": 2, "clusters": {"nb_min_spot": 5}}])
    assert_one_message(
        data,
        "`channels[0].clusters.nb_min_spot`",
        "is not a known setting",
        "did you mean `min_spots`?",
    )


def test_unknown_setting_inside_a_channel_itself():
    data = made(channels=[{"index": 2, "nme": "x"}])
    assert_one_message(data, "`channels[0].nme`", "is not a known setting", "did you mean `name`?")


def test_unknown_setting_at_the_top_level_with_a_suggestion():
    data = made(microscop={"type": "confocal"})
    assert_one_message(data, "`microscop`", "did you mean `microscope`?")


def test_unknown_setting_without_a_suggestion():
    data = made(zebra_stripes=3)
    messages = problems(data)
    assert messages == ["`zebra_stripes` is not a known setting."]


def test_unknown_setting_without_a_suggestion_when_nested():
    data = made(run={"input": {"banana": "x"}})
    assert problems(data) == ["`run.input.banana` is not a known setting."]


def test_suggestions_ignore_capitals():
    data = made(microscope={"na": 1.4})
    assert_one_message(data, "`microscope.na`", "did you mean `NA`?")


def test_suggestions_come_only_from_settings_valid_at_that_place():
    data = made(run={"input": {"filtr": "x"}})
    assert_one_message(data, "did you mean `filter`?")
    data = made(run={"filtr": "x"})
    assert problems(data) == ["`run.filtr` is not a known setting."]


# --- required settings --------------------------------------------------------


def test_missing_axes():
    data = made(image={"voxel_size_nm": {"z": 200, "yx": 65}})
    assert_one_message(data, "`image.axes` is required", "ZCYX")


def test_blank_axes_counts_as_missing():
    data = made(image={"axes": None, "voxel_size_nm": {"z": 200, "yx": 65}})
    assert_one_message(data, "`image.axes` is required")


def test_missing_image_group_reports_both_settings():
    data = made()
    del data["image"]
    messages = problems(data)
    assert any("`image.axes` is required" in message for message in messages)
    assert any("`image.voxel_size_nm` is required" in message for message in messages)


def test_missing_voxel_size():
    data = made(image={"axes": "ZCYX"})
    assert_one_message(data, "`image.voxel_size_nm` is required")


def test_missing_yx_voxel_size():
    data = made(image={"axes": "ZCYX", "voxel_size_nm": {"z": 200}})
    assert_one_message(data, "`image.voxel_size_nm.yx` is required")


def test_blank_yx_voxel_size():
    data = made(image={"axes": "ZCYX", "voxel_size_nm": {"z": 200, "yx": None}})
    assert_one_message(data, "`image.voxel_size_nm.yx` is required")


@pytest.mark.parametrize("bad", [0, -65])
def test_voxel_size_must_be_positive(bad):
    data = made(image={"axes": "ZCYX", "voxel_size_nm": {"z": 200, "yx": bad}})
    assert_one_message(data, "`image.voxel_size_nm.yx` must be a positive number")
    data = made(image={"axes": "ZCYX", "voxel_size_nm": {"z": bad, "yx": 65}})
    assert_one_message(data, "`image.voxel_size_nm.z` must be a positive number")


def test_z_given_for_a_two_dimensional_layout():
    for axes in ("YX", "CYX"):
        data = made(image={"axes": axes, "voxel_size_nm": {"z": 200, "yx": 65}})
        assert_one_message(data, "`image.voxel_size_nm.z`", "2D layout", axes)


def test_z_missing_for_a_three_dimensional_layout():
    for axes in ("ZCYX", "CZYX", "ZYX"):
        data = made(image={"axes": axes, "voxel_size_nm": {"yx": 65}})
        assert_one_message(data, "`image.voxel_size_nm.z`", "3D layout", axes)


def test_unknown_axes():
    data = made(image={"axes": "XYZ", "voxel_size_nm": {"z": 200, "yx": 65}})
    assert_one_message(data, "`image.axes` must be one of", "`ZCYX`", "found `XYZ`")


def test_missing_config_version():
    data = made()
    del data["config_version"]
    assert_one_message(data, "`config_version` is required")


@pytest.mark.parametrize("version", [2, 0, "1", True, 1.5])
def test_wrong_config_version(version):
    assert_one_message(made(config_version=version), "`config_version` must be 1")


def test_no_channels():
    assert problems(made(channels=[])) == ["`channels` needs at least one channel."]
    data = made()
    del data["channels"]
    assert problems(data) == ["`channels` needs at least one channel."]
    assert problems(made(channels=None)) == ["`channels` needs at least one channel."]


def test_channel_without_an_index():
    assert_one_message(made(channels=[{"name": "x"}]), "`channels[0].index` is required")


@pytest.mark.parametrize("bad", [-1, 1.5, "2", True])
def test_channel_index_must_be_a_whole_number_of_zero_or_more(bad):
    assert_one_message(made(channels=[{"index": bad}]), "`channels[0].index` must be a whole number")


def test_repeated_channel_index():
    data = made(channels=[{"index": 1}, {"index": 2}, {"index": 1}])
    assert_one_message(data, "`channels[2].index`", "repeats channel 1", "`channels[0].index`")


# --- rules that depend on other settings -------------------------------------------


def test_manual_threshold_needs_a_value():
    data = made(channels=[{"index": 2, "threshold": {"mode": "manual"}}])
    assert_one_message(data, "`channels[0].threshold.value`", "`manual`")


def test_manual_threshold_with_a_value_is_valid():
    data = made(channels=[{"index": 2, "threshold": {"mode": "manual", "value": 18}}])
    assert parse_config(data).channels[0].threshold.value == 18


def test_calibrated_threshold_needs_a_filter():
    for filter_text in ("", "   ", None):
        threshold = {"mode": "calibrated", "calibration_filter": filter_text}
        data = made(channels=[{"index": 2, "threshold": threshold}])
        assert_one_message(data, "`channels[0].threshold.calibration_filter`", "`calibrated`")


def test_calibrated_threshold_with_a_filter_is_valid():
    threshold = {"mode": "calibrated", "calibration_filter": "control", "lower_limit": 5}
    config = parse_config(made(channels=[{"index": 2, "threshold": threshold}]))
    assert config.channels[0].threshold.calibration_filter == "control"


def test_bailout_needs_a_limit():
    data = made(channels=[{"index": 2, "bailout": {"enabled": True}}])
    assert_one_message(data, "`channels[0].bailout.max_spots`", "`bailout.enabled`")


def test_bailout_with_a_limit_is_valid():
    data = made(channels=[{"index": 2, "bailout": {"enabled": True, "max_spots": 50000}}])
    assert parse_config(data).channels[0].bailout.max_spots == 50000


def test_bailout_limit_is_not_needed_while_bailout_is_off():
    data = made(channels=[{"index": 2, "bailout": {"enabled": False}}])
    assert parse_config(data).channels[0].bailout.max_spots is None


def test_label_files_need_a_folder_when_segmentation_is_on():
    data = made(segmentation={"enabled": True, "source": "label_files"})
    assert_one_message(data, "`segmentation.label_folder`", "`label_files`")


def test_label_files_need_no_folder_while_segmentation_is_off():
    data = made(segmentation={"enabled": False, "source": "label_files"})
    assert parse_config(data).segmentation.label_folder == ""


def test_cellpose_segmentation_needs_no_folder():
    data = made(segmentation={"enabled": True, "source": "cellpose"})
    assert parse_config(data).segmentation.enabled


@pytest.mark.parametrize("value", [0.05, 0.4, 1])
def test_cellpose_mask_size_limit_accepted(value):
    data = made(segmentation={"cellpose": {"max_size_fraction": value}})
    assert parse_config(data).segmentation.cellpose.max_size_fraction == value


@pytest.mark.parametrize("value", [0, -0.2, 1.5, "big"])
def test_cellpose_mask_size_limit_out_of_range(value):
    data = made(segmentation={"cellpose": {"max_size_fraction": value}})
    assert_one_message(
        data, "`segmentation.cellpose.max_size_fraction` must be a number above 0 and up to 1", f"found `{value}`"
    )


def test_local_input_needs_nothing_more_at_load_time():
    data = made(run={"input": {"source": "local", "folder": "", "filter": ""}})
    assert parse_config(data).run.input.folder == ""


@pytest.mark.parametrize("bad", [0, -2, 1.5, "4", "many", True, False, None, [2]])
def test_workers_must_be_auto_or_a_whole_number_of_one_or_more(bad):
    assert_one_message(made(run={"workers": bad}), "`run.workers`", "`auto`", "1 or more")


# --- wrong values ---------------------------------------------------------------


def test_text_where_a_number_is_expected():
    data = made(channels=[{"index": 2, "threshold": {"mode": "manual", "value": "high"}}])
    assert_one_message(data, "`channels[0].threshold.value` must be a number")


def test_yes_where_a_number_is_expected():
    # YAML reads yes and on as true.
    data = yaml.safe_load("microscope: {NA: yes}")
    messages = problems(made(**data))
    assert len(messages) == 1
    assert "`microscope.NA` must be a positive number" in messages[0]
    assert "yes and on as true" in messages[0]


def test_on_where_a_choice_is_expected():
    data = yaml.safe_load("outputs: {qc: {final: on}}")
    assert_one_message(made(**data), "`outputs.qc.final` must be one of", "found `true`")


def test_text_where_a_switch_is_expected():
    data = made(run={"keep_awake": "maybe"})
    assert_one_message(data, "`run.keep_awake` must be true or false")


def test_number_where_text_is_expected():
    data = made(run={"input": {"filter": 2024}})
    assert_one_message(data, "`run.input.filter` must be text")


def test_text_where_a_whole_number_is_expected():
    data = made(run={"seed": "zero"})
    assert_one_message(data, "`run.seed` must be a whole number")


def test_decimal_where_a_whole_number_is_expected():
    data = made(channels=[{"index": 2, "clusters": {"min_spots": 2.5}}])
    assert_one_message(data, "`channels[0].clusters.min_spots` must be a whole number")


def test_list_where_a_group_is_expected():
    data = made(microscope=[1, 2])
    assert_one_message(data, "`microscope` must be a group of settings")


def test_image_ids_must_be_a_list_of_whole_numbers():
    data = made(run={"input": {"omero": {"image_ids": [3, "x"]}}})
    assert_one_message(data, "`run.input.omero.image_ids[1]` must be a whole number")
    data = made(run={"input": {"omero": {"image_ids": 3}}})
    assert_one_message(data, "`run.input.omero.image_ids` must be a list")


def test_unknown_choice():
    data = made(channels=[{"index": 2, "threshold": {"mode": "automatic"}}])
    assert_one_message(
        data,
        "`channels[0].threshold.mode` must be one of",
        "`manual`",
        "`auto`",
        "`calibrated`",
        "found `automatic`",
    )


def test_two_mistakes_in_one_file_are_both_reported():
    data = made(
        microscope={"NA": "high"},
        channels=[{"index": 2, "clusters": {"nb_min_spot": 5}}],
    )
    messages = problems(data)
    assert len(messages) == 2
    assert any("`microscope.NA`" in message for message in messages)
    assert any("`channels[0].clusters.nb_min_spot`" in message for message in messages)


def test_many_mistakes_are_all_reported():
    data = made(
        config_version=3,
        image={"axes": "YX", "voxel_size_nm": {"z": 5, "yx": 0}},
        channels=[
            {"index": 2, "threshold": {"mode": "manual"}},
            {"index": 3, "bailout": {"enabled": True}},
        ],
        run={"workers": 0},
    )
    messages = problems(data)
    for setting in (
        "`config_version`",
        "`image.voxel_size_nm.yx`",
        "`channels[0].threshold.value`",
        "`channels[1].bailout.max_spots`",
        "`run.workers`",
    ):
        assert any(setting in message for message in messages), setting
    assert len(messages) == len(set(messages))


def test_messages_hold_no_library_wording():
    data = made(
        config_version="x",
        run={"workers": "x", "seed": "x", "keep_awake": 3},
        microscope={"NA": "x", "type": 3},
        channels=[{"index": "x", "name": 5, "bogus": 1, "ex": [], "clusters": 5}],
        image={"axes": 4, "voxel_size_nm": {"yx": "x", "z": {}}},
    )
    text = " ".join(problems(data)).lower()
    for word in ("pydantic", "http", "validation", "input should", "type=", "float", "int_"):
        assert word not in text


# --- reading and writing YAML -----------------------------------------------------


def test_invalid_yaml(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("run: [unclosed\n  name: x\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert len(caught.value.messages) == 1
    assert "`bad.yaml` is not a valid settings file" in caught.value.messages[0]
    assert "line" in caught.value.messages[0]


def test_yaml_that_is_not_a_mapping(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must hold settings"):
        load_config(path)


def test_empty_file(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="must hold settings"):
        load_config(path)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="was not found"):
        load_config(tmp_path / "nothing.yaml")


def test_yaml_cannot_run_code(tmp_path):
    path = tmp_path / "unsafe.yaml"
    path.write_text("run: !!python/object/apply:os.system ['echo hi']\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not a valid settings file"):
        load_config(path)


def test_error_text_lists_every_message():
    error = ConfigError(["first", "second"])
    assert error.messages == ["first", "second"]
    assert "first" in str(error) and "second" in str(error)
    assert str(ConfigError("only one")) == "only one"


def test_names_with_accents_and_spaces_survive_a_save(tmp_path):
    data = made(
        run={"name": "série 1", "input": {"folder": "données brutes/a b", "filter": "é"}},
        channels=[{"index": 2, "name": "Ago1 Q570 µ"}],
    )
    saved = tmp_path / "saved.yaml"
    save_config(parse_config(data), saved)
    config = load_config(saved)
    assert config.run.input.folder == "données brutes/a b"
    assert config.channels[0].name == "Ago1 Q570 µ"


# --- folders ------------------------------------------------------------------------


def test_relative_folders_start_at_the_config_file_folder(tmp_path):
    folder = tmp_path / "experiment one"
    folder.mkdir()
    data = made(
        run={"input": {"folder": "images"}, "output_folder": "results/run 1"},
        segmentation={"enabled": True, "source": "label_files", "label_folder": "../labels"},
    )
    config = load_config(write_yaml(folder / "config.yaml", data))
    assert config.config_folder == Path(os.path.abspath(folder))
    assert config.full_input_folder() == Path(os.path.abspath(folder / "images"))
    assert config.full_output_folder() == Path(os.path.abspath(folder / "results" / "run 1"))
    assert config.full_label_folder() == Path(os.path.abspath(tmp_path / "labels"))


def test_a_dot_means_the_config_file_folder(crop_config_path, test_kit_folder):
    config = load_config(crop_config_path)
    assert config.full_input_folder() == Path(os.path.abspath(test_kit_folder))
    assert config.full_label_folder() == Path(os.path.abspath(test_kit_folder))


def test_full_paths_are_kept_as_they_are(tmp_path):
    other = tmp_path / "elsewhere"
    data = made(run={"input": {"folder": str(other)}})
    config = load_config(write_yaml(tmp_path / "config.yaml", data))
    assert config.full_input_folder() == Path(os.path.abspath(other))


def test_empty_folders_have_no_full_path(tmp_path):
    config = load_config(write_yaml(tmp_path / "config.yaml", made()))
    assert config.full_input_folder() is None
    assert config.full_output_folder() is None
    assert config.full_label_folder() is None


def test_a_config_not_read_from_a_file_uses_the_current_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = parse_config(made(run={"input": {"folder": "images"}}))
    assert config.config_folder is None
    assert config.full_input_folder() == Path(os.path.abspath(tmp_path / "images"))


def test_with_config_folder(tmp_path):
    config = parse_config(made(run={"input": {"folder": "images"}}))
    moved = config.with_config_folder(tmp_path)
    assert moved.full_input_folder() == Path(os.path.abspath(tmp_path / "images"))
    assert config.config_folder is None


def test_with_full_paths_fills_in_every_folder(tmp_path):
    data = made(
        run={"input": {"folder": "images"}, "output_folder": ""},
        segmentation={"enabled": True, "source": "label_files", "label_folder": "labels"},
    )
    config = load_config(write_yaml(tmp_path / "config.yaml", data))
    full = config.with_full_paths()
    assert full.run.input.folder == os.path.abspath(tmp_path / "images")
    assert full.segmentation.label_folder == os.path.abspath(tmp_path / "labels")
    assert full.run.output_folder == ""
    assert Path(full.run.input.folder).is_absolute()
    assert config.run.input.folder == "images"


def test_with_full_paths_keeps_everything_else(crop_config_path):
    config = load_config(crop_config_path)
    full = config.with_full_paths()
    expected = config.to_dict()
    expected["run"]["input"]["folder"] = full.run.input.folder
    expected["segmentation"]["label_folder"] = full.segmentation.label_folder
    assert full.to_dict() == expected


def test_full_paths_saved_and_loaded_from_another_folder_still_point_to_the_same_place(
    tmp_path,
):
    source = tmp_path / "source"
    source.mkdir()
    config = load_config(write_yaml(source / "config.yaml", made(run={"input": {"folder": "images"}})))
    run_config = tmp_path / "results" / "run_config.yaml"
    save_config(config.with_full_paths(), run_config)
    assert load_config(run_config).full_input_folder() == Path(os.path.abspath(source / "images"))


def test_equal_configs_from_different_folders_are_equal(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = load_config(write_yaml(tmp_path / "a" / "config.yaml", made()))
    second = load_config(write_yaml(tmp_path / "b" / "config.yaml", made()))
    assert first == second


# --- the resolved block --------------------------------------------------------------


RESOLVED = {"images": ["a.tif", "b.tif"], "thresholds": {2: 14.5, 4: 20}}


def test_resolved_block_is_optional_and_absent_by_default():
    config = parse_config(MINIMAL)
    assert config.resolved is None
    assert "resolved" not in config.to_dict()


def test_resolved_block_loads_and_round_trips(tmp_path):
    data = made(channels=[{"index": 2}, {"index": 4}], resolved=RESOLVED)
    config = parse_config(data)
    assert config.resolved.images == ["a.tif", "b.tif"]
    assert config.resolved.thresholds == {2: 14.5, 4: 20}
    saved = tmp_path / "run_config.yaml"
    save_config(config, saved)
    again = load_config(saved)
    assert again == config
    assert again.resolved.thresholds == {2: 14.5, 4: 20}


def test_resolved_block_can_be_empty_or_partial():
    assert parse_config(made(resolved={})).resolved.images == []
    assert parse_config(made(resolved={"images": ["a.tif"]})).resolved.thresholds == {}


def test_resolved_threshold_for_an_unknown_channel():
    data = made(resolved={"images": [], "thresholds": {5: 1.0}})
    assert_one_message(data, "`resolved.thresholds.5`", "channel 5", "`channels`")


def test_resolved_threshold_must_be_a_number():
    data = made(resolved={"images": [], "thresholds": {2: "high"}})
    assert_one_message(data, "`resolved.thresholds.2` must be a number")


def test_resolved_threshold_channel_must_be_a_whole_number():
    data = made(resolved={"images": [], "thresholds": {"red": 1.0}})
    assert_one_message(data, "`resolved.thresholds.red`", "not a channel number")


def test_resolved_block_unknown_setting():
    data = made(resolved={"imagez": []})
    assert_one_message(data, "`resolved.imagez`", "did you mean `images`?")


def test_with_resolved_and_without_resolved():
    config = parse_config(made(channels=[{"index": 2}, {"index": 4}]))
    filled = config.with_resolved(["a.tif"], {4: 12.5})
    assert filled.resolved.images == ["a.tif"]
    assert filled.resolved.thresholds == {4: 12.5}
    assert config.resolved is None
    assert filled.without_resolved() == config


# --- overrides ---------------------------------------------------------------------------


def config_with_resolved(tmp_path):
    data = made(
        run={
            "input": {"folder": "images", "filter": "old", "omero": {"dataset_id": 7}},
            "output_folder": "out",
            "workers": 2,
        },
        resolved={"images": ["a.tif"], "thresholds": {2: 9.5}},
    )
    return load_config(write_yaml(tmp_path / "config.yaml", data))


def test_overrides_change_only_what_is_given(tmp_path):
    config = config_with_resolved(tmp_path)
    changed = apply_overrides(config)
    assert changed == config
    assert changed.resolved is not None
    assert changed.config_folder == config.config_folder


def test_overrides_do_not_change_the_original(tmp_path):
    config = config_with_resolved(tmp_path)
    before = config.to_dict()
    apply_overrides(config, input_folder="x", filter="y", workers=3)
    assert config.to_dict() == before


def test_new_input_folder_drops_resolved(tmp_path, monkeypatch):
    config = config_with_resolved(tmp_path)
    monkeypatch.chdir(tmp_path)
    changed = apply_overrides(config, input_folder="new images")
    assert changed.resolved is None
    assert changed.run.input.folder == os.path.abspath(tmp_path / "new images")
    assert changed.run.input.filter == "old"


def test_new_filter_drops_resolved(tmp_path):
    changed = apply_overrides(config_with_resolved(tmp_path), filter="control")
    assert changed.resolved is None
    assert changed.run.input.filter == "control"


def test_an_empty_filter_is_a_new_filter(tmp_path):
    changed = apply_overrides(config_with_resolved(tmp_path), filter="")
    assert changed.resolved is None
    assert changed.run.input.filter == ""


def test_new_dataset_id_drops_resolved_and_replaces_image_ids(tmp_path):
    config = apply_overrides(config_with_resolved(tmp_path), image_ids=[1, 2])
    changed = apply_overrides(config.with_resolved(["a"]), dataset_id=12)
    assert changed.resolved is None
    assert changed.run.input.omero.dataset_id == 12
    assert changed.run.input.omero.image_ids == []


def test_new_image_ids_drop_resolved_and_replace_the_dataset_id(tmp_path):
    changed = apply_overrides(config_with_resolved(tmp_path), image_ids=[5, 6, 7])
    assert changed.resolved is None
    assert changed.run.input.omero.image_ids == [5, 6, 7]
    assert changed.run.input.omero.dataset_id is None


def test_output_folder_and_workers_keep_resolved(tmp_path, monkeypatch):
    config = config_with_resolved(tmp_path)
    monkeypatch.chdir(tmp_path)
    changed = apply_overrides(config, output_folder="results", workers=4)
    assert changed.resolved == config.resolved
    assert changed.resolved.thresholds == {2: 9.5}
    assert changed.run.output_folder == os.path.abspath(tmp_path / "results")
    assert changed.run.workers == 4
    assert changed.run.input.folder == "images"


def test_workers_from_the_command_line_can_be_text(tmp_path):
    config = config_with_resolved(tmp_path)
    assert apply_overrides(config, workers="3").run.workers == 3
    assert apply_overrides(config, workers="auto").run.workers == "auto"


def test_bad_override_gives_a_message(tmp_path):
    config = config_with_resolved(tmp_path)
    with pytest.raises(ConfigError, match="`run.workers`"):
        apply_overrides(config, workers=0)
    with pytest.raises(ConfigError, match="`run.workers`"):
        apply_overrides(config, workers="many")
    with pytest.raises(ConfigError, match="`run.input.omero.dataset_id`"):
        apply_overrides(config, dataset_id="abc")


def test_overrides_on_a_config_that_was_not_read_from_a_file():
    config = parse_config(MINIMAL)
    changed = apply_overrides(config, filter="x", workers=2)
    assert (changed.run.input.filter, changed.run.workers) == ("x", 2)
    assert isinstance(changed, Config)


# --- values that the steps cannot use ------------------------------------------

REFUSED_SETTINGS = [
    # (settings text, message)
    ("channels: [{index: 0, decomposition: {alpha: 1.5}}]",
     "`channels[0].decomposition.alpha` must be a number from 0 to 1 (found `1.5`)."),
    ("channels: [{index: 0, decomposition: {alpha: -0.1}}]",
     "`channels[0].decomposition.alpha` must be a number from 0 to 1 (found `-0.1`)."),
    ("channels: [{index: 0, decomposition: {beta: 0}}]",
     "`channels[0].decomposition.beta` must be a positive number (found `0`)."),
    ("channels: [{index: 0, background: {radius_px: 0.5}}]",
     "`channels[0].background.radius_px` must be a number of 1 or more (found `0.5`)."),
    ("segmentation: {background: {radius_px: 0.9}}",
     "`segmentation.background.radius_px` must be a number of 1 or more (found `0.9`)."),
    ("channels: [{index: 0, clusters: {min_spots: 1}}]",
     "`channels[0].clusters.min_spots` must be a whole number of 2 or more (found `1`)."),
    ("segmentation: {cellpose: {min_size: -2}}",
     "`segmentation.cellpose.min_size` must be a whole number of -1 or more (found `-2`)."),
    ("segmentation: {cellpose: {model: ''}}",
     "`segmentation.cellpose.model` must name a Cellpose model, such as `cpsam_v2`, "
     "or give the full path to a model file."),
    ("segmentation: {cellpose: {model: }}",
     "`segmentation.cellpose.model` must name a Cellpose model, such as `cpsam_v2`, "
     "or give the full path to a model file."),
    ("channels: [{index: 0, threshold: {mode: manual, value: .nan}}]",
     "`channels[0].threshold.value` must be a number, not infinite and not `.nan` (found `.nan`)."),
    ("channels: [{index: 0, threshold: {mode: manual, value: .inf}}]",
     "`channels[0].threshold.value` must be a number, not infinite and not `.nan` (found `.inf`)."),
    ("channels: [{index: 0, threshold: {lower_limit: -.inf}}]",
     "`channels[0].threshold.lower_limit` must be a number, not infinite and not `.nan` (found `-.inf`)."),
    ("channels: [{index: 0, ex: .inf}]",
     "`channels[0].ex` must be a positive number, not infinite and not `.nan` (found `.inf`)."),
    ("microscope: {NA: .nan}",
     "`microscope.NA` must be a positive number, not infinite and not `.nan` (found `.nan`)."),
    ("channels: [{index: 0, decomposition: {alpha: .nan}}]",
     "`channels[0].decomposition.alpha` must be a number from 0 to 1, not infinite and not `.nan` (found `.nan`)."),
    ("segmentation: {cellpose: {cellprob_threshold: .inf}}",
     "`segmentation.cellpose.cellprob_threshold` must be a number, not infinite and not `.nan` (found `.inf`)."),
    ("resolved: {images: [a.tif], thresholds: {0: .nan}}",
     "`resolved.thresholds.0` must be a number, not infinite and not `.nan` (found `.nan`)."),
]


@pytest.mark.parametrize("text, message", REFUSED_SETTINGS)
def test_values_the_steps_cannot_use_are_refused(text, message):
    data = made(**yaml.safe_load(text))
    assert problems(data) == [message]


@pytest.mark.parametrize("text", [
    "channels: [{index: 0, decomposition: {alpha: 0, beta: 0.01}}]",
    "channels: [{index: 0, decomposition: {alpha: 1}}]",
    "channels: [{index: 0, background: {radius_px: 1}, clusters: {min_spots: 2}}]",
    "segmentation: {cellpose: {min_size: -1}, background: {radius_px: 1}}",
    "channels: [{index: 0, threshold: {mode: manual, value: -3, lower_limit: 0}}]",
])
def test_values_at_the_limits_are_accepted(text):
    parse_config(made(**yaml.safe_load(text)))
