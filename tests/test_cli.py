"""Tests for the command line: `bigfish-pypeline batch` and `bigfish-pypeline check`."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import tifffile
import yaml

from bigfish_pypeline import __version__, cli
from conftest import CROP_NAME
from synthetic import make_image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_image(path, seed=0):
    """A small two-channel 3D image with voxel sizes of 200 nm (Z) and 65 nm (Y, X)."""
    channels = [make_image((8, 64, 64), n_spots=8, seed=seed + channel)[0] for channel in range(2)]
    metadata = {"axes": "ZCYX", "unit": "um", "spacing": 0.2}
    tifffile.imwrite(
        path, np.stack(channels, axis=1), imagej=True, metadata=metadata,
        resolution=(1 / 0.065, 1 / 0.065),
    )
    return path


def write_config(path, input_folder):
    """A settings file for generated images: top-hat background, manual threshold 50."""
    data = {
        "config_version": 1,
        "run": {
            "name": "cli_test",
            "input": {"source": "local", "folder": str(input_folder)},
            "workers": 1,
            "keep_awake": False,
        },
        "image": {"axes": "ZCYX", "voxel_size_nm": {"z": 200, "yx": 65}},
        "channels": [
            {"index": index, "background": {"method": "tophat", "radius_px": 5},
             "threshold": {"mode": "manual", "value": 50}}
            for index in (0, 1)
        ],
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def images(tmp_path):
    """Two folders of generated images: `first` holds a_1 and a_2, `second` holds b_1, b_2 and b_3."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for number, name in enumerate(("a_1", "a_2")):
        write_image(first / f"{name}.tif", seed=number)
    for number, name in enumerate(("b_1", "b_2", "b_3")):
        write_image(second / f"{name}.tif", seed=10 + number)
    return first, second


def run_command(capsys, *arguments):
    """Run the command in this process: (exit code, text printed, text of messages)."""
    code = cli.main([str(argument) for argument in arguments])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_folder_from(output):
    """The run folder named in the last lines of the command's text."""
    lines = [line for line in output.splitlines() if line.startswith("Run folder: ")]
    assert lines, output
    folder = Path(lines[-1][len("Run folder: "):])
    assert folder.is_dir()
    return folder


def folder_contents(folder):
    return sorted(str(path.relative_to(folder)) for path in Path(folder).rglob("*"))


def installed_command():
    """The `bigfish-pypeline` program next to the Python that runs the tests, or None."""
    folders = [Path(sys.executable).parent, Path(sys.executable).parent / "Scripts"]
    found = shutil.which(cli.PROGRAM, path=os.pathsep.join(str(folder) for folder in folders))
    return found


@pytest.fixture(scope="module")
def kit_run(crop_config_path, tmp_path_factory):
    """`batch` on the test kit config."""
    output = tmp_path_factory.mktemp("kit_output")
    code = cli.main(["batch", str(crop_config_path), "--output-folder", str(output)])
    return code, output


# ---------------------------------------------------------------------------
# Test kit
# ---------------------------------------------------------------------------


def test_check_test_kit(crop_config_path, test_kit_folder, tmp_path, capsys):
    output = tmp_path / "results"
    before = folder_contents(test_kit_folder)
    code, out, err = run_command(capsys, "check", crop_config_path, "--output-folder", output)
    assert code == 0, err
    assert err == ""
    assert f"{CROP_NAME}.tif" in out
    assert "Images (1)" in out
    assert "channel 2 (jim-exon): manual, threshold 18" in out
    assert "Cell results: yes, from the label files in" in out
    assert str(output) in out
    assert "1 worker(s), as set in the config" in out
    assert not output.exists()
    assert folder_contents(tmp_path) == []
    assert folder_contents(test_kit_folder) == before


def test_batch_test_kit(kit_run):
    code, output = kit_run
    assert code == 0
    folders = [path for path in output.iterdir() if path.is_dir()]
    assert len(folders) == 1
    spots = pd.read_csv(folders[0] / "spots.csv")
    assert len(spots) == 692
    assert (folders[0] / "run_config.yaml").is_file()


