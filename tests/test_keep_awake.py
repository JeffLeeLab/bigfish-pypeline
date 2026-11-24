"""Tests for keeping the computer awake during a batch run (`run.keep_awake`).

The macOS tests start the real `caffeinate` and run only on a Mac. The Windows
and Linux paths, and a `caffeinate` that is missing or fails, are tested with
stand-ins on every system. Every test ends with no `caffeinate` process left.
"""

import os
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import psutil
import pytest

from bigfish_pypeline import batch, cli
from bigfish_pypeline.config import save_config
from test_batch_run import local_config, log_text, run_fake, run_info, tiny_images

ON_MAC = sys.platform == "darwin" and shutil.which("caffeinate") is not None
mac_only = pytest.mark.skipif(not ON_MAC, reason="needs caffeinate on macOS")

SLEEP_NOTE = "a laptop still sleeps when its lid is closed"
KEPT_AWAKE_LINE = (
    "Keep awake: the computer is kept from sleeping on its own until the run ends "
    f"({SLEEP_NOTE})."
)
OFF_LINE = "Keep awake: off (`run.keep_awake` is off), so the computer may go to sleep during the run."
LINUX_LINE = "Keep awake: not available on Linux, so the computer may go to sleep during the run."
OTHER_LINE = "Keep awake: not available on this system, so the computer may go to sleep during the run."
WARNING_START = "Warning: the computer could not be kept awake ("
WARNING_END = "); the run goes on, and the computer may go to sleep."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def keep_awake_lines(run_folder):
    """Every line of run.log about keeping the computer awake, without the time."""
    return [
        line.split("  ", 1)[1] for line in log_text(run_folder).splitlines()
        if "Keep awake:" in line or "could not be kept awake" in line
    ]


