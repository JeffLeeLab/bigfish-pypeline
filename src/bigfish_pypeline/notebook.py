"""Helpers for the Optimise notebook."""

import sys

from bigfish_pypeline import io, steps
from bigfish_pypeline.config import ConfigError

# Problems with the values a user has typed, or with the image: shown as one short message.
# Any other error keeps its full traceback.
PLAIN_PROBLEMS = (
    ConfigError,
    steps.ChannelError,
    io.ImageReadError,
    io.OmeroSessionEnded,
    FileNotFoundError,
    ConnectionError,
    ValueError,
)
# Problems that this package or the system words in plain English; for the others the
# name of the error is shown before the message.
_OWN_WORDS = (ConfigError, steps.ChannelError, io.ImageReadError, io.OmeroSessionEnded,
              FileNotFoundError, ConnectionError)


def problem_text(error):
    """One line for a problem: "Problem: " and the message, with the error's name
    before the message unless the message is the package's own plain sentence."""
    if isinstance(error, _OWN_WORDS):
        return f"Problem: {error}"
    return f"Problem: {type(error).__name__}: {error}"


def show_problems_plainly():
    """In a running notebook, show the problems of `PLAIN_PROBLEMS` as one red line
    (`problem_text`) instead of a long traceback. The cell still counts as failed.

    Returns True when this was set up, and False, doing nothing, when no IPython
    session is running.
    """
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    shell = get_ipython()
    if shell is None:
        return False

    def show(shell, error_type, error, traceback, tb_offset=None):
        print(problem_text(error), file=sys.stderr)
        return []

    shell.set_custom_exc(PLAIN_PROBLEMS, show)
    return True
