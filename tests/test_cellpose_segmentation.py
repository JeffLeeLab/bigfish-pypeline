"""Device choice, model loading, segmentation with Cellpose, and label files written."""

import subprocess
import sys
import textwrap

import numpy as np
import pytest
import tifffile

from bigfish_pypeline import segmentation as seg
from bigfish_pypeline.config import CellposeSettings
from cellpose_standin import StandInModel, rectangle_labels


# ---------------------------------------------------------------------------
# Segmentation with the stand-in model
# ---------------------------------------------------------------------------

def test_settings_reach_eval_unchanged():
    settings = CellposeSettings(
        diameter=42.5, flow_threshold=0.7, cellprob_threshold=-1.5, min_size=30,
        normalize=False, batch_size=4, niter=500,
    )
    model = StandInModel()
    image = np.arange(40 * 60, dtype=np.uint16).reshape(40, 60)

    seg.segment_cells(model, image, **seg.cellpose_eval_settings(settings))

    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["diameter"] == 42.5
    assert call["flow_threshold"] == 0.7
    assert call["cellprob_threshold"] == -1.5
    assert call["min_size"] == 30
    assert call["normalize"] is False
    assert call["batch_size"] == 4
    assert call["niter"] == 500
    assert call["do_3D"] is False
    assert call["channel_axis"] is None
    assert call["x"].shape == (40, 60)
    assert call["x"].dtype == np.float32
    np.testing.assert_array_equal(call["x"], image)


def test_default_settings_follow_the_config():
    model = StandInModel()
    seg.segment_cells(model, np.ones((20, 20)), **seg.cellpose_eval_settings(CellposeSettings()))
    call = model.calls[0]
    assert call["diameter"] is None
    assert call["flow_threshold"] == 0.4
    assert call["cellprob_threshold"] == 0
    assert call["min_size"] == 15
    assert call["normalize"] is True
    assert call["batch_size"] == 1
    assert call["niter"] is None
    assert call["do_3D"] is False


def test_eval_settings_from_a_dict_leave_out_the_model_name():
    settings = CellposeSettings().model_dump()
    assert set(seg.cellpose_eval_settings(settings)) == set(seg.EVAL_SETTINGS)
    assert "model" not in seg.cellpose_eval_settings(settings)


def test_result_holds_labels_qc_items_and_time():
    model = StandInModel(n_cells=3)
    result = seg.segment_cells(model, np.ones((30, 70), dtype=np.uint8))

    masks = result["masks"]
    assert masks.shape == (30, 70)
    assert masks.dtype == np.uint32
    assert result["n_cells"] == 3
    assert set(np.unique(masks)) == {0, 1, 2, 3}
    assert result["warning"] is None
    assert result["model_input"].shape == (30, 70)
    assert result["flows"][0].shape == (30, 70, 3)
    assert result["seconds"] >= 0
    seg.check_labels(masks, (30, 70))


def test_no_cells_gives_zero_labels_and_a_warning():
    result = seg.segment_cells(StandInModel(n_cells=0), np.zeros((25, 25)))
    assert result["masks"].shape == (25, 25)
    assert result["masks"].dtype == np.uint32
    assert not result["masks"].any()
    assert result["n_cells"] == 0
    assert result["warning"] == seg.NO_CELLS_WARNING


def test_error_in_eval_gives_one_line_segmentation_error():
    model = StandInModel(error=RuntimeError("MPS backend out of memory\n(details on a second line)"))
    with pytest.raises(seg.SegmentationError) as caught:
        seg.segment_cells(model, np.ones((20, 20)))
    message = str(caught.value)
    assert "\n" not in message
    assert "RuntimeError" in message
    assert "out of memory" in message


def test_memory_error_is_passed_on():
    with pytest.raises(MemoryError):
        seg.segment_cells(StandInModel(error=MemoryError()), np.ones((20, 20)))


def test_image_that_is_not_2d_is_refused():
    with pytest.raises(seg.SegmentationError, match="must be 2D"):
        seg.segment_cells(StandInModel(), np.ones((3, 20, 20)))