def test_batch_test_kit_messages(crop_config_path, tmp_path, capsys):
    code, out, err = run_command(capsys, "batch", crop_config_path, "--output-folder", tmp_path / "out")
    assert code == 0, err
    assert f"{CROP_NAME}, channel 2: done, threshold 18, 692 spots" in out
    lines = out.splitlines()
    assert lines[-2] == "The run finished: 1 image(s) processed."
    assert lines[-1] == f"Run folder: {run_folder_from(out)}"
    assert run_folder_from(out).parent == tmp_path / "out"


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def test_options_override_the_file(images, tmp_path, capsys):
    first, second = images
    config = write_config(tmp_path / "settings.yaml", first)
    output = tmp_path / "out"

    code, out, _ = run_command(capsys, "check", config, "--output-folder", output)
    assert code == 0
    assert "Images (2)" in out
    assert "a_1.tif" in out and "b_1.tif" not in out

    code, out, _ = run_command(capsys, "check", config, "--input-folder", second, "--output-folder", output)
    assert code == 0
    assert "Images (3)" in out
    assert "b_1.tif" in out and "a_1.tif" not in out

    code, out, _ = run_command(
        capsys, "check", config, "--input-folder", second, "--filter", "b_2", "--output-folder", output
    )
    assert code == 0
    assert "Images (1)" in out
    assert "b_2.tif" in out and "b_1.tif" not in out
    assert not output.exists()


def test_batch_options_choose_other_images(images, tmp_path, capsys):
    first, second = images
    config = write_config(tmp_path / "settings.yaml", first)
    code, out, err = run_command(
        capsys, "batch", config, "--input-folder", second, "--filter", "b_1", "--workers", "1",
        "--output-folder", tmp_path / "out",
    )
    assert code == 0, err
    spots = pd.read_csv(run_folder_from(out) / "spots.csv")
    assert set(spots["image"]) == {"b_1"}


def test_workers_option(images, tmp_path, capsys):
    first, _ = images
    config = write_config(tmp_path / "settings.yaml", first)
    output = tmp_path / "out"

    code, out, _ = run_command(capsys, "check", config, "--workers", "2", "--output-folder", output)
    assert code == 0
    assert "2 worker(s), as set in the config" in out

    code, out, _ = run_command(capsys, "check", config, "--workers", "1", "--output-folder", output)
    assert code == 0
    assert "1 worker(s), as set in the config" in out

    code, out, _ = run_command(capsys, "check", config, "--workers", "auto", "--output-folder", output)
    assert code == 0
    assert "chosen automatically" in out

    code, out, err = run_command(capsys, "batch", config, "--workers", "auto", "--output-folder", output)
    assert code == 0, err
    assert "chosen automatically" in out


@pytest.mark.parametrize("value", ["lots", "0", "-1", "1.5", ""])
def test_bad_workers_value(images, tmp_path, capsys, value):
    first, _ = images
    config = write_config(tmp_path / "settings.yaml", first)
    code, out, err = run_command(capsys, "batch", config, f"--workers={value}", "--output-folder", tmp_path / "out")
    assert code == 1
    assert out == ""
    assert "`--workers` must be `auto` or a whole number of 1 or more" in err
    assert "Traceback" not in err
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# Problems
# ---------------------------------------------------------------------------


def test_config_with_two_mistakes(images, tmp_path, capsys):
    first, _ = images
    config = write_config(tmp_path / "settings.yaml", first)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["run"]["wokers"] = 2
    data["image"]["axes"] = "XYZ"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")

    for command in ("check", "batch"):
        code, out, err = run_command(capsys, command, config, "--output-folder", tmp_path / "out")
        assert code == 1
        assert out == ""
        assert "2 problems were found" in err
        assert "run.wokers" in err
        assert "image.axes" in err
        assert "Traceback" not in err
    assert not (tmp_path / "out").exists()


def test_missing_config_file(tmp_path, capsys):
    for command in ("check", "batch"):
        code, out, err = run_command(capsys, command, tmp_path / "nothing.yaml")
        assert code == 1
        assert out == ""
        assert "was not found" in err
        assert "Traceback" not in err


def test_filter_matching_no_image(images, tmp_path, capsys):
    first, _ = images
    config = write_config(tmp_path / "settings.yaml", first)
    for command in ("check", "batch"):
        code, out, err = run_command(
            capsys, command, config, "--filter", "no_such_image", "--output-folder", tmp_path / "out"
        )
        assert code == 1
        assert "No images in" in err and "no_such_image" in err
        assert "Traceback" not in err
    assert not (tmp_path / "out").exists()


def test_failed_image_is_reported(images, tmp_path, capsys):
    first, _ = images
    damaged = first / "a_2.tif"
    damaged.write_bytes(damaged.read_bytes()[:3000])
    config = write_config(tmp_path / "settings.yaml", first)
    code, out, err = run_command(capsys, "batch", config, "--output-folder", tmp_path / "out")
    assert code == 0, err
    lines = out.splitlines()
    assert "1 of 2 image(s) had a channel that failed" in lines[-3]
    assert lines[-2] == "The run finished: 2 image(s) processed."
    assert lines[-1].startswith("Run folder: ")


# ---------------------------------------------------------------------------
# Repeating a run
# ---------------------------------------------------------------------------


def test_repeat_run_from_run_config(images, tmp_path, capsys):
    first, second = images
    config = write_config(tmp_path / "settings.yaml", first)
    code, out, err = run_command(capsys, "batch", config, "--output-folder", tmp_path / "out")
    assert code == 0, err
    first_run = run_folder_from(out)
    run_config = first_run / "run_config.yaml"
    assert "resolved" in yaml.safe_load(run_config.read_text(encoding="utf-8"))

    code, out, err = run_command(capsys, "batch", run_config, "--output-folder", tmp_path / "again")
    assert code == 0, err
    second_run = run_folder_from(out)
    assert second_run != first_run
    one, two = (pd.read_csv(folder / "spots.csv") for folder in (first_run, second_run))
    pd.testing.assert_frame_equal(one, two)

    # Another filter starts afresh: the images are listed again.
    code, out, err = run_command(
        capsys, "batch", run_config, "--input-folder", second, "--filter", "b_3",
        "--output-folder", tmp_path / "other",
    )
    assert code == 0, err
    other_run = run_folder_from(out)
    resolved = yaml.safe_load((other_run / "run_config.yaml").read_text(encoding="utf-8"))["resolved"]
    assert resolved["images"] == ["b_3.tif"]

    code, out, _ = run_command(capsys, "check", run_config, "--filter", "a_1", "--output-folder", tmp_path / "x")
    assert code == 0
    assert "Images (1)" in out


def test_repeat_run_with_missing_image(images, tmp_path, capsys):
    first, _ = images
    config = write_config(tmp_path / "settings.yaml", first)
    code, out, err = run_command(capsys, "batch", config, "--output-folder", tmp_path / "out")
    assert code == 0, err
    run_config = run_folder_from(out) / "run_config.yaml"
    (first / "a_2.tif").unlink()
    code, out, err = run_command(capsys, "check", run_config, "--output-folder", tmp_path / "out")
    assert code == 1
    assert "a_2.tif" in err
    assert "Traceback" not in err


# ---------------------------------------------------------------------------
# Help, version and the installed command
# ---------------------------------------------------------------------------


def test_no_command_prints_help(capsys):
    code, out, _ = run_command(capsys)
    assert code == 0
    assert "bigfish-pypeline check my_settings.yaml" in out
    assert "batch" in out and "check" in out
    assert "app" not in out.split("commands:")[1].split("Examples:")[0]


def test_help_and_version_in_process(capsys):
    code, out, _ = run_command(capsys, "--version")
    assert code == 0
    assert out.strip() == f"{cli.PROGRAM} {__version__}"

    code, out, _ = run_command(capsys, "--help")
    assert code == 0
    assert "settings file" in out

    code, out, _ = run_command(capsys, "batch", "--help")
    assert code == 0
    assert "--workers" in out and "Ctrl+C" in out


def test_installed_command(crop_config_path, tmp_path):
    command = installed_command()
    if command is None:
        pytest.skip("the bigfish-pypeline command is not installed next to this Python")
    work = tmp_path / "work"
    work.mkdir()

    version = subprocess.run([command, "--version"], cwd=work, capture_output=True, text=True)
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == f"bigfish-pypeline {__version__}"

    output = tmp_path / "results"
    check = subprocess.run(
        [command, "check", str(crop_config_path), "--output-folder", str(output)],
        cwd=work, capture_output=True, text=True,
    )
    assert check.returncode == 0, check.stderr
    assert f"{CROP_NAME}.tif" in check.stdout
    assert not output.exists()
    assert list(work.iterdir()) == []


def test_python_module(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "bigfish_pypeline.cli", "--version"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"bigfish-pypeline {__version__}"
