"""Check that several processes can share one OMERO login.

Run this on the lab network, in a terminal with the `bigfish-msp` environment active:

    python tests/manual/omero_session_check.py --image-id 12345

Use the ID of any image you can see in OMERO; a small image is quickest. The script
asks for your OMERO username (unless you give `--username`) and your password. The
password is not shown as you type and is not saved anywhere.

What it checks:
1. You can log in and read the image's information.
2. Two helper processes can join your login, each read the image's information and
   one channel, and leave again.
3. Your login still works after the helpers have left, and again 5 seconds later.

Each step prints PASS or FAIL. The script ends with a summary and returns an error
code if any step failed. Copy the printed lines (they contain no password or key)
when you report the result.
"""

import argparse
import getpass
import multiprocessing
import queue
import sys
import time

from bigfish_pypeline import io
from bigfish_pypeline.config import OMERO_HOST, OMERO_PORT

N_WORKERS = 2
WAIT_SECONDS = 5
WORKER_TIME_LIMIT = 600


def describe(info):
    """The image information as short lines of text."""
    sizes = f"Z {info.size_z}, C {info.size_c}, T {info.size_t}, Y {info.size_y}, X {info.size_x}"
    voxel = ", ".join(
        f"{axis} {size:g} nm" if size is not None else f"{axis} not given"
        for axis, size in (("z", info.voxel_size_z), ("y", info.voxel_size_y), ("x", info.voxel_size_x))
    )
    return [
        f"name: {info.name}",
        f"output name: {info.output_name}",
        f"sizes: {sizes}",
        f"pixel type: {info.pixel_type}",
        f"voxel sizes: {voxel}",
        f"channels: {', '.join(info.channel_names)}",
    ]


def hide(text, key):
    return str(text).replace(key, "[hidden]")


def worker(number, host, port, key, image_id, results):
    """Join the session, read the image information and channel 0, then leave the session."""
    io.start_plain_logging()
    name = f"Helper {number}"
    try:
        conn = io.join_session(host, port, key)
    except Exception as error:
        results.put((name, False, f"could not join the login ({hide(error, key)})"))
        return
    try:
        info = io.get_omero_image_info(conn, image_id)
        array = io.read_omero_channel(conn, image_id, info.layout, 0)
        shape = " × ".join(str(n) for n in array.shape)
        results.put((name, True, f"joined, read channel 0 ({shape}, {array.dtype}) and left"))
    except Exception as error:
        results.put((name, False, f"joined but could not read the image ({hide(error, key)})"))
    finally:
        io.detach_session(conn)


class Report:
    def __init__(self):
        self.results = []

    def add(self, step, passed, detail=""):
        self.results.append((step, passed))
        line = f"{'PASS' if passed else 'FAIL'}  {step}"
        if detail:
            line += f": {detail}"
        print(line, flush=True)

    def finish(self):
        n_failed = sum(not passed for _, passed in self.results)
        print()
        if n_failed:
            print(f"Summary: {n_failed} of {len(self.results)} steps FAILED. Sharing the OMERO login does not work as expected.")
        else:
            print(f"Summary: all {len(self.results)} steps passed. Sharing the OMERO login works.")
        return 1 if n_failed else 0


def read_info(report, step, conn, image_id):
    try:
        info = io.get_omero_image_info(conn, image_id)
    except Exception as error:
        report.add(step, False, str(error))
        return None
    report.add(step, True)
    return info


def main():
    parser = argparse.ArgumentParser(
        description="Check that several processes can share one OMERO login. Run it on the lab network."
    )
    parser.add_argument("--image-id", required=True, help="ID of an OMERO image you can see")
    parser.add_argument("--username", help="your OMERO username (asked for if not given)")
    parser.add_argument("--host", default=OMERO_HOST, help=f"OMERO server (default {OMERO_HOST})")
    parser.add_argument("--port", type=int, default=OMERO_PORT, help=f"OMERO port (default {OMERO_PORT})")
    args = parser.parse_args()
    # omero-py's own messages can hold the session key: they are not printed
    io.start_plain_logging()

    from bigfish_pypeline.omero_tools import connect_to_omero

    report = Report()
    username = args.username or input("OMERO username: ").strip()
    password = getpass.getpass(f"OMERO password for {username}: ")
    try:
        conn = connect_to_omero(username, args.host, args.port, password=password)
    except Exception as error:
        report.add("Log in", False, str(error))
        return report.finish()
    finally:
        del password
    report.add("Log in", True)

    info = read_info(report, "Read the image information", conn, args.image_id)
    if info is None:
        return report.finish()
    for line in describe(info):
        print(f"      {line}")

    try:
        key = io.session_key(conn)
    except Exception as error:
        report.add("Find the login to share", False, str(error))
        return report.finish()

    print(f"Starting {N_WORKERS} helper processes ...", flush=True)
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    workers = [
        context.Process(target=worker, args=(number, args.host, args.port, key, args.image_id, results))
        for number in range(1, N_WORKERS + 1)
    ]
    for process in workers:
        process.start()

    reported = set()
    deadline = time.monotonic() + WORKER_TIME_LIMIT
    while len(reported) < N_WORKERS and time.monotonic() < deadline:
        try:
            name, passed, detail = results.get(timeout=1)
        except queue.Empty:
            if not any(process.is_alive() for process in workers) and results.empty():
                break
            continue
        reported.add(name)
        report.add(name, passed, detail)
    for number, process in enumerate(workers, start=1):
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
        name = f"Helper {number}"
        if name not in reported:
            report.add(name, False, "stopped without reporting a result")

    read_info(report, "Main login still works after the helpers left", conn, args.image_id)
    print(f"Waiting {WAIT_SECONDS} seconds ...", flush=True)
    time.sleep(WAIT_SECONDS)
    read_info(report, f"Main login still works {WAIT_SECONDS} seconds later", conn, args.image_id)
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
