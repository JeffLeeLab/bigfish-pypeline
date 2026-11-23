"""Tests for OMERO image input, using stand-in connection objects instead of a server."""

import os
import subprocess
import sys
import textwrap
import traceback
from pathlib import Path

import numpy as np
import pytest

from bigfish_pypeline import io

Ice = pytest.importorskip("Ice")
omero_gateway = pytest.importorskip("omero.gateway")

KEY = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
HOST = "omero.example.org"
PORT = 4064


# Stand-ins for the omero-py objects


class FakeLength:
    def __init__(self, value, unit):
        self.value = value
        self.unit = unit

    def getValue(self):
        return self.value

    def getUnit(self):
        return self.unit


class FakeChannel:
    def __init__(self, name=None, label=None):
        self.name = name
        self.label = label

    def getName(self):
        return self.name

    def getLabel(self):
        return self.label


class FakePixels:
    def __init__(self, image):
        self.image = image

    def getPhysicalSizeX(self):
        return self.image.sizes_xyz[0]

    def getPhysicalSizeY(self):
        return self.image.sizes_xyz[1]

    def getPhysicalSizeZ(self):
        return self.image.sizes_xyz[2]

    def getPlanes(self, zct_list):
        conn = self.image.conn
        if conn.failures:
            error = conn.failures.pop(0)
            raise error
        for z, c, t in zct_list:
            yield self.image.data[t, z, c].copy()


class FakeImage:
    """An image stored as a TZCYX array."""

    def __init__(self, image_id, name, data, pixel_type=None, sizes_xyz=None, channels=None):
        self.image_id = image_id
        self.name = name
        self.data = data
        self.pixel_type = pixel_type or str(data.dtype).replace("float32", "float").replace("float64", "double")
        um = FakeLength(0.065, "MICROMETER")
        self.sizes_xyz = sizes_xyz if sizes_xyz is not None else (um, um, FakeLength(0.2, "MICROMETER"))
        self.channels = channels if channels is not None else [FakeChannel(f"ch{c}") for c in range(data.shape[2])]
        self.conn = None

    def getId(self):
        return self.image_id

    def getName(self):
        return self.name

    def getSizeT(self):
        return self.data.shape[0]

    def getSizeZ(self):
        return self.data.shape[1]

    def getSizeC(self):
        return self.data.shape[2]

    def getSizeY(self):
        return self.data.shape[3]

    def getSizeX(self):
        return self.data.shape[4]

    def getPixelsType(self):
        return self.pixel_type

    def getPrimaryPixels(self):
        return FakePixels(self)

    def getChannels(self, noRE=False):
        return self.channels


class FakeDataset:
    def __init__(self, images):
        self.images = images

    def listChildren(self):
        return iter(self.images)


class FakeClient:
    def __init__(self, key):
        self.key = key

    def getSessionId(self):
        if self.key is None:
            raise Exception("No session available")
        return self.key


class FakeConn:
    """A connection serving the given images and datasets.

    `failures` is a list of errors raised, one per read, before reads work.
    `info_failures` is the same for looking up an image (as when its information is read).
    """

    def __init__(self, images=(), datasets=None, failures=None, key=KEY, info_failures=None):
        self.images = {image.image_id: image for image in images}
        for image in images:
            image.conn = self
        self.datasets = datasets or {}
        self.failures = list(failures or [])
        self.info_failures = list(info_failures or [])
        self.c = FakeClient(key)
        self.closed = []

    def getObject(self, kind, object_id):
        object_id = int(object_id)
        if kind == "Image" and self.info_failures:
            raise self.info_failures.pop(0)
        if kind == "Image":
            image = self.images.get(object_id)
            if image is not None:
                image.conn = self
            return image
        if kind == "Dataset":
            return self.datasets.get(object_id)
        raise AssertionError(kind)

    def close(self, hard=True):
        self.closed.append(hard)


def make_data(size_z=3, size_c=2, size_t=1, dtype=np.uint16, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 1000, (size_t, size_z, size_c, 8, 10)).astype(dtype)


