"""Stand-ins for `batch.process_image`, run in worker processes by the batch runner tests.

What the stand-in does depends on words in the image name:

- `crash_once`: the worker process ends abruptly the first time, then the image works.
- `crash_always`: the worker process ends abruptly every time.
- `slow`: some files are written, then the worker waits for a long time.
- `cancel`: a `cancel` file is put in the run folder, then as `slow`.
- `session_ended`: the OMERO session has ended.
- `key_in_error`: an error whose message holds the session key.
- `threads`: the thread variables are written in the `warnings` column.
- anything else: one spot per channel, written at once.

With a label folder, `segmentation_status` is "done" when the image's label
file is there, "no_labels" when it is not, and "failed" with a segmentation
error; `n_cells` is the number of cells in the label file.
"""

import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import tifffile

from bigfish_pypeline import io, outputs
from bigfish_pypeline.segmentation import label_file_path

CRASH_DELAY_S = 2
LONG_WAIT_S = 120


def _crash():
    time.sleep(CRASH_DELAY_S)
    os._exit(1)


def fake_process_image(config, image_name, image_source, run_folder, label_folder=None,
                       omero_host=None, omero_port=None, omero_key=None,
                       segmentation_warnings=(), segmentation_error=None):
    run_folder = Path(run_folder)
    per_image = run_folder / outputs.PER_IMAGE_FOLDER_NAME

    if "crash_once" in image_name:
        marker = run_folder.parent / f"{image_name}.crashed"
        if not marker.exists():
            marker.write_text("", encoding="utf-8")
            _crash()
    if "crash_always" in image_name:
        _crash()
    if "session_ended" in image_name:
        raise io.OmeroSessionEnded("The OMERO session has ended.")
    if "key_in_error" in image_name:
        raise RuntimeError(f"the server refused session {omero_key}")
    if "cancel" in image_name:
        (run_folder / "cancel").write_text("", encoding="utf-8")
    if "slow" in image_name or "cancel" in image_name:
        (per_image / f"{image_name}_spots.csv").write_text("image\n", encoding="utf-8")
        (per_image / f"{image_name}_images.csv.tmp").write_text("image\n", encoding="utf-8")
        time.sleep(LONG_WAIT_S)

    warnings = list(segmentation_warnings)
    if "threads" in image_name:
        warnings = [f"{name}={os.environ.get(name)}" for name in
                    ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")]
    source, status, n_cells = "", "", None
    if label_folder is not None:
        source = config.segmentation.source
        path = label_file_path(label_folder, image_name)
        if segmentation_error is not None:
            status = "failed"
            warnings.append(f"no cell results: segmentation failed: {segmentation_error}")
        elif path.is_file():
            status = "done"
            n_cells = len(np.unique(tifffile.imread(path))) - 1
        else:
            status = "no_labels"
    rows = []
    spots = []
    columns = outputs.spot_columns(3)
    for channel in config.channels:
        rows.append(outputs.image_row(
            image_name, channel.index, channel.name, "done",
            threshold_mode=channel.threshold.mode, threshold=10.0,
            n_spots_detected=1, n_spots=1, n_clusters=0, n_cells=n_cells,
            segmentation_source=source, segmentation_status=status,
            warnings=warnings, runtime_s=0.01,
        ))
        spots.append(outputs.make_spots_table(
            image_name, channel.index, channel.name, [[1, 2, 3]], 3, 65, 200, columns=columns,
        ))
    outputs.write_image_tables(run_folder, image_name, outputs.make_images_table(rows), spots=spots)
    log_lines = []
    if omero_key is not None:
        log_lines.append(f"{image_name}: warning: read with session {omero_key} from {omero_host}")
    return {"image": image_name, "rows": rows, "log_lines": log_lines}


# ---------------------------------------------------------------------------
# OMERO in a worker process, with stand-ins for the server
# ---------------------------------------------------------------------------


def log_like_omero(key):
    """Log what omero-py logs around a dropped connection, the session key included.

    Before logging, `logging.basicConfig()` is called, as omero-py does each time it
    makes a connection. A warning on a Cellpose-like logger (whose package has its
    own NullHandler) is logged too.
    """
    logging.basicConfig()
    try:
        raise RuntimeError(f"Ice.ConnectionLostException: recv() returned zero ('omero.session.uuid': '{key}')")
    except RuntimeError:
        for level in (logging.WARNING, logging.ERROR):
            logging.getLogger("omero.gateway").log(
                level, "ConnectionLostException on findByQuery {'omero.session.uuid': '%s'}", key, exc_info=True,
            )
            logging.getLogger("omero.client").log(level, "Session %s: cannot get session service", key, exc_info=True)
    logging.getLogger("omero.client").warning("Cannot get session service for killSession. Using closeSession")
    logging.getLogger("cellpose").addHandler(logging.NullHandler())
    logging.getLogger("cellpose.vit").warning("Could not import CPDINO")


_joins = {"count": 0}


def omero_process_image(config, image_name, image_source, run_folder, label_folder=None,
                        omero_host=None, omero_port=None, omero_key=None,
                        segmentation_warnings=(), segmentation_error=None):
    """`batch.process_image` with io's OMERO functions replaced by stand-ins.

    Words in the image name: `drop_once` and `drop_twice`: the connection drops once
    or twice while the image information is read, and omero-py's messages are logged
    as `log_like_omero` does. A last log line says which connection the image ended
    with and how many joins this worker has made.
    """
    from bigfish_pypeline import batch

    drops = {"left": 2 if "drop_twice" in image_name else 1 if "drop_once" in image_name else 0}

    def join_session(host, port, key):
        logging.basicConfig()
        _joins["count"] += 1
        return SimpleNamespace(number=_joins["count"], close=lambda hard=True: None)

    def get_omero_image_info(conn, image_id):
        if drops["left"]:
            drops["left"] -= 1
            log_like_omero(omero_key)
            reason = f"ConnectionLostException: Ice.ConnectionLostException: session {omero_key}"
            error = io.OmeroConnectionLost(f"OMERO image {image_id}: lost the connection to OMERO ({reason})")
            error.reason = reason
            raise error
        return io.OmeroImageInfo(
            image_id=image_id, name="x", size_z=2, size_c=2, size_t=1, size_y=16, size_x=16,
            pixel_type="uint16", dtype=np.dtype("uint16"), voxel_size_z=200.0,
            voxel_size_y=65.0, voxel_size_x=65.0, channel_names=["a", "b"],
        )

    def read_omero_channels(conn, image_id, layout, channels):
        return {channel: np.ones((2, 16, 16), dtype=np.uint16) for channel in channels}

    io.join_session = join_session
    io.get_omero_image_info = get_omero_image_info
    io.read_omero_channels = read_omero_channels
    result = batch.process_image(
        config, image_name, image_source, run_folder, label_folder=label_folder,
        omero_host=omero_host, omero_port=omero_port, omero_key=omero_key,
        segmentation_warnings=segmentation_warnings, segmentation_error=segmentation_error,
    )
    conn = batch._omero["conn"]
    result["log_lines"].append(
        f"{image_name}: connection {conn.number if conn else None} after {_joins['count']} join(s)"
    )
    return result
