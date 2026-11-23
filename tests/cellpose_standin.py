"""Stand-ins for a Cellpose model, for tests that must not load Cellpose or its model file."""

import threading
from types import SimpleNamespace

import numpy as np


def rectangle_labels(shape_yx, n_cells):
    """Label image with up to n_cells rectangles side by side, numbered 1, 2, ..."""
    ly, lx = shape_yx
    labels = np.zeros((ly, lx), dtype=np.uint16)
    label = 0
    for i in range(n_cells):
        x0 = (2 * i + 1) * lx // (2 * n_cells + 1)
        x1 = (2 * i + 2) * lx // (2 * n_cells + 1)
        y0, y1 = ly // 4, max(ly // 4 + 1, 3 * ly // 4)
        if x1 > x0 and y1 > y0:
            label += 1
            labels[y0:y1, x0:x1] = label
    return labels


class StandInModel:
    """
    Behaves like a loaded Cellpose model for segment_cells.

    n_cells: number of rectangles returned as cells (0 for none).
    error: an error raised by `eval` instead of returning labels.
    device: device name given as `model.device.type`.

    Every call of `eval` is recorded in `calls` as a dict holding the image
    ("x") and the settings it was given.
    """

    def __init__(self, n_cells=3, error=None, device="cpu"):
        self.n_cells = n_cells
        self.error = error
        self.device = SimpleNamespace(type=device)
        self.calls = []

    def eval(self, x, **settings):
        self.calls.append({"x": x, **settings})
        if self.error is not None:
            raise self.error
        shape_yx = np.shape(x)[:2]
        masks = rectangle_labels(shape_yx, self.n_cells)
        flows = [
            np.zeros((*shape_yx, 3), dtype=np.uint8),
            np.zeros((2, *shape_yx), dtype=np.float32),
            np.zeros(shape_yx, dtype=np.float32),
        ]
        return masks, flows, np.zeros(256, dtype=np.float32)


class BlockingModel(StandInModel):
    """
    A stand-in whose `eval` waits until `release` is set, like a long
    segmentation on the CPU that cannot be interrupted.

    block_from: the first call that waits (counted from 1); earlier calls
        return at once.
    timeout: the longest a call waits, in seconds.

    `waiting` is set when a call starts to wait; `returned` is set when a
    call that waited has returned.
    """

    def __init__(self, block_from=1, timeout=60, **kwargs):
        super().__init__(**kwargs)
        self.block_from = block_from
        self.timeout = timeout
        self.waiting = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()

    def eval(self, x, **settings):
        if len(self.calls) + 1 < self.block_from:
            return super().eval(x, **settings)
        self.waiting.set()
        self.release.wait(self.timeout)
        try:
            return super().eval(x, **settings)
        finally:
            self.returned.set()


class FailingModel(StandInModel):
    """A stand-in whose `eval` raises `error` on the call numbers in `fail_on` (counted from 1)."""

    def __init__(self, fail_on=(2,), error=None, **kwargs):
        super().__init__(**kwargs)
        self.fail_on = set(fail_on)
        self.fail_error = error if error is not None else RuntimeError("the stand-in model failed")

    def eval(self, x, **settings):
        if len(self.calls) + 1 in self.fail_on:
            self.calls.append({"x": x, **settings})
            raise self.fail_error
        return super().eval(x, **settings)