def lost():
    return Ice.ConnectionLostException()


# Listing


def test_list_dataset_sorted_by_name_then_id():
    data = make_data()
    images = [
        FakeImage(30, "b.tif", data),
        FakeImage(12, "a.tif", data),
        FakeImage(5, "b.tif", data),
    ]
    conn = FakeConn(images, datasets={7: FakeDataset(images)})
    assert io.list_omero_images(conn, dataset_id=7) == [(12, "a.tif"), (5, "b.tif"), (30, "b.tif")]
    assert io.list_omero_images(conn, dataset_id="Dataset:7") == [(12, "a.tif"), (5, "b.tif"), (30, "b.tif")]


def test_list_ids_keeps_order_without_repeats():
    data = make_data()
    conn = FakeConn([FakeImage(3, "c", data), FakeImage(1, "a", data), FakeImage(2, "b", data)])
    assert io.list_omero_images(conn, image_ids=[3, "1", 3, "Image:2", 1]) == [(3, "c"), (1, "a"), (2, "b")]


def test_list_missing_ids_named():
    conn = FakeConn([FakeImage(1, "a", make_data())])
    with pytest.raises(ValueError, match=r"not found on OMERO.*: 4, 5$"):
        io.list_omero_images(conn, image_ids=[1, 4, 5])


def test_list_missing_dataset():
    with pytest.raises(ValueError, match="Dataset 9 was not found"):
        io.list_omero_images(FakeConn(), dataset_id=9)


def test_list_needs_one_source():
    with pytest.raises(ValueError, match="either"):
        io.list_omero_images(FakeConn())
    with pytest.raises(ValueError, match="either"):
        io.list_omero_images(FakeConn(), dataset_id=1, image_ids=[1])
    with pytest.raises(ValueError, match="whole numbers"):
        io.list_omero_images(FakeConn(), image_ids=["abc"])


def test_list_connection_lost_hides_key():
    class BrokenConn(FakeConn):
        def getObject(self, kind, object_id):
            raise Ice.ObjectNotExistException(id=Ice.Identity(name="x", category=KEY))

    with pytest.raises(ConnectionError) as caught:
        io.list_omero_images(BrokenConn(), image_ids=[1])
    assert_key_hidden(caught.value)


# Output names


@pytest.mark.parametrize(
    "name, expected",
    [
        ('a/b\\c:d*e?f"g<h>i|j.tif', "12_a_b_c_d_e_f_g_h_i_j"),
        ("cell 1 – day 2.tif", "12_cell 1 – day 2"),
        ("Zellkern_grün_é.tif", "12_Zellkern_grün_é"),
        ("tab\there", "12_tab_here"),
        ("image.tiff", "12_image"),
        ("image.TIF", "12_image"),
        ("image.ome.tif", "12_image.ome"),
        ("cell 1.5 uM", "12_cell 1.5 uM"),
        ("image.czi", "12_image.czi"),
        ("tif", "12_tif"),
        (".tif", "12_.tif"),
    ],
)
def test_output_name(name, expected):
    assert io.omero_output_name(12, name) == expected


def test_output_name_same_for_composed_and_decomposed_accents():
    assert io.omero_output_name(1, "é") == io.omero_output_name(1, "é")


# Image information


def test_image_info():
    data = make_data(size_z=3, size_c=2)
    conn = FakeConn([FakeImage(12, "a/b.tif", data)])
    info = io.get_omero_image_info(conn, "12")
    assert (info.size_z, info.size_c, info.size_t, info.size_y, info.size_x) == (3, 2, 1, 8, 10)
    assert info.shape == (3, 2, 8, 10)
    assert info.axes == "ZCYX"
    assert info.layout == "ZCYX"
    assert info.pixel_type == "uint16"
    assert info.dtype == np.uint16
    assert info.nbytes == 3 * 2 * 8 * 10 * 2
    assert (info.voxel_size_z, info.voxel_size_y, info.voxel_size_x) == (200.0, 65.0, 65.0)
    assert info.channel_names == ["ch0", "ch1"]
    assert info.output_name == "12_a_b"
    assert info.n_timepoints == 1 and info.n_positions == 1
    assert not info.xy_sizes_differ


