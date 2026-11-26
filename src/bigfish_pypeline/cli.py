"""The `bigfish-pypeline` command: `batch` runs a settings file, `check` looks it over."""

import argparse
import os
import shlex
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from bigfish_pypeline import __version__, io, outputs
from bigfish_pypeline.batch import BatchError, RunStoppedError, plan_run, run_batch
from bigfish_pypeline.config import ConfigError, apply_overrides, load_config
from bigfish_pypeline.segmentation import describe_planes

PROGRAM = "bigfish-pypeline"

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_CANCELLED = 130

DESCRIPTION = """\
Find RNA spots in smFISH images with Big-FISH, group them into clusters and
count them in cells. Everything a run needs is written in a settings file
(a .yaml file).
"""

EPILOG = """\
Examples:
  bigfish-pypeline check my_settings.yaml
  bigfish-pypeline batch my_settings.yaml
  bigfish-pypeline batch my_settings.yaml --input-folder D:\\images --workers 2

Run `bigfish-pypeline check --help` or `bigfish-pypeline batch --help` to see
the options of each command.
"""

BATCH_EPILOG = """\
Options given here are used instead of the same settings in the file.
Press Ctrl+C to cancel a run: the images that are already finished are kept.

The command ends with 0 when the run finished (even if some images failed),
1 when there was a problem, and 130 when the run was cancelled.
"""

CHECK_EPILOG = """\
Options given here are used instead of the same settings in the file.
Nothing is processed and no folder is made. When the images are on an OMERO
server, you are asked for your password. With Cellpose, the segmentation
channel is checked, but the device and the model are only checked when a
run starts.
"""


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def _add_run_options(parser):
    parser.add_argument("config", metavar="settings.yaml", help="the settings file to use")
    parser.add_argument(
        "--input-folder", metavar="FOLDER",
        help="folder with the images (instead of the one in the settings file)",
    )
    parser.add_argument(
        "--filter", metavar="TEXT",
        help="only use images whose file names contain this text",
    )
    parser.add_argument(
        "--output-folder", metavar="FOLDER",
        help="folder in which the new run folder is made",
    )
    parser.add_argument(
        "--workers", metavar="NUMBER",
        help="how many images to process at the same time: a whole number, "
             "or `auto` to let the program choose from your processor and memory",
    )


