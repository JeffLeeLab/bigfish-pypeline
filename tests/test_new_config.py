"""Tests for starting a config from presets and for changing a config with checking."""

import copy
import itertools

import pytest

from bigfish_pypeline.config import (
    ASSAY_AMPLIFIED,
    ASSAY_SMFISH,
    ASSAY_TYPES,
    ConfigError,
    add_channel,
    load_config,
    new_config,
    parse_config,
    remove_channel,
    save_config,
    update_channel,
    update_config,
)

VOXEL = {"yx": 65, "z": 200}

# Switches of spec 5.2: decomposition and clusters, by assay type.
SWITCHES = {
    ASSAY_SMFISH: {"decomposition": True, "clusters": True},
    ASSAY_AMPLIFIED: {"decomposition": False, "clusters": False},
}


def channel(index=2, assay_type=ASSAY_SMFISH, **more):
    return {"index": index, "name": f"ch{index}", "ex": 570, "em": 610, "assay_type": assay_type, **more}


def messages(call, *args):
    with pytest.raises(ConfigError) as caught:
        call(*args)
    return caught.value.messages


def default_config_data(channels, cell_results=False, axes="ZCYX", voxel=VOXEL):
    """The settings every default gives, written out without the presets."""
    return {
        "config_version": 1,
        "image": {"axes": axes, "voxel_size_nm": voxel},
        "channels": channels,
        "segmentation": {"enabled": cell_results},
    }


# --- presets ------------------------------------------------------------------------------


def test_assay_type_names():
    assert ASSAY_TYPES == ("smFISH", "amplified")


@pytest.mark.parametrize("assay_type", ASSAY_TYPES)
@pytest.mark.parametrize("cell_results", [False, True])
def test_each_preset_gives_the_switches_of_the_specification(assay_type, cell_results):
    config = new_config("ZCYX", VOXEL, [channel(2, assay_type)], cell_results=cell_results)
    only = config.channels[0]
    assert only.decomposition.enabled is SWITCHES[assay_type]["decomposition"]
    assert only.clusters.enabled is SWITCHES[assay_type]["clusters"]
    assert only.subpixel.enabled is False
    assert only.measurements.snr is False and only.measurements.intensity is False
    assert config.segmentation.enabled is cell_results


@pytest.mark.parametrize("assay_type", ASSAY_TYPES)
@pytest.mark.parametrize("cell_results", [False, True])
def test_a_preset_changes_only_switches(assay_type, cell_results):
    config = new_config("ZCYX", VOXEL, [channel(2, assay_type)], cell_results=cell_results)
    expected = parse_config(
        default_config_data([{"index": 2, "name": "ch2", "ex": 570, "em": 610}], cell_results)
    ).to_dict()
    for group in ("decomposition", "clusters"):
        expected["channels"][0][group]["enabled"] = SWITCHES[assay_type][group]
    assert config.to_dict() == expected


def test_each_channel_has_its_own_assay_type():
    config = new_config(
        "ZCYX", VOXEL, [channel(1, ASSAY_AMPLIFIED), channel(2, ASSAY_SMFISH), channel(3, ASSAY_AMPLIFIED)]
    )
    assert [c.index for c in config.channels] == [1, 2, 3]
    assert [c.clusters.enabled for c in config.channels] == [False, True, False]
    assert [c.decomposition.enabled for c in config.channels] == [False, True, False]


def test_channel_names_and_wavelengths_are_kept():
    config = new_config("ZCYX", VOXEL, [{"index": 1, "name": "Ago1", "ex": 640, "em": 670, "assay_type": "smFISH"}])
    only = config.channels[0]
    assert (only.index, only.name, only.ex, only.em) == (1, "Ago1", 640, 670)


def test_other_channel_settings_win_over_the_assay_type():
    config = new_config(
        "ZCYX",
        VOXEL,
        [channel(2, ASSAY_AMPLIFIED, clusters={"enabled": True, "radius_nm": 300}, threshold={"mode": "auto"})],
    )
    assert config.channels[0].clusters.enabled is True
    assert config.channels[0].clusters.radius_nm == 300
    assert config.channels[0].clusters.min_spots == 4
    assert config.channels[0].decomposition.enabled is False