@pytest.mark.parametrize(
    "size_z, size_c, axes",
    [(1, 1, "YX"), (3, 1, "ZYX"), (1, 2, "CYX"), (3, 2, "ZCYX")],
)
def test_image_info_axes(size_z, size_c, axes):
    conn = FakeConn([FakeImage(1, "a", make_data(size_z, size_c))])
    info = io.get_omero_image_info(conn, 1)
    assert info.axes == axes
    assert info.layout == axes


@pytest.mark.parametrize(
    "length, expected",
    [
        (FakeLength(0.065, "MICROMETER"), 65.0),
        (FakeLength(0.2, "MICROMETRE"), 200.0),
        (FakeLength(110, "NANOMETER"), 110.0),
        (FakeLength(0.0001, "MILLIMETER"), 100.0),
        (FakeLength(1.0, "PIXEL"), None),
        (FakeLength(0, "MICROMETER"), None),
        (None, None),
    ],
)
def test_length_to_nm(length, expected):
    assert io._length_to_nm(length) == expected


def test_image_info_missing_and_different_sizes():
    sizes = (FakeLength(0.1, "MICROMETER"), FakeLength(0.2, "MICROMETER"), None)
    channels = [FakeChannel(None, "525"), FakeChannel(None, None)]
    conn = FakeConn([FakeImage(1, "a", make_data(size_z=3, size_c=2), sizes_xyz=sizes, channels=channels)])
    info = io.get_omero_image_info(conn, 1)
    assert info.voxel_size_z is None
    assert (info.voxel_size_y, info.voxel_size_x) == (200.0, 100.0)
    assert info.xy_sizes_differ
    assert info.channel_names == ["525", "Channel 1"]


def test_image_info_works_with_voxel_size_check():
    conn = FakeConn([FakeImage(4, "img", make_data())])
    info = io.get_omero_image_info(conn, 4)
    assert io.check_voxel_sizes(info, 200, 65) is None
    assert io.check_voxel_sizes(info, 300, 65).startswith("4_img: voxel sizes differ")


def test_image_info_unknown_pixel_type():
    conn = FakeConn([FakeImage(1, "a", make_data(), pixel_type="bit")])
    info = io.get_omero_image_info(conn, 1)
    assert info.dtype is None and info.nbytes is None


def test_image_info_missing_image():
    with pytest.raises(io.ImageReadError, match="OMERO image 3: not found"):
        io.get_omero_image_info(FakeConn(), 3)


# Reading


@pytest.mark.parametrize(
    "size_z, size_c, layout",
    [
        (3, 2, "ZCYX"),
        (3, 2, "CZYX"),
        (3, 1, "ZYX"),
        (1, 2, "CYX"),
        (1, 1, "YX"),
    ],
)
def test_read_layouts(size_z, size_c, layout):
    data = make_data(size_z, size_c)
    conn = FakeConn([FakeImage(1, "a", data)])
    channels = list(range(size_c))
    arrays = io.read_omero_channels(conn, 1, layout, channels)
    assert list(arrays) == channels
    for channel in channels:
        expected = data[0, :, channel] if "Z" in layout else data[0, 0, channel]
        np.testing.assert_array_equal(arrays[channel], expected)
        assert arrays[channel].dtype == data.dtype


def test_read_one_channel_float():
    data = make_data(3, 2, dtype=np.float32)
    conn = FakeConn([FakeImage(1, "a", data)])
    np.testing.assert_array_equal(io.read_omero_channel(conn, 1, "CZYX", 1), data[0, :, 1])