def make_parser():
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")
    commands = parser.add_subparsers(dest="command", title="commands", metavar="{batch,check}")

    batch = commands.add_parser(
        "batch",
        help="process the images listed by a settings file",
        description="Process every image listed by a settings file and save the results "
                    "in a new run folder.",
        epilog=BATCH_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_run_options(batch)

    check = commands.add_parser(
        "check",
        help="look over a settings file and list what a run would do",
        description="Look over a settings file and list the images and settings a run would use. "
                    "Nothing is processed or saved.",
        epilog=CHECK_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_run_options(check)
    return parser


def command_line(argv):
    """The command as typed, for the run record: the program name and its arguments,
    with quotes where an argument needs them on this system."""
    words = [PROGRAM] + [str(argument) for argument in argv]
    if sys.platform == "win32":
        return subprocess.list2cmdline(words)
    return shlex.join(words)


def _workers_option(text):
    """The value of `--workers`: a whole number of 1 or more, or "auto"."""
    if text is None:
        return None
    value = text.strip()
    if value.lower() == "auto":
        return "auto"
    if value.isdigit() and int(value) >= 1:
        return int(value)
    raise ConfigError(
        f"`--workers` must be `auto` or a whole number of 1 or more, for example 2 (you gave `{text}`)."
    )


def _load(arguments):
    """The settings file with the command-line options put on top."""
    workers = _workers_option(arguments.workers)
    config = load_config(arguments.config)
    return apply_overrides(
        config,
        input_folder=arguments.input_folder,
        filter=arguments.filter,
        output_folder=arguments.output_folder,
        workers=workers,
    )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _say(text=""):
    print(text, flush=True)


def _complain(error):
    """Print a problem as plain text, listing every message of a ConfigError."""
    messages = error.messages if isinstance(error, ConfigError) else [str(error)]
    if len(messages) == 1:
        text = f"Problem: {messages[0]}"
    else:
        text = f"{len(messages)} problems were found:\n" + "\n".join(f"  - {message}" for message in messages)
    print(text, file=sys.stderr, flush=True)
    print("Nothing was run.", file=sys.stderr, flush=True)


def _threshold_text(config, channel):
    threshold = channel.threshold
    if threshold.mode == "manual":
        return f"manual, threshold {threshold.value:g}"
    if threshold.mode == "auto":
        return "automatic, found separately for each image"
    known = config.resolved.thresholds if config.resolved is not None else {}
    if channel.index in known:
        return f"calibrated, threshold {known[channel.index]:g} (from the settings file, not calibrated again)"
    return f"calibrated on the images whose names contain `{threshold.calibration_filter}`"


def describe_plan(config, plan, config_path):
    """Lines saying what a run would do."""
    lines = [f"Settings file: {config_path}"]

    if config.run.input.source == "omero":
        settings = config.run.input.omero
        if config.resolved is not None or settings.dataset_id is None:
            where = "the image IDs given"
        else:
            where = f"dataset {settings.dataset_id}"
        lines.append(f"Input: OMERO server {settings.host}, {where}")
    else:
        lines.append(f"Input folder: {config.full_input_folder()}")

    lines.append(f"Images ({len(plan.images)}), in the order they would be processed:")
    width = len(str(len(plan.images)))
    for number, image in enumerate(plan.images, start=1):
        lines.append(f"  {number:>{width}}. {image.listed}")
    refused = [problem for problem in plan.problems if problem is not None]
    if refused:
        lines.append(f"Images that cannot be used ({len(refused)}); a run would list them as failed:")
        lines.extend(f"  - {problem}" for problem in refused)

    lines.append("FISH channels:")
    for channel in config.channels:
        name = f" ({channel.name})" if channel.name else ""
        lines.append(f"  channel {channel.index}{name}: {_threshold_text(config, channel)}")

    segmentation = config.segmentation
    if not segmentation.enabled:
        lines.append("Cell results: no (segmentation is switched off)")
    elif segmentation.source == "cellpose":
        planes = describe_planes((segmentation.z_planes.first, segmentation.z_planes.last))
        channel = f"channel {segmentation.channel}"
        if planes:
            channel += f", projection {planes}"
        lines.append(
            f"Cell results: yes, cells found by Cellpose (model {segmentation.cellpose.model}, "
            f"{channel}, device: {segmentation.device}). The device and "
            "the model are checked when the run starts."
        )
        if config.outputs.label_images:
            lines.append("Label images: saved in `labels/` in the run folder")
        else:
            lines.append("Label images: not kept (`outputs.label_images` is off)")
    else:
        lines.append(f"Cell results: yes, from the label files in {plan.label_folder}")

    root = outputs.output_root(config)
    run_name = f"{datetime.now():%Y-%m-%d_%H%M}_{outputs.safe_run_name(config.run.name)}"
    lines.append(f"Output: a new run folder, such as `{run_name}`, would be made in {root}")

    lines.append(f"Workers: {plan.workers_reason}")
    if plan.workers_warning:
        lines.append(f"Warning: {plan.workers_warning}")
    return lines


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _check(arguments):
    config = _load(arguments)
    plan = plan_run(config)
    try:
        lines = describe_plan(config, plan, Path(os.path.abspath(arguments.config)))
    finally:
        plan.close()
    for line in lines:
        _say(line)
    _say()
    _say("Nothing was processed and nothing was saved.")
    return EXIT_OK


def _batch(arguments):
    config = _load(arguments)
    # The runner shows the run folder, then how the run ended, with the number of
    # failed and skipped channels, as the last line.
    result = run_batch(config, config_file=Path(os.path.abspath(arguments.config)), show=_say,
                       command=arguments.command_line)
    if result.status == "finished":
        return EXIT_OK
    if result.status == "cancelled":
        return EXIT_CANCELLED
    return EXIT_PROBLEM


COMMANDS = {"batch": _batch, "check": _check}


def main(argv=None):
    """Run the command given in `argv` (default: the command line); returns the exit code."""
    parser = make_parser()
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else EXIT_PROBLEM
    if arguments.command is None:
        parser.print_help()
        return EXIT_OK
    arguments.command_line = command_line(argv)
    try:
        # omero-py may neither print its own messages nor set up logging for the program
        with io.plain_logging():
            return COMMANDS[arguments.command](arguments)
    except (ConfigError, BatchError) as error:
        _complain(error)
        return EXIT_PROBLEM
    except RunStoppedError as error:
        _say(f"Run folder: {error.run_folder}")
        print(str(error), file=sys.stderr, flush=True)
        return EXIT_PROBLEM
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr, flush=True)
        return EXIT_CANCELLED
    except Exception:
        # A problem nobody foresaw, outside a run. Python's own report is shown
        # for whoever looks into it, with any OMERO session key hidden.
        report = io.SESSION_KEY_PATTERN.sub("[hidden]", traceback.format_exc())
        print(
            "The command stopped because of an unexpected problem. "
            "Please pass on the lines below when you report it.",
            file=sys.stderr, flush=True,
        )
        print(report.rstrip(), file=sys.stderr, flush=True)
        return EXIT_PROBLEM


if __name__ == "__main__":
    sys.exit(main())