def test_microscope_settings_are_optional():
    assert new_config("ZCYX", VOXEL, [channel()]).microscope.type == "confocal"
    config = new_config("ZCYX", VOXEL, [channel()], microscope={"type": "widefield", "NA": 1.3})
    assert (config.microscope.type, config.microscope.NA, config.microscope.RI) == ("widefield", 1.3, 1.45)


def test_a_two_dimensional_layout():
    config = new_config("YX", {"yx": 65}, [channel(0)])
    assert config.image.axes == "YX"
    assert config.image.voxel_size_nm.z is None
    config = new_config("CYX", {"yx": 65, "z": None}, [channel(1)])
    assert config.image.voxel_size_nm.z is None


def test_config_folder_is_kept(tmp_path):
    assert new_config("ZCYX", VOXEL, [channel()], config_folder=tmp_path).config_folder == tmp_path
    assert new_config("ZCYX", VOXEL, [channel()]).config_folder is None


@pytest.mark.parametrize("assay_type", ASSAY_TYPES)
def test_result_saves_and_loads_equal(tmp_path, assay_type):
    config = new_config("ZCYX", VOXEL, [channel(1, assay_type), channel(2)], cell_results=True)
    save_config(config, tmp_path / "config.yaml")
    assert load_config(tmp_path / "config.yaml") == config


def test_result_passes_the_settings_check_unchanged():
    config = new_config("ZCYX", VOXEL, [channel(1, ASSAY_AMPLIFIED), channel(2)], cell_results=True)
    assert parse_config(config.to_dict()) == config


def test_presets_are_not_written_to_the_file(tmp_path):
    new = new_config("ZCYX", VOXEL, [channel(2, ASSAY_AMPLIFIED)])
    save_config(new, tmp_path / "config.yaml")
    assert "assay_type" not in (tmp_path / "config.yaml").read_text()


def test_unknown_assay_type_lists_the_choices():
    found = messages(new_config, "ZCYX", VOXEL, [channel(2, "HCR")])
    assert len(found) == 1
    assert found[0].startswith("`channels[0].assay_type` must be one of `smFISH` or `amplified` (found `HCR`)")
    assert "HCR or RNAscope" in found[0]


def test_misspelt_assay_type_suggests_the_name():
    found = messages(new_config, "ZCYX", VOXEL, [channel(2), channel(3, "smfish")])
    assert len(found) == 1 and "`channels[1].assay_type`" in found[0] and "Did you mean `smFISH`?" in found[0]


def test_missing_assay_type():
    found = messages(new_config, "ZCYX", VOXEL, [{"index": 2}])
    assert found == [
        "`channels[0].assay_type` is required and must be one of `smFISH` or `amplified`. "
        "Use `amplified` for amplified FISH such as HCR or RNAscope."
    ]


def test_assay_type_problem_comes_with_other_problems():
    found = messages(new_config, "ZCYX", {"yx": -1, "z": 200}, [channel(2, "HCR")])
    assert len(found) == 2
    assert any("assay_type" in m for m in found)
    assert any("`image.voxel_size_nm.yx` must be a positive number" in m for m in found)


def test_channel_must_be_a_dictionary():
    found = messages(new_config, "ZCYX", VOXEL, ["ch2"])
    assert len(found) == 1 and found[0].startswith("`channels[0]` must be written as `name: value` pairs")


@pytest.mark.parametrize("channels", [[], ()])
def test_at_least_one_channel(channels):
    assert messages(new_config, "ZCYX", VOXEL, channels) == ["`channels` needs at least one channel."]


def test_channels_must_be_a_list():
    assert "must be a list" in messages(new_config, "ZCYX", VOXEL, channel())[0]


def test_repeated_channel_index():
    found = messages(new_config, "ZCYX", VOXEL, [channel(2), channel(2)])
    assert len(found) == 1 and "repeats channel 2" in found[0]