@pytest.mark.parametrize(
    "size_z, size_c, layout",
    [
        (3, 2, "ZYX"),
        (3, 2, "CYX"),
        (1, 2, "ZCYX"),
        (3, 1, "CZYX"),
        (1, 1, "ZYX"),
        (3, 1, "YX"),
    ],
)
def test_read_layout_mismatch(size_z, size_c, layout):
    conn = FakeConn([FakeImage(1, "a", make_data(size_z, size_c))])
    with pytest.raises(io.ImageReadError, match=f"does not fit the layout {layout}"):
        io.read_omero_channels(conn, 1, layout, [0])


def test_read_unknown_layout():
    conn = FakeConn([FakeImage(1, "a", make_data())])
    with pytest.raises(ValueError, match="Layout must be"):
        io.read_omero_channels(conn, 1, "XYZ", [0])


@pytest.mark.parametrize("channel", [2, -1])
def test_read_bad_channel(channel):
    conn = FakeConn([FakeImage(1, "a", make_data(3, 2))])
    with pytest.raises(io.ImageReadError, match=rf"channel {channel} does not exist; the image has 2 channels \(0–1\)"):
        io.read_omero_channels(conn, 1, "ZCYX", [0, channel])


def test_read_several_time_points():
    conn = FakeConn([FakeImage(1, "a", make_data(3, 2, size_t=4))])
    with pytest.raises(io.ImageReadError, match="4 time points; only one is accepted"):
        io.read_omero_channels(conn, 1, "ZCYX", [0])


def test_read_missing_image():
    with pytest.raises(io.ImageReadError, match="not found"):
        io.read_omero_channels(FakeConn(), 1, "ZCYX", [0])


def test_read_connection_lost_without_retry():
    conn = FakeConn([FakeImage(1, "a", make_data())], failures=[lost()])
    with pytest.raises(io.ImageReadError, match="lost the connection") as caught:
        io.read_omero_channels(conn, 1, "ZCYX", [0])
    assert_key_hidden(caught.value)


# Retry after a dropped connection


def test_retry_after_rejoining(monkeypatch):
    data = make_data()
    first = FakeConn([FakeImage(1, "a", data)], failures=[lost()])
    second = FakeConn([FakeImage(1, "a", data)])
    joins = []

    def fake_join(host, port, key):
        joins.append((host, port, key))
        return second

    monkeypatch.setattr(io, "join_session", fake_join)
    arrays, conn = io.read_omero_channels_with_retry(first, 1, "ZCYX", [0, 1], HOST, PORT, KEY)
    assert conn is second
    assert joins == [(HOST, PORT, KEY)]
    assert first.closed == [False]
    for channel in (0, 1):
        np.testing.assert_array_equal(arrays[channel], data[0, :, channel])


def test_no_retry_when_read_works(monkeypatch):
    conn = FakeConn([FakeImage(1, "a", make_data())])
    monkeypatch.setattr(io, "join_session", lambda *args: pytest.fail("should not rejoin"))
    arrays, same = io.read_omero_channels_with_retry(conn, 1, "ZCYX", [0], HOST, PORT, KEY)
    assert same is conn and conn.closed == []


def test_no_retry_for_image_problems(monkeypatch):
    conn = FakeConn([FakeImage(1, "a", make_data())])
    monkeypatch.setattr(io, "join_session", lambda *args: pytest.fail("should not rejoin"))
    with pytest.raises(io.ImageReadError, match="does not exist"):
        io.read_omero_channels_with_retry(conn, 1, "ZCYX", [5], HOST, PORT, KEY)


def test_retry_fails_twice(monkeypatch):
    error = Ice.ObjectNotExistException(id=Ice.Identity(name="x", category=KEY))
    first = FakeConn([FakeImage(1, "a", make_data())], failures=[lost()])
    second = FakeConn([FakeImage(1, "a", make_data())], failures=[error])
    monkeypatch.setattr(io, "join_session", lambda host, port, key: second)
    with pytest.raises(io.ImageReadError, match="lost the connection to OMERO twice") as caught:
        io.read_omero_channels_with_retry(first, 1, "ZCYX", [0], HOST, PORT, KEY)
    assert_key_hidden(caught.value)


