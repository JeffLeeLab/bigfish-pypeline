"""Tests for segmentation.py: reading and checking label files."""

import numpy as np
import pytest
import tifffile

from bigfish_pypeline.segmentation import LabelFileError, label_file_path, read_label_file

IMAGE = "my image é"
SHAPE = (6, 8)


def _labels():
    labels = np.zeros(SHAPE, dtype=np.uint16)
    labels[1:3, 1:4] = 1
    labels[3:6, 5:8] = 2
    return labels


def _write(folder, array, name=IMAGE):
    tifffile.imwrite(label_file_path(folder, name), array)


def test_label_file_path(tmp_path):
    assert label_file_path(tmp_path, "img_01") == tmp_path / "img_01_seglabels.tif"


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16, np.uint32, np.int32, np.float32, np.float64])
def test_valid_file_loads(tmp_path, dtype):
    _write(tmp_path, _labels().astype(dtype))
    masks = read_label_file(tmp_path, IMAGE, SHAPE)
    assert masks.dtype == np.uint32
    assert masks.shape == SHAPE
    np.testing.assert_array_equal(masks, _labels())


def test_large_labels_kept(tmp_path):
    labels = _labels().astype(np.uint32)
    labels[labels == 2] = 70000
    _write(tmp_path, labels)
    masks = read_label_file(tmp_path, IMAGE, SHAPE)
    assert set(np.unique(masks)) == {0, 1, 70000}


def test_all_background_loads(tmp_path):
    _write(tmp_path, np.zeros(SHAPE, dtype=np.uint16))
    masks = read_label_file(tmp_path, IMAGE, SHAPE)
    assert masks.max() == 0


def _bad(values):
    labels = _labels().astype(np.float32)
    labels[0, 0] = values
    return labels


@pytest.mark.parametrize(
    "array, reason",
    [
        (np.zeros((2, *SHAPE), dtype=np.uint16), "2D"),
        (np.zeros(SHAPE[::-1], dtype=np.uint16), "but the image is 6 x 8"),
        (np.zeros((6, 9), dtype=np.uint16), "but the image is 6 x 8"),
        (_bad(-1), "negative"),
        (np.where(_labels() > 0, -3, 0).astype(np.int16), "negative"),
        (_bad(1.5), "not whole numbers"),
        (_bad(np.nan), "NaN"),
        (_bad(np.inf), "NaN or infinite"),
    ],
)
def test_bad_file_rejected(tmp_path, array, reason):
    _write(tmp_path, array)
    with pytest.raises(LabelFileError, match=reason) as error:
        read_label_file(tmp_path, IMAGE, SHAPE)
    assert "\n" not in str(error.value)


def test_missing_file(tmp_path):
    with pytest.raises(LabelFileError, match="not found"):
        read_label_file(tmp_path, IMAGE, SHAPE)


def test_file_for_other_image_not_used(tmp_path):
    _write(tmp_path, _labels(), name="other")
    with pytest.raises(LabelFileError, match="not found"):
        read_label_file(tmp_path, IMAGE, SHAPE)


def test_unreadable_file(tmp_path):
    label_file_path(tmp_path, IMAGE).write_bytes(b"this is not a tiff file")
    with pytest.raises(LabelFileError, match="could not be read") as error:
        read_label_file(tmp_path, IMAGE, SHAPE)
    assert "\n" not in str(error.value)


def test_crop_label_file(crop_labels_path):
    name = crop_labels_path.name.removesuffix("_seglabels.tif")
    masks = read_label_file(crop_labels_path.parent, name, (384, 384))
    assert masks.dtype == np.uint32
    labels = np.unique(masks)
    assert labels[0] == 0
    assert len(labels[labels > 0]) == 44