@pytest.mark.parametrize(
    "axes, voxel, part",
    [
        ("ZXYC", VOXEL, "`image.axes` must be one of"),
        (None, VOXEL, "`image.axes` is required"),
        ("ZCYX", {"yx": 65}, "`image.voxel_size_nm.z` is needed for the 3D layout `ZCYX`"),
        ("ZCYX", {"z": 200}, "`image.voxel_size_nm.yx` is required"),
        ("ZCYX", None, "`image.voxel_size_nm.yx` is required"),
        ("YX", VOXEL, "`image.voxel_size_nm.z` must be left empty for the 2D layout `YX`"),
        ("ZCYX", {"yx": 0, "z": 200}, "`image.voxel_size_nm.yx` must be a positive number"),
    ],
)
def test_bad_layout_or_voxel_sizes(axes, voxel, part):
    found = messages(new_config, axes, voxel, [channel()])
    assert len(found) == 1 and part in found[0]


def test_bad_values_use_the_messages_of_the_settings_file():
    found = messages(new_config, "ZCYX", VOXEL, [channel(-1, ex=0, bogus=1)], "yes", {"type": "confocl", "NA": -1})
    assert "`channels[0].index` must be a whole number of 0 or more (found `-1`)." in found
    assert "`channels[0].ex` must be a positive number (found `0`)." in found
    assert "`channels[0].bogus` is not a known setting." in found
    assert "`segmentation.enabled` must be true or false (found `yes`)." in found
    assert "`microscope.type` must be one of `confocal`, `widefield` or `nipkow` (found `confocl`)." in found
    assert "`microscope.NA` must be a positive number (found `-1`)." in found


def test_inputs_are_not_changed():
    channels = [channel(2, ASSAY_AMPLIFIED, threshold={"mode": "auto"})]
    voxel = dict(VOXEL)
    before = copy.deepcopy((channels, voxel))
    new_config("ZCYX", voxel, channels)
    assert (channels, voxel) == before


def test_presets_cover_every_switch_combination():
    for assays in itertools.product(ASSAY_TYPES, repeat=2):
        config = new_config("ZCYX", VOXEL, [channel(i, a) for i, a in enumerate(assays)])
        assert [c.clusters.enabled for c in config.channels] == [a == ASSAY_SMFISH for a in assays]


# --- changing a config --------------------------------------------------------------------


@pytest.fixture
def config(tmp_path):
    base = new_config("ZCYX", VOXEL, [channel(0, ASSAY_AMPLIFIED), channel(2, ASSAY_SMFISH)])
    return base.with_config_folder(tmp_path)


def differences(first, second, path=""):
    """Paths of the settings that differ between two settings dictionaries."""
    found = []
    for name in sorted(set(first) | set(second)):
        left, right = first.get(name), second.get(name)
        if isinstance(left, dict) and isinstance(right, dict):
            found += differences(left, right, f"{path}{name}.")
        elif left != right:
            found.append(f"{path}{name}")
    return found


def test_update_config_changes_only_what_is_named(config):
    changed = update_config(config, {"segmentation": {"cellpose": {"diameter": 60}}})
    assert changed.segmentation.cellpose.diameter == 60
    assert differences(config.to_dict(), changed.to_dict()) == ["segmentation.cellpose.diameter"]


def test_update_config_several_groups_at_once(config):
    changed = update_config(
        config, {"run": {"name": "test", "input": {"filter": "abc"}}, "microscope": {"type": "widefield"}}
    )
    assert differences(config.to_dict(), changed.to_dict()) == ["microscope.type", "run.input.filter", "run.name"]


def test_update_config_does_not_change_the_config_given(config):
    before = config.to_dict()
    update_config(config, {"run": {"name": "other"}})
    assert config.to_dict() == before


def test_update_config_keeps_the_config_folder(config, tmp_path):
    assert update_config(config, {"run": {"name": "other"}}).config_folder == tmp_path


def test_update_config_replaces_lists(config):
    first = update_config(config, {"run": {"input": {"omero": {"image_ids": [1, 2, 3]}}}})
    second = update_config(first, {"run": {"input": {"omero": {"image_ids": [7]}}}})
    assert second.run.input.omero.image_ids == [7]


def test_update_config_can_empty_an_optional_value(config):
    first = update_config(config, {"segmentation": {"cellpose": {"diameter": 60}}})
    assert update_config(first, {"segmentation": {"cellpose": {"diameter": None}}}).segmentation.cellpose.diameter is None