def caffeinate_processes(pid=None):
    """The running `caffeinate` processes tied to process `pid` (default: this process)."""
    pid = os.getpid() if pid is None else pid
    found = []
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            command = process.info["cmdline"] or []
            if process.info["name"] == "caffeinate" and command[-2:] == ["-w", str(pid)]:
                found.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def wait_until_gone(pid=None, seconds=10):
    """True when no `caffeinate` tied to `pid` is left after at most `seconds`."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not caffeinate_processes(pid):
            return True
        time.sleep(0.1)
    return not caffeinate_processes(pid)


@pytest.fixture(autouse=True)
def no_caffeinate_left():
    yield
    left = caffeinate_processes()
    for process in left:
        process.kill()
    assert not left


class Seen:
    """Collects the number of `caffeinate` processes tied to this process while a run shows its lines."""

    def __init__(self, stop_on=None):
        self.counts = []
        self.stop_on = stop_on

    def __call__(self, text):
        self.counts.append(len(caffeinate_processes()))
        if self.stop_on is not None and text.startswith(self.stop_on):
            signal.raise_signal(signal.SIGINT)

    def during(self):
        """The most `caffeinate` processes seen at the same time during the run."""
        return max(self.counts, default=0)


class Calls:
    """A stand-in for the Windows call: keeps the flags and the thread of each call."""

    def __init__(self, result=1, error=None):
        self.flags = []
        self.threads = []
        self.result = result
        self.error = error

    def __call__(self, flags):
        self.flags.append(flags)
        self.threads.append(threading.current_thread())
        if self.error is not None:
            raise self.error
        return self.result


def windows_system(monkeypatch, calls):
    monkeypatch.setattr(batch, "_system_name", lambda: "Windows")
    monkeypatch.setattr(batch, "_set_execution_state", calls)


def nothing_may_start(monkeypatch):
    """Watch the processes started for keep-awake (those with the `-w` option).

    Returns the list that holds their commands. Other processes (the run
    record looks up the git commit) start as usual.
    """
    started = []
    real_popen = subprocess.Popen

    def popen(command, *args, **kwargs):
        if "-w" in command:
            started.append(command)
            raise AssertionError("no process may be started")
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(batch.subprocess, "Popen", popen)
    return started


def kept_awake(tmp_path, names=("a",), workers=1, **arguments):
    folder = tiny_images(tmp_path / "input", names)
    return local_config(folder, tmp_path / "out", workers=workers, keep_awake=True), arguments


def fail_in_the_run(monkeypatch):
    def broken(self):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(batch._Run, "process_images", broken)


# ---------------------------------------------------------------------------
# macOS: the real `caffeinate`
# ---------------------------------------------------------------------------


@mac_only
def test_mac_caffeinate_runs_during_a_run_and_is_gone_after(tmp_path):
    config, _ = kept_awake(tmp_path)
    seen = Seen()
    result = run_fake(config, show=seen)
    assert result.status == "finished"
    assert seen.during() == 1
    assert not caffeinate_processes()
    assert keep_awake_lines(result.run_folder) == [KEPT_AWAKE_LINE]


@mac_only
def test_mac_caffeinate_command(tmp_path, monkeypatch):
    """The command: no sleep when idle, ending with the process of the run."""
    commands = []
    real_popen = subprocess.Popen

    def popen(command, *args, **kwargs):
        if "-w" in command:
            commands.append(command)
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(batch.subprocess, "Popen", popen)
    config, _ = kept_awake(tmp_path)
    run_fake(config)
    [command] = commands
    assert Path(command[0]).name == "caffeinate"
    assert command[1:] == ["-i", "-w", str(os.getpid())]


@mac_only
def test_mac_caffeinate_starts_after_the_run_folder_line(tmp_path):
    config, _ = kept_awake(tmp_path)
    states = []
    result = run_fake(config, show=lambda text: states.append((text.split(":")[0], len(caffeinate_processes()))))
    names = [name for name, _ in states]
    assert names.index("Run folder") < names.index("Keep awake")
    assert dict(states)["Keep awake"] == 1
    assert result.status == "finished"
    assert not caffeinate_processes()


@mac_only
def test_mac_nothing_started_when_keep_awake_is_off(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a"])
    seen = Seen()
    result = run_fake(local_config(folder, tmp_path / "out", keep_awake=False), show=seen)
    assert result.status == "finished"
    assert seen.during() == 0
    assert keep_awake_lines(result.run_folder) == [OFF_LINE]


@mac_only
def test_mac_gone_after_a_cancel_file(tmp_path):
    config, _ = kept_awake(tmp_path, names=["a", "b_slow", "c_cancel", "d"], workers=2)
    seen = Seen()
    result = run_fake(config, show=seen)
    assert result.status == "cancelled"
    assert seen.during() == 1
    assert not caffeinate_processes()


@mac_only
def test_mac_gone_after_ctrl_c(tmp_path):
    config, _ = kept_awake(tmp_path)
    seen = Seen(stop_on="a: started")
    result = run_fake(config, show=seen)
    assert result.status == "cancelled"
    assert "Ctrl+C" in result.message
    assert seen.during() == 1
    assert not caffeinate_processes()


@mac_only
def test_mac_gone_after_a_stopped_run(tmp_path):
    config, _ = kept_awake(tmp_path, names=["a", "b_crash_always", "c"])
    seen = Seen()
    result = run_fake(config, show=seen)
    assert result.status == "stopped"
    assert seen.during() == 1
    assert not caffeinate_processes()


@mac_only
def test_mac_gone_after_an_unexpected_problem(tmp_path, monkeypatch):
    config, _ = kept_awake(tmp_path)
    fail_in_the_run(monkeypatch)
    seen = Seen()
    with pytest.raises(batch.RunStoppedError, match="the disk is full"):
        run_fake(config, show=seen)
    assert seen.during() == 1
    assert not caffeinate_processes()
    [run_folder] = (tmp_path / "out").iterdir()
    assert keep_awake_lines(run_folder) == [KEPT_AWAKE_LINE]
    assert run_info(run_folder, "stopped")["status"] == "stopped"


KILLED_RUN = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, sys.argv[1])
    from batch_helpers import fake_process_image
    from bigfish_pypeline import batch
    from test_batch_run import local_config, tiny_images

    if __name__ == "__main__":
        folder = tiny_images(Path(sys.argv[2]) / "input", ["a_slow"])
        config = local_config(folder, Path(sys.argv[2]) / "out", keep_awake=True)
        batch.run_batch(config, image_function=fake_process_image)
    """
)