def test_stand_in_labels_fit_any_2d_image():
    for shape in [(1, 1), (5, 3), (64, 64), (100, 17)]:
        labels = rectangle_labels(shape, 4)
        assert labels.shape == shape
        seg.check_labels(labels, shape)


# ---------------------------------------------------------------------------
# Device choice, with stand-ins for the device checks
# ---------------------------------------------------------------------------

@pytest.fixture
def devices(monkeypatch):
    """
    Pretend which devices are present and which pass the test calculation.
    Set `present` and `working` on the returned object; the CPU is always present.
    """
    class Devices:
        present = {"cpu"}
        working = {"cpu"}
        tested = []

    state = Devices()
    state.tested = []

    def available(name):
        return name in state.present

    def test_calculation(name):
        state.tested.append(name)
        if name not in state.working:
            raise RuntimeError("the result was 0.0")

    monkeypatch.setattr(seg, "_device_available", available)
    monkeypatch.setattr(seg, "_test_calculation", test_calculation)
    return state


def test_auto_takes_cuda_first(devices):
    devices.present = {"cuda", "mps", "cpu"}
    devices.working = {"cuda", "mps", "cpu"}
    device, report, warnings = seg.choose_device("auto")
    assert device == "cuda"
    assert devices.tested == ["cuda"]
    assert "cuda" in report
    assert warnings == []


def test_auto_takes_the_apple_gpu_without_cuda(devices):
    devices.present = {"mps", "cpu"}
    devices.working = {"mps", "cpu"}
    device, report, warnings = seg.choose_device("auto")
    assert device == "mps"
    assert "Apple GPU" in report
    assert warnings == []


def test_auto_moves_on_when_the_gpu_fails_the_test(devices):
    devices.present = {"cuda", "mps", "cpu"}
    devices.working = {"mps", "cpu"}
    device, _, warnings = seg.choose_device("auto")
    assert device == "mps"
    assert devices.tested == ["cuda", "mps"]
    assert len(warnings) == 1
    assert "NVIDIA GPU" in warnings[0] and "failed a test calculation" in warnings[0]


def test_auto_falls_back_to_the_cpu_with_warnings(devices):
    devices.present = {"mps", "cpu"}
    devices.working = {"cpu"}
    device, report, warnings = seg.choose_device("auto")
    assert device == "cpu"
    assert devices.tested == ["mps", "cpu"]
    assert "the CPU" in report
    assert "Apple GPU" in warnings[0]
    assert warnings[-1] == seg.CPU_WARNING


def test_auto_without_a_gpu_uses_the_cpu_with_a_warning(devices):
    device, _, warnings = seg.choose_device("auto")
    assert device == "cpu"
    assert warnings == [seg.CPU_WARNING]


def test_cpu_named_in_the_config_gives_the_slow_warning(devices):
    devices.present = {"mps", "cpu"}
    devices.working = {"mps", "cpu"}
    device, report, warnings = seg.choose_device("cpu")
    assert device == "cpu"
    assert "as set in the config" in report
    assert warnings == [seg.CPU_WARNING]


@pytest.mark.parametrize("name", ["cuda", "mps"])
def test_named_gpu_that_is_missing_stops_with_a_plain_message(devices, name):
    with pytest.raises(seg.CellposeSetupError) as caught:
        seg.choose_device(name)
    message = str(caught.value)
    assert "\n" not in message
    assert f"`device: {name}`" in message
    assert "not available" in message
    assert devices.tested == []


@pytest.mark.parametrize("name", ["cuda", "mps"])
def test_named_gpu_that_fails_the_test_stops_with_a_plain_message(devices, name):
    devices.present = {name, "cpu"}
    with pytest.raises(seg.CellposeSetupError) as caught:
        seg.choose_device(name)
    message = str(caught.value)
    assert "\n" not in message
    assert "failed a test calculation" in message
    assert devices.tested == [name]


def test_named_gpu_that_works_is_used(devices):
    devices.present = {"mps", "cpu"}
    devices.working = {"mps", "cpu"}
    device, report, warnings = seg.choose_device("mps")
    assert device == "mps"
    assert "as set in the config" in report
    assert warnings == []


def test_unknown_device_setting_is_refused():
    with pytest.raises(seg.CellposeSetupError, match="Unknown device"):
        seg.choose_device("gpu")


def test_test_calculation_runs_on_the_cpu():
    seg._test_calculation("cpu")


# ---------------------------------------------------------------------------
# Model loading, with Cellpose's model class replaced
# ---------------------------------------------------------------------------

@pytest.fixture
def cellpose_models(monkeypatch, tmp_path):
    """
    Cellpose's models module with an empty model folder, no downloads, and a
    model class that records how it was called.
    """
    from cellpose import models

    calls = []

    class RecordingModel:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    def no_download(name):
        raise AssertionError(f"a download of {name} was started")

    monkeypatch.setattr(models, "MODEL_DIR", tmp_path / "models")
    monkeypatch.setattr(models, "MODEL_LIST_PATH", str(tmp_path / "models" / "gui_models.txt"))
    monkeypatch.setattr(models, "cache_model_path", no_download)
    monkeypatch.setattr(models, "CellposeModel", RecordingModel)
    monkeypatch.setattr(models, "calls", calls, raising=False)
    return models


def test_unknown_model_name_gives_a_plain_message_without_download(cellpose_models):
    with pytest.raises(seg.CellposeSetupError) as caught:
        seg.load_cellpose_model("cpsam_v9", "cpu")
    message = str(caught.value)
    assert "\n" not in message
    assert "Unknown Cellpose model 'cpsam_v9'" in message
    assert "cpsam_v2" in message
    assert cellpose_models.calls == []


def test_model_call_uses_the_device_and_32_bit_weights(cellpose_models):
    import torch

    seg.load_cellpose_model("cpsam_v2", "cpu")
    assert cellpose_models.calls == [
        {"pretrained_model": "cpsam_v2", "device": torch.device("cpu"), "use_bfloat16": False}
    ]


def test_model_file_given_by_its_path(cellpose_models, tmp_path):
    model_file = tmp_path / "my_model"
    model_file.write_bytes(b"weights")
    seg.load_cellpose_model(str(model_file), "cpu")
    assert cellpose_models.calls[0]["pretrained_model"] == str(model_file)


def test_model_added_in_the_cellpose_window_is_known(cellpose_models, tmp_path):
    folder = tmp_path / "models"
    folder.mkdir()
    (folder / "gui_models.txt").write_text("my_nuclei\n")
    seg.load_cellpose_model("my_nuclei", "cpu")
    assert cellpose_models.calls[0]["pretrained_model"] == "my_nuclei"


def test_failed_download_gives_a_plain_message(cellpose_models, monkeypatch):
    from urllib.error import URLError

    def no_network(**kwargs):
        raise URLError("nodename nor servname provided, or not known")

    monkeypatch.setattr(cellpose_models, "CellposeModel", no_network)
    with pytest.raises(seg.CellposeSetupError) as caught:
        seg.load_cellpose_model("cpsam_v2", "cpu")
    message = str(caught.value)
    assert "\n" not in message
    assert "could not be downloaded" in message
    assert "internet connection" in message


def test_model_that_cannot_be_loaded_gives_a_plain_message(cellpose_models, monkeypatch, tmp_path):
    folder = tmp_path / "models"
    folder.mkdir()
    (folder / "cpsam_v2").write_bytes(b"damaged")

    def damaged(**kwargs):
        raise RuntimeError("PytorchStreamReader failed reading zip archive")

    monkeypatch.setattr(cellpose_models, "CellposeModel", damaged)
    with pytest.raises(seg.CellposeSetupError) as caught:
        seg.load_cellpose_model("cpsam_v2", "cpu")
    message = str(caught.value)
    assert "\n" not in message
    assert "could not be loaded" in message
    assert "delete it" in message


def test_threads_are_set_on_the_cpu(cellpose_models, monkeypatch):
    import torch

    chosen = []
    monkeypatch.setattr(torch, "set_num_threads", chosen.append)
    seg.load_cellpose_model("cpsam_v2", "cpu", threads=3)
    seg.load_cellpose_model("cpsam_v2", "cpu")
    assert chosen == [3]


# ---------------------------------------------------------------------------
# The real model on the crop
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def real_model():
    """The Cellpose model, loaded once for all the tests that need it."""
    device, _, _ = seg.choose_device("auto")
    return seg.load_cellpose_model("cpsam_v2", device)


@pytest.fixture(scope="session")
def crop_dapi(crop_path):
    """The crop's DAPI channel (channel 0 of ZCYX), pre-treated with the default settings."""
    image = tifffile.imread(crop_path)
    return seg.pretreat_channel(image[:, 0])


@pytest.mark.cellpose
def test_real_model_gives_valid_labels_for_the_crop(real_model, crop_dapi):
    result = seg.segment_cells(real_model, crop_dapi)
    masks = result["masks"]
    assert masks.ndim == 2
    assert masks.dtype == np.uint32
    assert masks.shape == crop_dapi.shape
    seg.check_labels(masks, crop_dapi.shape)
    assert result["flows"][0].shape == (*crop_dapi.shape, 3)
    assert result["seconds"] > 0


@pytest.mark.cellpose
def test_two_runs_on_the_same_device_give_the_same_labels(real_model, crop_dapi):
    first = seg.segment_cells(real_model, crop_dapi)["masks"]
    second = seg.segment_cells(real_model, crop_dapi)["masks"]
    np.testing.assert_array_equal(first, second)


# ---------------------------------------------------------------------------
# Label files
# ---------------------------------------------------------------------------

def test_written_label_file_is_read_back(tmp_path):
    masks = rectangle_labels((40, 50), 3).astype(np.int64)
    masks[0, 0] = 70000
    path = seg.write_label_file(masks, tmp_path / "labels", "image_01")

    assert path == seg.label_file_path(tmp_path / "labels", "image_01")
    assert path.name == "image_01_seglabels.tif"
    assert not seg.temporary_label_path(path).exists()
    labels = seg.read_label_file(tmp_path / "labels", "image_01", (40, 50))
    assert labels.dtype == np.uint32
    np.testing.assert_array_equal(labels, masks)


def test_written_empty_label_file_is_read_back(tmp_path):
    masks = np.zeros((12, 9), dtype=np.uint32)
    seg.write_label_file(masks, tmp_path, "empty")
    np.testing.assert_array_equal(seg.read_label_file(tmp_path, "empty", (12, 9)), masks)


def test_file_left_under_the_temporary_name_is_not_a_label_file(tmp_path):
    path = seg.label_file_path(tmp_path, "image_01")
    tifffile.imwrite(seg.temporary_label_path(path), np.ones((10, 10), dtype=np.uint32))
    with pytest.raises(seg.LabelFileError, match="not found"):
        seg.read_label_file(tmp_path, "image_01", (10, 10))


def test_failed_rename_leaves_no_file(tmp_path, monkeypatch):
    def fail(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(seg.os, "replace", fail)
    with pytest.raises(OSError):
        seg.write_label_file(np.ones((10, 10), dtype=np.uint32), tmp_path, "image_01")
    assert list(tmp_path.iterdir()) == []


def test_unusable_labels_are_not_written(tmp_path):
    with pytest.raises(seg.LabelFileError):
        seg.write_label_file(np.full((5, 5), -1), tmp_path, "image_01")
    with pytest.raises(seg.LabelFileError):
        seg.write_label_file(np.ones((2, 5, 5)), tmp_path, "image_01")
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Reading label files does not load Cellpose
# ---------------------------------------------------------------------------

def test_reading_label_files_does_not_load_cellpose_or_torch(tmp_path):
    seg.write_label_file(rectangle_labels((20, 20), 2), tmp_path, "image_01")
    script = textwrap.dedent(f"""
        import sys
        from bigfish_pypeline import segmentation
        labels = segmentation.read_label_file({str(tmp_path)!r}, "image_01", (20, 20))
        assert labels.max() == 2
        loaded = [name for name in ("cellpose", "torch") if name in sys.modules]
        print("loaded:", loaded)
        sys.exit(1 if loaded else 0)
    """)
    run = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "loaded: []" in run.stdout