def test_retry_cannot_reconnect(monkeypatch):
    first = FakeConn([FakeImage(1, "a", make_data())], failures=[lost()])

    def no_server(host, port, key):
        raise ConnectionError("cannot reach the OMERO server")

    monkeypatch.setattr(io, "join_session", no_server)
    with pytest.raises(io.ImageReadError, match="could not reconnect") as caught:
        io.read_omero_channels_with_retry(first, 1, "ZCYX", [0], HOST, PORT, KEY)
    assert_key_hidden(caught.value)


def test_retry_session_ended(monkeypatch):
    first = FakeConn([FakeImage(1, "a", make_data())], failures=[lost()])

    def ended(host, port, key):
        raise io.OmeroSessionEnded("The OMERO session has ended. Log in again and start a new run.")

    monkeypatch.setattr(io, "join_session", ended)
    with pytest.raises(io.OmeroSessionEnded) as caught:
        io.read_omero_channels_with_retry(first, 1, "ZCYX", [0], HOST, PORT, KEY)
    assert_key_hidden(caught.value)


def test_retry_log_hides_key(monkeypatch, caplog):
    error = Ice.ObjectNotExistException(id=Ice.Identity(name="x", category=KEY))
    first = FakeConn([FakeImage(1, "a", make_data())], failures=[error])
    second = FakeConn([FakeImage(1, "a", make_data())])
    monkeypatch.setattr(io, "join_session", lambda host, port, key: second)
    with caplog.at_level("DEBUG"):
        io.read_omero_channels_with_retry(first, 1, "ZCYX", [0], HOST, PORT, KEY)
    assert "rejoining the session" in caplog.text
    assert KEY not in caplog.text


def test_info_connection_lost_is_an_image_read_error():
    error = Ice.ObjectNotExistException(id=Ice.Identity(name="x", category=KEY))
    conn = FakeConn([FakeImage(1, "a", make_data())], info_failures=[error])
    with pytest.raises(io.OmeroConnectionLost, match="OMERO image 1: lost the connection to OMERO") as caught:
        io.get_omero_image_info(conn, 1)
    assert isinstance(caught.value, io.ImageReadError)
    assert KEY not in caught.value.reason
    assert_key_hidden(caught.value)


def test_reader_rejoins_when_reading_the_information(monkeypatch):
    data = make_data()
    first = FakeConn([FakeImage(1, "a", data)], info_failures=[lost()])
    second = FakeConn([FakeImage(1, "a", data)])
    joins = []

    def fake_join(host, port, key):
        joins.append(key)
        return second

    monkeypatch.setattr(io, "join_session", fake_join)
    notes = []
    reader = io.OmeroImageReader(first, 1, HOST, PORT, KEY, notes=notes)
    assert reader.info().size_c == 2
    assert reader.conn is second and first.closed == [False]
    assert len(notes) == 1
    assert notes[0].startswith("OMERO image 1: lost the connection to OMERO (ConnectionLostException")
    assert notes[0].endswith("; rejoining the session and trying again")
    # the channels are read with the new connection, without joining again
    arrays = reader.channels("ZCYX", [1])
    np.testing.assert_array_equal(arrays[1], data[0, :, 1])
    assert joins == [KEY]


def test_reader_rejoins_once_for_the_whole_image(monkeypatch):
    data = make_data()
    first = FakeConn([FakeImage(1, "a", data)], info_failures=[lost()])
    second = FakeConn([FakeImage(1, "a", data)], failures=[lost()])
    joins = []

    def fake_join(host, port, key):
        joins.append(key)
        return second

    monkeypatch.setattr(io, "join_session", fake_join)
    reader = io.OmeroImageReader(first, 1, HOST, PORT, KEY, notes=[])
    reader.info()
    with pytest.raises(io.ImageReadError, match="lost the connection to OMERO twice") as caught:
        reader.channels("ZCYX", [0])
    assert not isinstance(caught.value, io.OmeroConnectionLost)
    assert joins == [KEY]
    assert reader.conn is second


def test_reader_information_lost_twice(monkeypatch):
    first = FakeConn([FakeImage(1, "a", make_data())], info_failures=[lost()])
    second = FakeConn([FakeImage(1, "a", make_data())], info_failures=[lost()])
    monkeypatch.setattr(io, "join_session", lambda host, port, key: second)
    reader = io.OmeroImageReader(first, 1, HOST, PORT, KEY, notes=[])
    with pytest.raises(io.ImageReadError, match="^OMERO image 1: lost the connection to OMERO twice"):
        reader.info()


def test_reader_session_ended(monkeypatch):
    first = FakeConn([FakeImage(1, "a", make_data())], info_failures=[lost()])

    def ended(host, port, key):
        raise io.OmeroSessionEnded("The OMERO session has ended. Log in again and start a new run.")

    monkeypatch.setattr(io, "join_session", ended)
    reader = io.OmeroImageReader(first, 1, HOST, PORT, KEY, notes=[])
    with pytest.raises(io.OmeroSessionEnded):
        reader.info()
    assert first.closed == [False]
    assert reader.conn is None


def test_reader_cannot_reconnect(monkeypatch):
    first = FakeConn([FakeImage(1, "a", make_data())], info_failures=[lost()])

    def no_server(host, port, key):
        raise ConnectionError(f"cannot reach the OMERO server ({KEY})")

    monkeypatch.setattr(io, "join_session", no_server)
    reader = io.OmeroImageReader(first, 1, HOST, PORT, KEY, notes=[])
    with pytest.raises(io.ImageReadError, match="could not reconnect") as caught:
        reader.info()
    assert_key_hidden(caught.value)
    assert reader.conn is None
    with pytest.raises(io.ImageReadError, match="no connection to OMERO"):
        reader.channels("ZCYX", [0])


# Session sharing


class FakeGateway:
    """Stand-in for omero.gateway.BlitzGateway."""

    made = []
    result = True

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = []
        FakeGateway.made.append(self)

    def connect(self, sUuid=None):
        self.joined_with = sUuid
        if isinstance(FakeGateway.result, Exception):
            raise FakeGateway.result
        return FakeGateway.result

    def close(self, hard=True):
        self.closed.append(hard)


@pytest.fixture
def fake_gateway(monkeypatch):
    FakeGateway.made = []
    FakeGateway.result = True
    monkeypatch.setattr(omero_gateway, "BlitzGateway", FakeGateway)
    return FakeGateway


def test_session_key():
    assert io.session_key(FakeConn()) == KEY
    with pytest.raises(ConnectionError, match="Not logged in"):
        io.session_key(FakeConn(key=None))


def test_join_session(fake_gateway):
    conn = io.join_session(HOST, "4064", KEY)
    assert conn.kwargs == {"host": HOST, "port": 4064, "secure": True}
    assert conn.joined_with == KEY
    assert conn.closed == []


def test_join_session_refused(fake_gateway):
    fake_gateway.result = False
    with pytest.raises(io.OmeroSessionEnded, match="Log in again") as caught:
        io.join_session(HOST, PORT, KEY)
    assert fake_gateway.made[0].closed == [False]
    assert_key_hidden(caught.value)


def test_join_session_no_server(fake_gateway):
    fake_gateway.result = Ice.ConnectionRefusedException(error=61)
    with pytest.raises(ConnectionError, match=f"cannot reach the OMERO server at {HOST}:{PORT}") as caught:
        io.join_session(HOST, PORT, KEY)
    assert fake_gateway.made[0].closed == [False]
    assert_key_hidden(caught.value)


def test_join_session_error_with_key_in_text(fake_gateway):
    other_key = "plain-secret-key"
    fake_gateway.result = RuntimeError(f"cannot join {other_key}")
    with pytest.raises(ConnectionError) as caught:
        io.join_session(HOST, PORT, other_key)
    assert_key_hidden(caught.value, other_key)


def test_detach_session_keeps_session():
    conn = FakeConn()
    io.detach_session(conn)
    assert conn.closed == [False]

    class Broken:
        def close(self, hard=True):
            raise RuntimeError("already gone")

    io.detach_session(Broken())


