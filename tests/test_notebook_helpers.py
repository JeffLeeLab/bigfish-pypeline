"""Tests for the helpers of the Optimise notebook (notebook.py)."""

import subprocess
import sys
import textwrap

import pytest

from bigfish_pypeline import io, notebook, steps
from bigfish_pypeline.config import ConfigError


@pytest.mark.parametrize("error", [
    ConfigError("`channels[0].threshold.mode` must be one of `manual`, `auto` or `calibrated`."),
    steps.ChannelError("no calibrated threshold for channel 2"),
    io.ImageReadError("crop.tif: channel 5 does not exist"),
    io.OmeroSessionEnded("The OMERO session has ended."),
    FileNotFoundError("Folder not found: images"),
    ConnectionError("Could not connect to OMERO server at host:4064."),
])
def test_the_packages_own_problems_are_shown_as_their_message_alone(error):
    assert notebook.problem_text(error) == f"Problem: {error}"


def test_a_value_error_is_shown_with_its_name():
    error = ValueError("The start and end points are the same.")

    assert notebook.problem_text(error) == "Problem: ValueError: The start and end points are the same."


def test_several_config_problems_are_shown_one_per_line():
    error = ConfigError(["first problem", "second problem"])

    assert notebook.problem_text(error) == "Problem: - first problem\n- second problem"


def test_the_problems_shown_plainly_are_the_expected_ones_and_other_errors_are_not():
    assert issubclass(ConfigError, notebook.PLAIN_PROBLEMS)
    assert issubclass(io.OmeroConnectionLost, notebook.PLAIN_PROBLEMS)
    for other in (KeyError, IndexError, ZeroDivisionError, MemoryError):
        assert not issubclass(other, notebook.PLAIN_PROBLEMS)


def test_outside_a_notebook_nothing_is_set_up_and_nothing_happens():
    assert notebook.show_problems_plainly() is False


def test_in_an_ipython_session_the_handler_is_installed(tmp_path):
    script = textwrap.dedent("""
        from IPython.testing.globalipapp import start_ipython
        ip = start_ipython()
        from bigfish_pypeline import notebook
        assert notebook.show_problems_plainly() is True
        assert ip.custom_exceptions == notebook.PLAIN_PROBLEMS
        print("ok")
    """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=tmp_path)

    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout
