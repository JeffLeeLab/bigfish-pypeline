"""Tests for reading local TIFF images."""

from pathlib import Path

import numpy as np
import pytest
import tifffile

from bigfish_pypeline import io

SIZES = {"Z": 3, "C": 2, "Y": 10, "X": 12}
DTYPES = [np.uint8, np.uint16]
REFUSED_DTYPES = [np.float32, np.int16, np.int32, np.uint32]
# Pixel sizes written to the metadata, in µm: Z, Y, X.
VOXEL_UM = (0.2, 0.065, 0.065)


def make_array(layout, dtype, seed=0):
    rng = np.random.default_rng(seed)
    shape = tuple(SIZES[axis] for axis in layout)
    if np.dtype(dtype).kind == "f":
        return rng.uniform(0, 1000, shape).astype(dtype)
    return rng.integers(0, np.iinfo(dtype).max, shape, endpoint=True).astype(dtype)


def write_tiff(path, array, layout, kind, voxel_um=VOXEL_UM):
    """Write `array` as an ImageJ, OME, tifffile-shaped or plain TIFF file."""
    z, y, x = voxel_um
    if kind == "imagej":
        metadata = {"axes": layout}
        if "Z" in layout:
            metadata.update(spacing=z, unit="um")
        else:
            metadata.update(unit="um")
        tifffile.imwrite(path, array, imagej=True, metadata=metadata, resolution=(1 / x, 1 / y))
    elif kind == "ome":
        metadata = {"axes": layout, "PhysicalSizeX": x, "PhysicalSizeY": y}
        if "Z" in layout:
            metadata["PhysicalSizeZ"] = z
        tifffile.imwrite(path, array, ome=True, metadata=metadata)
    elif kind == "shaped":
        tifffile.imwrite(path, array, metadata={"axes": layout}, photometric="minisblack")
    elif kind == "plain":
        planes = array.reshape(-1, *array.shape[-2:])
        tifffile.imwrite(path, planes if planes.shape[0] > 1 else planes[0], metadata=None, photometric="minisblack")
    return path


def expected_channel(array, layout, channel):
    if layout == "ZCYX":
        return array[:, channel]
    if layout in ("CZYX", "CYX"):
        return array[channel]
    return array


def n_channels(layout):
    return SIZES["C"] if "C" in layout else 1


# Every layout, metadata kind and data type

CASES = [
    (layout, kind)
    for layout in io.LAYOUTS
    for kind in ("imagej", "ome", "shaped", "plain")
    # ImageJ always stores Z before C; a plain TIFF cannot record two stacked axes.
    if not (kind == "imagej" and layout == "CZYX") and not (kind == "plain" and len(layout) == 4)
]


@pytest.mark.parametrize("dtype", DTYPES, ids=lambda d: np.dtype(d).name)
@pytest.mark.parametrize("layout,kind", CASES)
def test_read_every_layout(tmp_path, layout, kind, dtype):
    array = make_array(layout, dtype)
    path = write_tiff(tmp_path / f"{layout}_{kind}.tif", array, layout, kind)

    info = io.get_image_info(path)
    assert info.shape == array.shape
    assert info.dtype == np.dtype(dtype)
    assert info.n_timepoints == 1
    assert info.n_positions == 1
    assert info.nbytes == array.nbytes

    if kind == "plain":
        assert info.layout is None
    else:
        assert info.layout == layout

    if kind in ("imagej", "ome"):
        assert info.voxel_size_y == 65
        assert info.voxel_size_x == 65
        assert info.voxel_size_z == (200 if "Z" in layout else None)
        assert not info.xy_sizes_differ
    else:
        assert (info.voxel_size_z, info.voxel_size_y, info.voxel_size_x) == (None, None, None)

    for channel in range(n_channels(layout)):
        data = io.read_channel(path, layout, channel)
        assert data.dtype == np.dtype(dtype)
        np.testing.assert_array_equal(data, expected_channel(array, layout, channel))


def test_read_several_channels(tmp_path):
    array = make_array("CZYX", np.uint16)
    path = write_tiff(tmp_path / "image.tif", array, "CZYX", "ome")
    channels = io.read_channels(path, "CZYX", [1, 0])
    assert list(channels) == [1, 0]
    for channel, data in channels.items():
        np.testing.assert_array_equal(data, array[channel])


@pytest.mark.parametrize("kind", ["imagej", "ome", "shaped"])
def test_axes_in_metadata_must_match_the_layout(tmp_path, kind):
    path = write_tiff(tmp_path / "image.tif", make_array("ZCYX", np.uint16), "ZCYX", kind)
    message = r"image.tif: the file's own information says its axes are stored in the order ZCYX, " \
              r"which does not match the layout CZYX of this run"
    with pytest.raises(io.ImageReadError, match=message):
        io.read_channel(path, "CZYX", 1)
    with pytest.raises(io.ImageReadError, match=message):
        io.check_image(path, "CZYX")


def test_layout_used_when_metadata_gives_no_axes(tmp_path):
    # tifffile's own metadata without axes: tifffile calls the first two axes Q.
    array = make_array("ZCYX", np.uint16)
    path = tmp_path / "image.tif"
    tifffile.imwrite(path, array, photometric="minisblack")
    assert io.get_image_info(path).layout is None
    io.check_image(path, "CZYX", [1])
    np.testing.assert_array_equal(io.read_channel(path, "CZYX", 1), array[1])
    np.testing.assert_array_equal(io.read_channel(path, "ZCYX", 1), array[:, 1])


def test_imagej_without_axes_read_with_the_layout(tmp_path):
    # ImageJ metadata giving only the number of images: tifffile calls that axis I.
    array = make_array("ZYX", np.uint16)
    path = tmp_path / "image.tif"
    tifffile.imwrite(path, array, description=f"ImageJ=1.11a\nimages={len(array)}\n", photometric="minisblack",
                     metadata=None)
    with tifffile.TiffFile(path) as tif:
        assert tif.series[0].kind == "imagej" and tif.series[0].axes == "IYX"
    np.testing.assert_array_equal(io.read_channel(path, "ZYX", 0), array)
    np.testing.assert_array_equal(io.read_channel(path, "CYX", 2), array[2])


@pytest.mark.parametrize("kind", ["imagej", "ome"])
def test_different_x_and_y_pixel_sizes(tmp_path, kind):
    path = write_tiff(tmp_path / "image.tif", make_array("ZYX", np.uint16), "ZYX", kind, voxel_um=(0.3, 0.07, 0.065))
    info = io.get_image_info(path)
    assert info.voxel_size_z == 300
    assert info.voxel_size_y == 70
    assert info.voxel_size_x == 65
    assert info.xy_sizes_differ


def test_ome_sizes_in_nm(tmp_path):
    path = tmp_path / "image.ome.tif"
    metadata = {"axes": "ZYX", "PhysicalSizeZ": 250, "PhysicalSizeZUnit": "nm",
                "PhysicalSizeY": 110, "PhysicalSizeYUnit": "nm", "PhysicalSizeX": 110, "PhysicalSizeXUnit": "nm"}
    tifffile.imwrite(path, make_array("ZYX", np.uint16), ome=True, metadata=metadata)
    info = io.get_image_info(path)
    assert (info.voxel_size_z, info.voxel_size_y, info.voxel_size_x) == (250, 110, 110)


def test_imagej_without_calibration(tmp_path):
    path = tmp_path / "image.tif"
    tifffile.imwrite(path, make_array("ZYX", np.uint16), imagej=True, metadata={"axes": "ZYX"})
    info = io.get_image_info(path)
    assert info.layout == "ZYX"
    assert (info.voxel_size_z, info.voxel_size_y, info.voxel_size_x) == (None, None, None)


def test_single_channel_reported_without_channel_axis(tmp_path):
    array = make_array("ZCYX", np.uint16)[:, :1]
    path = tmp_path / "image.tif"
    tifffile.imwrite(path, array, imagej=True, metadata={"axes": "ZCYX"})
    info = io.get_image_info(path)
    assert info.layout == "ZYX"
    np.testing.assert_array_equal(io.read_channel(path, "ZYX", 0), array[:, 0])


# Time points, positions and other rejected files


def test_single_time_point_is_dropped(tmp_path):
    array = make_array("ZYX", np.uint16)[np.newaxis]
    path = tmp_path / "image.tif"
    tifffile.imwrite(path, array, imagej=True, metadata={"axes": "TZYX"})
    info = io.get_image_info(path)
    assert info.layout == "ZYX"
    assert info.n_timepoints == 1
    np.testing.assert_array_equal(io.read_channel(path, "ZYX", 0), array[0])


def test_several_time_points_rejected(tmp_path):
    array = np.stack([make_array("ZYX", np.uint16, seed) for seed in range(2)])
    path = tmp_path / "image.tif"
    tifffile.imwrite(path, array, imagej=True, metadata={"axes": "TZYX"})
    info = io.get_image_info(path)
    assert info.n_timepoints == 2
    assert info.layout is None
    with pytest.raises(io.ImageReadError, match="2 time points"):
        io.read_channel(path, "ZYX", 0)


def test_several_positions_rejected(tmp_path):
    path = tmp_path / "image.ome.tif"
    with tifffile.TiffWriter(path, ome=True) as tif:
        for seed in range(2):
            tif.write(make_array("ZYX", np.uint16, seed), metadata={"axes": "ZYX"})
    assert io.get_image_info(path).n_positions == 2
    with pytest.raises(io.ImageReadError, match="2 positions"):
        io.read_channel(path, "ZYX", 0)


ONE_BLOCK_KINDS = {
    "imagej": {"imagej": True},
    "shaped": {"photometric": "minisblack"},
}


def write_one_block(path, array, layout, kind, byteorder="<"):
    """Write the whole image as one page, as ImageJ does for files over 4 GB."""
    tifffile.imwrite(path, array, metadata={"axes": layout}, truncate=True, byteorder=byteorder, **ONE_BLOCK_KINDS[kind])
    with tifffile.TiffFile(path) as tif:
        assert tif.series[0].is_truncated
        assert len(tif.pages) == 1
    return path


@pytest.mark.parametrize("kind", ONE_BLOCK_KINDS)
@pytest.mark.parametrize("layout", ["ZCYX", "ZYX"])
def test_read_whole_image_in_one_page(tmp_path, layout, kind):
    array = make_array(layout, np.uint16)
    path = write_one_block(tmp_path / "image.tif", array, layout, kind)

    info = io.get_image_info(path)
    assert info.shape == array.shape
    assert info.layout == layout
    assert info.dtype == np.uint16

    for channel in range(n_channels(layout)):
        data = io.read_channel(path, layout, channel)
        assert data.flags.owndata
        np.testing.assert_array_equal(data, expected_channel(array, layout, channel))
    # The file is released after reading.
    path.unlink()


def test_read_whole_image_in_one_page_big_endian(tmp_path):
    array = make_array("ZCYX", np.uint16)
    path = write_one_block(tmp_path / "image.tif", array, "ZCYX", "shaped", byteorder=">")
    data = io.read_channel(path, "ZCYX", 1)
    assert data.dtype == np.dtype("=u2")
    np.testing.assert_array_equal(data, array[:, 1])


@pytest.mark.parametrize("kind", ONE_BLOCK_KINDS)
def test_whole_image_in_one_page_cut_short(tmp_path, kind):
    path = write_one_block(tmp_path / "image.tif", make_array("ZCYX", np.uint16), "ZCYX", kind)
    with tifffile.TiffFile(path) as tif:
        data_start = tif.series[0].dataoffset
    path.write_bytes(path.read_bytes()[: data_start + 100])
    with pytest.raises(io.ImageReadError, match="image.tif: the file is damaged or incomplete"):
        io.read_channel(path, "ZCYX", 1)


def test_truncated_file(tmp_path):
    path = write_tiff(tmp_path / "image.tif", make_array("ZCYX", np.uint16), "ZCYX", "imagej")
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    with pytest.raises(io.ImageReadError, match="image.tif: the file is damaged or incomplete"):
        io.get_image_info(path)
    with pytest.raises(io.ImageReadError, match="image.tif: the file is damaged or incomplete"):
        io.read_channel(path, "ZCYX", 1)


def test_truncated_pixel_data(tmp_path):
    # Each plane stored after its own header, then the file cut inside the last plane.
    path = tmp_path / "image.tif"
    with tifffile.TiffWriter(path) as tif:
        for plane in make_array("ZYX", np.uint16):
            tif.write(plane, contiguous=False, metadata=None, photometric="minisblack")
    with tifffile.TiffFile(path) as tif:
        last_plane_start = tif.pages[-1].dataoffsets[0]
    path.write_bytes(path.read_bytes()[: last_plane_start + 100])
    with pytest.raises(io.ImageReadError, match="image.tif: the pixel data cannot be read"):
        io.read_channel(path, "ZYX", 0)