def test_key_hidden_with_known_non_uuid_key():
    other_key = "plain-secret-key"
    error = Ice.ObjectNotExistException(id=Ice.Identity(name="x", category=other_key))
    conn = FakeConn([FakeImage(1, "a", make_data())], failures=[error], key=other_key)
    with pytest.raises(io.ImageReadError) as caught:
        io.read_omero_channels(conn, 1, "ZCYX", [0])
    assert_key_hidden(caught.value, other_key)


def assert_key_hidden(error, key=KEY):
    """The key is in neither the message, the repr nor the printed traceback of `error`."""
    text = "".join(traceback.format_exception(error))
    assert key not in str(error)
    assert key not in repr(error)
    assert key not in text


# Imports


def test_io_import_does_not_load_omero():
    code = "import sys, bigfish_pypeline.io; print(any(m.split('.')[0] in ('omero', 'Ice', 'Glacier2') for m in sys.modules))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


def run_fresh(code):
    """Run Python code in a fresh process, with the tests folder on the path; returns (stdout, stderr)."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).parent)] + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [])
    )
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True,
                          env=environment, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout, done.stderr


@pytest.mark.parametrize("module", ["bigfish_pypeline.io", "bigfish_pypeline.batch"])
def test_import_leaves_the_root_logger_alone(module):
    stdout, _ = run_fresh(f"""
        import logging
        root = logging.getLogger()
        before = (list(root.handlers), root.level)
        import {module}
        print((list(root.handlers), root.level) == before)
    """)
    assert stdout.strip() == "True"


# Logging


def test_omero_messages_silenced():
    """Nothing omero-py logs reaches the screen, even with logging set up as omero-py
    sets it up, and before the package knows any session key."""
    stdout, stderr = run_fresh(f"""
        import logging
        import bigfish_pypeline.io
        import Ice
        import omero.gateway
        from batch_helpers import log_like_omero

        log_like_omero("{KEY}")

        # omero-py's own wrapper logs a call that fails with a dropped connection
        def find_by_query(*arguments):
            raise Ice.ConnectionLostException()

        wrapper = omero.gateway.OmeroGatewaySafeCallWrapper(None, "findByQuery", find_by_query)
        try:
            wrapper("select obj from Image obj", {{"omero.session.uuid": "{KEY}"}})
        except Ice.ConnectionLostException:
            pass
        logging.getLogger("omero.gateway.utils").setLevel(logging.DEBUG)
        logging.getLogger("omero.gateway.utils").error("lost session {KEY}")
        logging.getLogger("some.package").warning("a warning of another package")
    """)
    terminal = stdout + stderr
    assert KEY not in terminal
    assert "omero" not in terminal
    assert "Traceback" not in terminal
    # logging.basicConfig() is in effect here, as omero-py set it up
    assert "WARNING:some.package:a warning of another package" in stderr


def test_plain_logging():
    stdout, stderr = run_fresh(f"""
        import logging
        from bigfish_pypeline import io
        from batch_helpers import log_like_omero

        root = logging.getLogger()
        with io.plain_logging():
            log_like_omero("{KEY}")
            assert len(root.handlers) == 1, root.handlers
            logging.getLogger("some.package").warning("a warning of another package")
            logging.getLogger("some.package").error("an error of another package")
            logging.getLogger("some.package").info("not shown")
        assert root.handlers == [], root.handlers

        # a handler set up by the program is kept, and nothing is added
        handler = logging.StreamHandler()
        root.addHandler(handler)
        with io.plain_logging():
            assert root.handlers == [handler]
        assert root.handlers == [handler]
    """)
    terminal = stdout + stderr
    assert KEY not in terminal
    assert "CPDINO" not in terminal
    assert "killSession" not in terminal
    assert "WARNING:" not in terminal
    # warnings that no handler takes are shown as Python shows them without any set-up
    assert stderr.splitlines() == ["a warning of another package", "an error of another package"]