def test_update_config_does_not_keep_the_dictionary_given(config):
    changes = {"run": {"input": {"omero": {"image_ids": [1, 2]}}}}
    changed = update_config(config, changes)
    changes["run"]["input"]["omero"]["image_ids"].append(3)
    assert changed.run.input.omero.image_ids == [1, 2]


def test_update_config_result_is_checked_as_a_whole(config):
    found = messages(update_config, config, {"segmentation": {"enabled": True, "source": "label_files"}})
    assert found == ["`segmentation.label_folder` is needed when `source` is `label_files`."]


def test_update_config_switching_to_a_2d_layout_needs_no_z(config):
    changed = update_config(config, {"image": {"axes": "CYX", "voxel_size_nm": {"z": None}}})
    assert changed.image.axes == "CYX"


def test_update_config_misspelt_name_gives_the_message_of_the_settings_file(config):
    assert messages(update_config, config, {"segmentation": {"cellpose": {"diamter": 60}}}) == [
        "`segmentation.cellpose.diamter` is not a known setting – did you mean `diameter`?"
    ]
    assert messages(update_config, config, {"segmentaton": {"enabled": True}}) == [
        "`segmentaton` is not a known setting – did you mean `segmentation`?"
    ]


def test_update_config_bad_values(config):
    found = messages(
        update_config, config, {"segmentation": {"cellpose": {"flow_threshold": -1}}, "run": {"workers": 0}}
    )
    assert "`segmentation.cellpose.flow_threshold` must be a number of 0 or more (found `-1`)." in found
    assert "`run.workers` must be `auto` or a whole number of 1 or more." in found


def test_update_config_needs_a_dictionary(config):
    assert "must be written as a dictionary" in messages(update_config, config, [("run", {})])[0]


def test_update_config_result_saves_and_loads_equal(config, tmp_path):
    changed = update_config(config, {"segmentation": {"enabled": True}, "run": {"name": "x"}})
    save_config(changed, tmp_path / "c.yaml")
    assert load_config(tmp_path / "c.yaml") == changed


def test_update_channel_changes_only_what_is_named(config):
    changed = update_channel(config, 2, {"threshold": {"mode": "manual", "value": 12}})
    assert changed.channels[1].threshold.mode == "manual" and changed.channels[1].threshold.value == 12
    assert differences(config.to_dict(), changed.to_dict()) == [
        "channels",
    ]
    assert differences(config.to_dict()["channels"][1], changed.to_dict()["channels"][1]) == [
        "threshold.mode",
        "threshold.value",
    ]
    assert changed.channels[0] == config.channels[0]


def test_update_channel_uses_the_channel_index_not_the_position(config):
    changed = update_channel(config, 0, {"name": "first"})
    assert [c.name for c in changed.channels] == ["first", "ch2"]


def test_update_channel_does_not_change_the_config_given_and_keeps_its_folder(config, tmp_path):
    before = config.to_dict()
    changed = update_channel(config, 2, {"clusters": {"radius_nm": 300}})
    assert config.to_dict() == before
    assert changed.config_folder == tmp_path


def test_update_channel_unknown_channel_names_the_channels_held(config):
    assert messages(update_channel, config, 5, {"name": "x"}) == [
        "Channel 5 is not in the settings; the settings hold channels 0 and 2."
    ]
    one = remove_channel(config, 0)
    assert messages(update_channel, one, 0, {}) == ["Channel 0 is not in the settings; the settings hold channel 2."]
    three = add_channel(config, channel(4))
    assert "channels 0, 2 and 4." in messages(update_channel, three, 1, {})[0]


@pytest.mark.parametrize("bad_index", [True, "2", 2.5, None])
def test_update_channel_index_must_be_one_of_the_channels(config, bad_index):
    assert "is not in the settings" in messages(update_channel, config, bad_index, {})[0]


def test_update_channel_misspelt_name(config):
    assert messages(update_channel, config, 2, {"threshold": {"mod": "manual"}}) == [
        "`channels[1].threshold.mod` is not a known setting – did you mean `mode`?"
    ]