@mac_only
def test_mac_main_process_killed_leaves_no_caffeinate(tmp_path):
    script = tmp_path / "killed_run.py"
    script.write_text(KILLED_RUN, encoding="utf-8")
    child = subprocess.Popen(
        [sys.executable, str(script), str(Path(__file__).parent), str(tmp_path)],
        cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    workers = []
    try:
        end = time.monotonic() + 60
        while not caffeinate_processes(child.pid):
            assert child.poll() is None, "the run ended before keep-awake was seen"
            assert time.monotonic() < end, "keep-awake did not start"
            time.sleep(0.1)
        workers = psutil.Process(child.pid).children(recursive=True)
        child.kill()
        child.wait()
        assert wait_until_gone(child.pid, seconds=10)
    finally:
        # the worker of the killed run sleeps for a long time; none may be left behind
        for process in workers:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        if child.poll() is None:
            child.kill()
            child.wait()
        for process in caffeinate_processes(child.pid):
            process.kill()


# ---------------------------------------------------------------------------
# Windows: the system's request, with a stand-in for the call
# ---------------------------------------------------------------------------


def test_windows_request_at_the_start_and_withdrawn_at_the_end(tmp_path, monkeypatch):
    calls = Calls()
    windows_system(monkeypatch, calls)
    started = nothing_may_start(monkeypatch)
    config, _ = kept_awake(tmp_path)
    result = run_fake(config)
    assert result.status == "finished"
    assert calls.flags == [batch.ES_CONTINUOUS | batch.ES_SYSTEM_REQUIRED, batch.ES_CONTINUOUS]
    assert batch.ES_CONTINUOUS == 0x80000000 and batch.ES_SYSTEM_REQUIRED == 0x1
    assert calls.threads[0] is calls.threads[1] is threading.main_thread()
    assert started == []
    assert keep_awake_lines(result.run_folder) == [KEPT_AWAKE_LINE]


def test_windows_request_is_in_force_during_the_run(tmp_path, monkeypatch):
    calls = Calls()
    windows_system(monkeypatch, calls)
    config, _ = kept_awake(tmp_path)
    seen = []
    run_fake(config, show=lambda text: seen.append(len(calls.flags)))
    # made before the images start, withdrawn only after the last line
    assert seen[-1] == 1
    assert len(calls.flags) == 2


def test_windows_withdrawn_after_a_cancel(tmp_path, monkeypatch):
    calls = Calls()
    windows_system(monkeypatch, calls)
    config, _ = kept_awake(tmp_path, names=["a", "b_slow", "c_cancel", "d"], workers=2)
    result = run_fake(config)
    assert result.status == "cancelled"
    assert calls.flags == [batch.ES_CONTINUOUS | batch.ES_SYSTEM_REQUIRED, batch.ES_CONTINUOUS]


def test_windows_withdrawn_after_ctrl_c(tmp_path, monkeypatch):
    calls = Calls()
    windows_system(monkeypatch, calls)
    config, _ = kept_awake(tmp_path)
    result = run_fake(config, show=Seen(stop_on="a: started"))
    assert result.status == "cancelled"
    assert calls.flags == [batch.ES_CONTINUOUS | batch.ES_SYSTEM_REQUIRED, batch.ES_CONTINUOUS]


def test_windows_withdrawn_after_a_stop(tmp_path, monkeypatch):
    calls = Calls()
    windows_system(monkeypatch, calls)
    config, _ = kept_awake(tmp_path, names=["a", "b_crash_always", "c"])
    result = run_fake(config)
    assert result.status == "stopped"
    assert calls.flags == [batch.ES_CONTINUOUS | batch.ES_SYSTEM_REQUIRED, batch.ES_CONTINUOUS]


def test_windows_withdrawn_after_an_error(tmp_path, monkeypatch):
    calls = Calls()
    windows_system(monkeypatch, calls)
    fail_in_the_run(monkeypatch)
    config, _ = kept_awake(tmp_path)
    with pytest.raises(batch.RunStoppedError, match="the disk is full"):
        run_fake(config)
    assert calls.flags == [batch.ES_CONTINUOUS | batch.ES_SYSTEM_REQUIRED, batch.ES_CONTINUOUS]


def test_windows_request_not_accepted_is_a_warning(tmp_path, monkeypatch):
    calls = Calls(result=0)
    windows_system(monkeypatch, calls)
    config, _ = kept_awake(tmp_path)
    result = run_fake(config)
    assert result.status == "finished"
    # nothing was granted, so there is nothing to withdraw
    assert calls.flags == [batch.ES_CONTINUOUS | batch.ES_SYSTEM_REQUIRED]
    assert keep_awake_lines(result.run_folder) == [
        WARNING_START + "Windows did not accept the request" + WARNING_END
    ]


def test_windows_call_that_fails_is_a_warning(tmp_path, monkeypatch):
    calls = Calls(error=OSError("no such system call"))
    windows_system(monkeypatch, calls)
    config, _ = kept_awake(tmp_path)
    result = run_fake(config)
    assert result.status == "finished"
    assert keep_awake_lines(result.run_folder) == [
        WARNING_START + "OSError: no such system call" + WARNING_END
    ]


def test_windows_nothing_requested_when_keep_awake_is_off(tmp_path, monkeypatch):
    calls = Calls()
    windows_system(monkeypatch, calls)
    folder = tiny_images(tmp_path / "input", ["a"])
    result = run_fake(local_config(folder, tmp_path / "out", keep_awake=False))
    assert calls.flags == []
    assert keep_awake_lines(result.run_folder) == [OFF_LINE]


# ---------------------------------------------------------------------------
# Linux and other systems
# ---------------------------------------------------------------------------


def test_linux_nothing_is_done(tmp_path, monkeypatch):
    calls = Calls()
    monkeypatch.setattr(batch, "_system_name", lambda: "Linux")
    monkeypatch.setattr(batch, "_set_execution_state", calls)
    started = nothing_may_start(monkeypatch)
    config, _ = kept_awake(tmp_path)
    result = run_fake(config)
    assert result.status == "finished"
    assert started == [] and calls.flags == []
    assert keep_awake_lines(result.run_folder) == [LINUX_LINE]


def test_other_system_nothing_is_done(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "_system_name", lambda: "FreeBSD")
    started = nothing_may_start(monkeypatch)
    config, _ = kept_awake(tmp_path)
    result = run_fake(config)
    assert started == []
    assert keep_awake_lines(result.run_folder) == [OTHER_LINE]


# ---------------------------------------------------------------------------
# `caffeinate` missing or failing (forced to the macOS path)
# ---------------------------------------------------------------------------


def test_caffeinate_missing_is_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "_system_name", lambda: "Darwin")
    monkeypatch.setattr(batch, "CAFFEINATE", "caffeinate-that-does-not-exist")
    started = nothing_may_start(monkeypatch)
    config, _ = kept_awake(tmp_path)
    result = run_fake(config)
    assert result.status == "finished"
    assert started == []
    assert keep_awake_lines(result.run_folder) == [
        WARNING_START + "`caffeinate-that-does-not-exist` was not found" + WARNING_END
    ]


def test_caffeinate_that_cannot_start_is_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "_system_name", lambda: "Darwin")
    monkeypatch.setattr(batch.shutil, "which", lambda name: "/bin/caffeinate-stand-in")

    real_popen = subprocess.Popen

    def popen(command, *args, **kwargs):
        if "-w" in command:
            raise PermissionError("not allowed")
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(batch.subprocess, "Popen", popen)
    config, _ = kept_awake(tmp_path)
    result = run_fake(config)
    assert result.status == "finished"
    assert keep_awake_lines(result.run_folder) == [
        WARNING_START + "PermissionError: not allowed" + WARNING_END
    ]


@pytest.mark.skipif(shutil.which("false") is None, reason="needs the `false` program")
def test_caffeinate_that_stops_at_once_is_a_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "_system_name", lambda: "Darwin")
    monkeypatch.setattr(batch, "CAFFEINATE", "false")
    config, _ = kept_awake(tmp_path)
    result = run_fake(config)
    assert result.status == "finished"
    assert keep_awake_lines(result.run_folder) == [
        WARNING_START + "`false` stopped at once (exit code 1)" + WARNING_END
    ]


# ---------------------------------------------------------------------------
# Off, and `check`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("system", ["Darwin", "Windows", "Linux"])
def test_off_starts_nothing_on_any_system(tmp_path, monkeypatch, system):
    calls = Calls()
    monkeypatch.setattr(batch, "_system_name", lambda: system)
    monkeypatch.setattr(batch, "_set_execution_state", calls)
    started = nothing_may_start(monkeypatch)
    folder = tiny_images(tmp_path / "input", ["a"])
    result = run_fake(local_config(folder, tmp_path / "out", keep_awake=False))
    assert result.status == "finished"
    assert started == [] and calls.flags == []
    assert keep_awake_lines(result.run_folder) == [OFF_LINE]


def test_the_line_comes_once_and_after_the_workers_line(tmp_path):
    folder = tiny_images(tmp_path / "input", ["a"])
    result = run_fake(local_config(folder, tmp_path / "out", keep_awake=False))
    lines = log_text(result.run_folder).splitlines()
    awake = [index for index, line in enumerate(lines) if "Keep awake:" in line]
    [workers] = [index for index, line in enumerate(lines) if "  Workers: " in line]
    assert awake == [workers + 1]


def test_check_starts_nothing(tmp_path, monkeypatch, capsys):
    calls = Calls()
    monkeypatch.setattr(batch, "_system_name", lambda: "Windows")
    monkeypatch.setattr(batch, "_set_execution_state", calls)
    started = nothing_may_start(monkeypatch)
    folder = tiny_images(tmp_path / "input", ["a"])
    config = local_config(folder, tmp_path / "out", keep_awake=True)
    settings = tmp_path / "settings.yaml"
    save_config(config, settings)
    code = cli.main(["check", str(settings)])
    capsys.readouterr()
    assert code == 0
    assert started == [] and calls.flags == []
    assert not (tmp_path / "out").exists()


def test_plan_run_starts_nothing(tmp_path, monkeypatch):
    calls = Calls()
    monkeypatch.setattr(batch, "_system_name", lambda: "Windows")
    monkeypatch.setattr(batch, "_set_execution_state", calls)
    started = nothing_may_start(monkeypatch)
    folder = tiny_images(tmp_path / "input", ["a"])
    plan = batch.plan_run(local_config(folder, tmp_path / "out", keep_awake=True))
    plan.close()
    assert started == [] and calls.flags == []


def test_stop_without_start_and_twice(monkeypatch):
    calls = Calls()
    monkeypatch.setattr(batch, "_system_name", lambda: "Windows")
    monkeypatch.setattr(batch, "_set_execution_state", calls)
    keep_awake = batch._KeepAwake()
    keep_awake.stop()
    assert calls.flags == []
    keep_awake.start(True)
    keep_awake.stop()
    keep_awake.stop()
    assert calls.flags == [batch.ES_CONTINUOUS | batch.ES_SYSTEM_REQUIRED, batch.ES_CONTINUOUS]
