from __future__ import annotations

import yaml

from config_export import generate_yaml


def parse_generated_yaml(yaml_text):
    content_lines = [line for line in yaml_text.splitlines() if not line.startswith("#")]
    return yaml.safe_load("\n".join(content_lines))


def test_generate_yaml_for_auto_threshold_single_channel():
    yaml_text = generate_yaml(
        voxel_size_yx=65,
        voxel_size_z=200,
        ex=570,
        em=610,
        na=1.45,
        ri=1.45,
        microscope="confocal",
        bg_radius=5,
        channels=[3],
        auto_threshold=True,
        manual_thresholds={},
        alpha=0.5,
        beta=1,
        subpixel_fitting_mode=False,
        bf_radius=600,
        nb_min_spots=12,
    )
    config = parse_generated_yaml(yaml_text)
    assert config["channels"] == [3]
    assert config["auto_threshold"] is True
    assert config["smFISH_ch1"] == 3
    assert config["voxel_size_yx"] == 65


def test_generate_yaml_for_two_manual_channels():
    yaml_text = generate_yaml(
        voxel_size_yx=65,
        voxel_size_z=200,
        ex=570,
        em=610,
        na=1.45,
        ri=1.45,
        microscope="confocal",
        bg_radius=5,
        channels=[2, 3],
        auto_threshold=False,
        manual_thresholds={2: 50, 3: 30},
        alpha=0.5,
        beta=1,
        subpixel_fitting_mode=True,
        bf_radius=400,
        nb_min_spots=5,
    )
    config = parse_generated_yaml(yaml_text)
    assert config["smFISH_ch1"] == 2
    assert config["smFISH_ch1_thresh"] == 50
    assert config["smFISH_ch2"] == 3
    assert config["smFISH_ch2_thresh"] == 30
    assert config["subpixel_fitting_mode"] is True


def test_generate_yaml_rejects_manual_export_for_more_than_two_channels():
    try:
        generate_yaml(
            voxel_size_yx=65,
            voxel_size_z=200,
            ex=570,
            em=610,
            na=1.45,
            ri=1.45,
            microscope="confocal",
            bg_radius=5,
            channels=[1, 2, 3],
            auto_threshold=False,
            manual_thresholds={1: 10, 2: 20, 3: 30},
            alpha=0.5,
            beta=1,
            subpixel_fitting_mode=False,
            bf_radius=600,
            nb_min_spots=12,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected generate_yaml to reject more than two manual-threshold channels.")


def test_generate_yaml_requires_saved_manual_thresholds():
    try:
        generate_yaml(
            voxel_size_yx=65,
            voxel_size_z=200,
            ex=570,
            em=610,
            na=1.45,
            ri=1.45,
            microscope="confocal",
            bg_radius=5,
            channels=[2],
            auto_threshold=False,
            manual_thresholds={},
            alpha=0.5,
            beta=1,
            subpixel_fitting_mode=False,
            bf_radius=600,
            nb_min_spots=12,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected generate_yaml to require a manual threshold for saved manual channels.")