def test_update_channel_bad_values(config):
    assert messages(update_channel, config, 2, {"threshold": {"mode": "manual"}}) == [
        "`channels[1].threshold.value` is needed when `mode` is `manual`: the threshold to use."
    ]
    assert messages(update_channel, config, 2, {"decomposition": {"alpha": 2}}) == [
        "`channels[1].decomposition.alpha` must be a number from 0 to 1 (found `2`)."
    ]


def test_update_channel_cannot_take_the_index_of_another_channel(config):
    assert "repeats channel 0" in messages(update_channel, config, 2, {"index": 0})[0]


def test_update_channel_needs_a_dictionary(config):
    assert "must be written as a dictionary" in messages(update_channel, config, 2, "manual")[0]


def test_add_channel(config, tmp_path):
    before = config.to_dict()
    added = add_channel(config, {"index": 1, "name": "Ago1", "ex": 640, "em": 670, "assay_type": ASSAY_AMPLIFIED})
    assert [c.index for c in added.channels] == [0, 2, 1]
    new = added.channels[2]
    assert (new.name, new.ex, new.em) == ("Ago1", 640, 670)
    assert (new.decomposition.enabled, new.clusters.enabled) == (False, False)
    assert added.channels[:2] == config.channels
    assert config.to_dict() == before
    assert added.config_folder == tmp_path


def test_add_channel_with_each_assay_type(config):
    smfish = add_channel(config, channel(1, ASSAY_SMFISH)).channels[2]
    amplified = add_channel(config, channel(1, ASSAY_AMPLIFIED)).channels[2]
    assert (smfish.decomposition.enabled, smfish.clusters.enabled) == (True, True)
    assert (amplified.decomposition.enabled, amplified.clusters.enabled) == (False, False)


def test_add_channel_assay_type_problems(config):
    found = messages(add_channel, config, channel(1, "HCR"))
    assert len(found) == 1 and found[0].startswith("`channel.assay_type` must be one of `smFISH` or `amplified`")
    assert "is required" in messages(add_channel, config, {"index": 1})[0]
    assert "`channel` must be written as" in messages(add_channel, config, 1)[0]


def test_add_channel_already_in_the_config(config):
    assert messages(add_channel, config, channel(2)) == [
        "Channel 2 is already in the settings; the settings hold channels 0 and 2."
    ]


def test_add_channel_bad_values(config):
    found = messages(add_channel, config, channel(1, ex=-5, bogus=1))
    assert "`channels[2].ex` must be a positive number (found `-5`)." in found
    assert "`channels[2].bogus` is not a known setting." in found
    assert "`channels[2].index` is required; it must be a whole number of 0 or more." in messages(
        add_channel, config, {"assay_type": ASSAY_SMFISH}
    )


def test_remove_channel(config, tmp_path):
    before = config.to_dict()
    removed = remove_channel(config, 0)
    assert [c.index for c in removed.channels] == [2]
    assert removed.channels[0] == config.channels[1]
    assert config.to_dict() == before
    assert removed.config_folder == tmp_path


def test_remove_channel_unknown_channel(config):
    assert messages(remove_channel, config, 7) == [
        "Channel 7 is not in the settings; the settings hold channels 0 and 2."
    ]


def test_the_last_channel_cannot_be_removed(config):
    assert messages(remove_channel, remove_channel(config, 0), 2) == ["`channels` needs at least one channel."]


def test_removing_a_channel_drops_its_calibrated_threshold(config):
    with_threshold = config.with_resolved(["a.tif"], {0: 5.0, 2: 7.0})
    removed = remove_channel(with_threshold, 0)
    assert removed.resolved.thresholds == {2: 7.0}


def test_add_and_remove_round_trip(config):
    assert remove_channel(add_channel(config, channel(1)), 1) == config


def test_a_notebook_sequence_gives_a_config_that_saves_and_loads(tmp_path):
    config = new_config("ZCYX", VOXEL, [channel(2)], cell_results=True)
    config = update_config(config, {"segmentation": {"channel": 1, "cellpose": {"diameter": 60}}})
    config = add_channel(config, channel(3, ASSAY_AMPLIFIED))
    config = update_channel(config, 3, {"threshold": {"mode": "manual", "value": 12}})
    save_config(config, tmp_path / "config.yaml")
    assert load_config(tmp_path / "config.yaml") == config