def test_not_a_tiff_file(tmp_path):
    path = tmp_path / "image.tif"
    path.write_text("not an image")
    with pytest.raises(io.ImageReadError, match="not a readable TIFF file"):
        io.get_image_info(path)
    with pytest.raises(io.ImageReadError, match="not a readable TIFF file"):
        io.read_channel(path, "ZYX", 0)


def test_missing_file(tmp_path):
    with pytest.raises(io.ImageReadError, match="file not found"):
        io.read_channel(tmp_path / "missing.tif", "ZYX", 0)


# Pixel types

REFUSED_TEXT = {
    "float32": "32-bit with decimal values (float32)",
    "int16": "16-bit signed (int16)",
    "int32": "32-bit signed (int32)",
    "uint32": "32-bit (uint32)",
}
CONVERT_TEXT = (
    "only 8-bit, 12-bit and 16-bit images are accepted. Convert the image to 16-bit, for example in Fiji "
    "with Image › Type › 16-bit (https://imagej.net/ij/docs/menus/image.html#type), then run it again. In Fiji, first untick \"Scale when converting\" under Edit › Options › Conversions, so that the pixel values are kept."
)


@pytest.mark.parametrize("dtype", REFUSED_DTYPES, ids=lambda d: np.dtype(d).name)
def test_other_pixel_types_refused(tmp_path, dtype):
    path = write_tiff(tmp_path / "image.tif", make_array("ZCYX", dtype), "ZCYX", "ome")
    name = np.dtype(dtype).name
    expected = f"image.tif: the pixel type is {REFUSED_TEXT[name]}, which cannot be used; {CONVERT_TEXT}"
    info = io.get_image_info(path)
    assert info.dtype == np.dtype(dtype)
    assert io.pixel_type_problem(info) == expected
    with pytest.raises(io.ImageReadError) as caught:
        io.check_image(path, "ZCYX")
    assert str(caught.value) == expected
    with pytest.raises(io.ImageReadError) as caught:
        io.read_channel(path, "ZCYX", 0)
    assert str(caught.value) == expected


@pytest.mark.parametrize("dtype", DTYPES, ids=lambda d: np.dtype(d).name)
def test_accepted_pixel_types(tmp_path, dtype):
    path = write_tiff(tmp_path / "image.tif", make_array("ZYX", dtype), "ZYX", "imagej")
    assert io.pixel_type_problem(io.get_image_info(path)) is None


def twelve_bit_array(layout="ZCYX"):
    """Values from 0 to 4095, as a 12-bit camera gives them."""
    rng = np.random.default_rng(12)
    shape = tuple(SIZES[axis] for axis in layout)
    array = rng.integers(0, 4095, shape, endpoint=True).astype(np.uint16)
    array.flat[0], array.flat[1] = 0, 4095
    return array


def test_12_bit_values_in_a_16_bit_file(tmp_path):
    array = twelve_bit_array()
    path = write_tiff(tmp_path / "image.tif", array, "ZCYX", "imagej")
    assert io.get_image_info(path).dtype == np.uint16
    for channel in range(2):
        data = io.read_channel(path, "ZCYX", channel)
        assert data.dtype == np.uint16
        np.testing.assert_array_equal(data, array[:, channel])


def test_packed_12_bit_file(tmp_path):
    array = twelve_bit_array()
    path = tmp_path / "image.tif"
    tifffile.imwrite(path, array, bitspersample=12, imagej=True, metadata={"axes": "ZCYX"})
    with tifffile.TiffFile(path) as tif:
        assert tif.pages[0].bitspersample == 12
        # each 12-bit value takes one and a half bytes in the file
        assert tif.pages[0].databytecounts[0] == SIZES["Y"] * SIZES["X"] * 3 // 2
    info = io.get_image_info(path)
    assert info.dtype == np.uint16
    io.check_image(path, "ZCYX", [0, 1])
    for channel in range(2):
        data = io.read_channel(path, "ZCYX", channel)
        assert data.dtype == np.uint16
        np.testing.assert_array_equal(data, array[:, channel])


# Checking an image without reading its pixels


def compressed_in_one_block(path, array):
    """A compressed file holding each channel's Z stack in one page: the file cannot be mapped."""
    tifffile.imwrite(path, array, volumetric=True, tile=(SIZES["Z"], 16, 16), compression="zlib",
                     metadata={"axes": "CZYX"}, photometric="minisblack")
    with tifffile.TiffFile(path) as tif:
        assert len(tif.series[0].pages) == SIZES["C"]
        assert tif.series[0].dataoffset is None
    return path


def no_pixel_reading(monkeypatch):
    def refuse(*arguments, **keywords):
        raise AssertionError("pixel data were read")

    monkeypatch.setattr(tifffile, "memmap", refuse)
    monkeypatch.setattr(tifffile.TiffFile, "asarray", refuse)
    monkeypatch.setattr(tifffile.TiffPage, "asarray", refuse)
    monkeypatch.setattr(tifffile.TiffPage, "segments", refuse)


@pytest.mark.parametrize("kind", ["one_block", "pages"])
def test_check_image_reads_no_pixel_data(tmp_path, monkeypatch, kind):
    array = make_array("CZYX", np.uint16)
    if kind == "one_block":
        path = compressed_in_one_block(tmp_path / "image.tif", array)
    else:
        path = tmp_path / "image.tif"
        tifffile.imwrite(path, array, compression="zlib", metadata={"axes": "CZYX"}, photometric="minisblack")
    np.testing.assert_array_equal(io.read_channel(path, "CZYX", 1), array[1])
    no_pixel_reading(monkeypatch)
    io.check_image(path, "CZYX", [0, 1])
    assert io.read_channels(path, "CZYX", []) == {}
    with pytest.raises(io.ImageReadError, match="channel 2 does not exist"):
        io.check_image(path, "CZYX", [2])


def test_channel_out_of_range(tmp_path):
    path = write_tiff(tmp_path / "image.tif", make_array("ZCYX", np.uint16), "ZCYX", "imagej")
    with pytest.raises(io.ImageReadError, match="channel 2 does not exist; the image has 2 channels"):
        io.read_channel(path, "ZCYX", 2)


def test_channel_out_of_range_without_channel_axis(tmp_path):
    path = write_tiff(tmp_path / "image.tif", make_array("ZYX", np.uint16), "ZYX", "imagej")
    with pytest.raises(io.ImageReadError, match="channel 1 does not exist; the image has 1 channel "):
        io.read_channel(path, "ZYX", 1)


def test_wrong_layout(tmp_path):
    path = write_tiff(tmp_path / "image.tif", make_array("ZCYX", np.uint16), "ZCYX", "imagej")
    with pytest.raises(io.ImageReadError, match=r"has 4 axes \(3 × 2 × 10 × 12\) but the layout ZYX needs 3"):
        io.read_channel(path, "ZYX", 0)


def test_plain_file_cannot_hold_two_stacked_axes(tmp_path):
    path = write_tiff(tmp_path / "image.tif", make_array("ZCYX", np.uint16), "ZCYX", "plain")
    with pytest.raises(io.ImageReadError, match="layout ZCYX needs 4"):
        io.read_channel(path, "ZCYX", 0)


def test_unknown_layout(tmp_path):
    path = write_tiff(tmp_path / "image.tif", make_array("ZYX", np.uint16), "ZYX", "imagej")
    with pytest.raises(ValueError, match="Layout must be one of"):
        io.read_channel(path, "TZYX", 0)


def test_colour_image_rejected(tmp_path):
    path = tmp_path / "image.tif"
    tifffile.imwrite(path, np.zeros((10, 12, 3), np.uint8), photometric="rgb")
    with pytest.raises(io.ImageReadError, match="colour"):
        io.read_channel(path, "CYX", 0)


# File list


@pytest.fixture
def image_folder(tmp_path):
    names = [
        "b sample 2.tif",
        "a sample 1.tif",
        "c_éèü sample.tif",
        "d_other.tif",
        "e sample.tiff",
        "f sample.TIF",
        "a sample 1_seglabels.tif",
        ".hidden sample.tif",
        "._a sample 1.tif",
        "notes sample.txt",
    ]
    for name in names:
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "bigfish_results").mkdir()
    (tmp_path / "bigfish_results" / "g sample.tif").write_bytes(b"")
    (tmp_path / "folder sample.tif").mkdir()
    return tmp_path


def test_list_images(image_folder):
    names = [p.name for p in io.list_images(image_folder, "sample", ".tif")]
    assert names == ["a sample 1.tif", "b sample 2.tif", "c_éèü sample.tif", "f sample.TIF"]


def test_list_images_without_filter(image_folder):
    names = [p.name for p in io.list_images(image_folder, "", ".tif")]
    assert names == ["a sample 1.tif", "b sample 2.tif", "c_éèü sample.tif", "d_other.tif", "f sample.TIF"]


def test_list_images_tiff(image_folder):
    assert [p.name for p in io.list_images(image_folder, "", ".tiff")] == ["e sample.tiff"]


def test_list_images_accented_filter(image_folder):
    assert [p.name for p in io.list_images(image_folder, "éèü", ".tif")] == ["c_éèü sample.tif"]


def test_list_images_missing_folder(tmp_path):
    with pytest.raises(FileNotFoundError, match="Folder not found"):
        io.list_images(tmp_path / "missing", "", ".tif")


def test_list_images_wrong_extension(image_folder):
    with pytest.raises(ValueError, match="Extension must be"):
        io.list_images(image_folder, "", ".png")


# Output names


def test_output_name(tmp_path):
    assert io.output_name(tmp_path / "a sample 1.tif") == "a sample 1"
    assert io.output_name("c_éèü.tiff") == "c_éèü"


def test_check_output_names(tmp_path):
    io.check_output_names([tmp_path / "a.tif", tmp_path / "b.tif"])
    with pytest.raises(ValueError, match="A.tif, a.tif"):
        io.check_output_names([tmp_path / "A.tif", tmp_path / "a.tif", tmp_path / "b.tif"])


# Metadata check


def make_info(z, y, x):
    return io.ImageInfo(
        path=Path("image.tif"), shape=(3, 10, 12), axes="ZYX", dtype=np.dtype(np.uint16), layout="ZYX",
        n_timepoints=1, n_positions=1, voxel_size_z=z, voxel_size_y=y, voxel_size_x=x,
    )


def test_check_voxel_sizes_agree():
    assert io.check_voxel_sizes(make_info(200, 65.0000004, 64.99), 200, 65) is None


def test_check_voxel_sizes_missing_in_file():
    assert io.check_voxel_sizes(make_info(None, None, None), 200, 65) is None


def test_check_voxel_sizes_disagree():
    warning = io.check_voxel_sizes(make_info(300, 65, 70), 200, 65)
    assert "Z 300 nm in the file, 200 nm in the config" in warning
    assert "X 70 nm in the file, 65 nm in the config" in warning
    assert "Y " not in warning


def test_check_voxel_sizes_2d():
    assert io.check_voxel_sizes(make_info(None, 65, 65), None, 65) is None


# Test kit crop


def test_crop_info(crop_path):
    info = io.get_image_info(crop_path)
    assert info.layout == "ZCYX"
    assert info.shape == (11, 3, 384, 384)
    assert info.dtype == np.uint16
    assert (info.voxel_size_z, info.voxel_size_y, info.voxel_size_x) == (200, 65, 65)
    assert info.n_timepoints == 1 and info.n_positions == 1


def test_crop_channel(crop_path):
    data = io.read_channel(crop_path, "ZCYX", 2)
    np.testing.assert_array_equal(data, tifffile.imread(crop_path)[:, 2])


def test_crop_listing(test_kit_folder):
    found = io.list_images(test_kit_folder, "sypN_DAPI_Phal_jim-exon_crop", ".tif")
    assert [p.name for p in found] == ["sypN_DAPI_Phal_jim-exon_crop.tif"]


@pytest.mark.full_image
def test_full_image(full_image_path):
    info = io.get_image_info(full_image_path)
    assert info.layout == "ZCYX"
    assert info.shape == (35, 4, 2048, 2048)
    assert info.dtype == np.uint16
    assert (info.voxel_size_z, info.voxel_size_y, info.voxel_size_x) == (200, 65, 65)

    data = io.read_channel(full_image_path, "ZCYX", 2)
    assert data.shape == (35, 2048, 2048)
    np.testing.assert_array_equal(data, tifffile.imread(full_image_path)[:, 2])
