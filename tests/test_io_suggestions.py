"""Tests for the values suggested from an image's header, and for numbered image lists."""

from pathlib import Path

import numpy as np
import pytest
import tifffile

from bigfish_pypeline import io
from bigfish_pypeline.config import new_config, parse_config

UM = (0.2, 0.065, 0.065)  # Z, Y, X in µm


def write(path, shape, kind, layout=None, dtype=np.uint16, um=UM):
    array = np.zeros(shape, dtype)
    z, y, x = um
    if kind == "imagej":
        metadata = {"axes": layout, "unit": "um"}
        if "Z" in layout:
            metadata["spacing"] = z
        tifffile.imwrite(path, array, imagej=True, metadata=metadata, resolution=(1 / x, 1 / y))
    elif kind == "ome":
        metadata = {"axes": layout, "PhysicalSizeX": x, "PhysicalSizeY": y}
        if "Z" in layout:
            metadata["PhysicalSizeZ"] = z
        tifffile.imwrite(path, array, ome=True, metadata=metadata)
    else:
        planes = array.reshape(-1, *array.shape[-2:])
        tifffile.imwrite(path, planes if len(planes) > 1 else planes[0], metadata=None, photometric="minisblack")
    return path


def suggest(path):
    return io.suggest_image_settings(io.get_image_info(path))


def omero_info(size_z=3, size_c=2, size_t=1, pixel_type="uint16", dtype=np.uint16, sizes=(200.0, 65.0, 65.0),
               names=("DAPI", "exon"), image_id=7, name="a.tif"):
    z, y, x = sizes
    return io.OmeroImageInfo(
        image_id=image_id, name=name, size_z=size_z, size_c=size_c, size_t=size_t, size_y=8, size_x=10,
        pixel_type=pixel_type, dtype=None if dtype is None else np.dtype(dtype),
        voxel_size_z=z, voxel_size_y=y, voxel_size_x=x, channel_names=list(names),
    )


# --- TIFF files ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["imagej", "ome"])
def test_file_with_metadata(tmp_path, kind):
    path = write(tmp_path / "a.tif", (3, 2, 10, 12), kind, "ZCYX")
    suggestion = suggest(path)
    assert suggestion.layout == "ZCYX"
    assert suggestion.possible_layouts == ("ZCYX",)
    assert suggestion.voxel_size_nm == {"yx": 65.0, "z": 200.0}
    assert (suggestion.n_planes, suggestion.n_channels) == (3, 2)
    assert suggestion.counts_by_layout == {"ZCYX": (3, 2)}
    assert suggestion.size_yx == (10, 12)
    assert suggestion.pixel_type == "16-bit (uint16)"
    assert suggestion.name == "a.tif"
    assert suggestion.notes == [] and suggestion.problems == []


def test_ome_file_with_channels_first(tmp_path):
    suggestion = suggest(write(tmp_path / "a.tif", (2, 3, 10, 12), "ome", "CZYX"))
    assert suggestion.layout == "CZYX"
    assert (suggestion.n_planes, suggestion.n_channels) == (3, 2)


def test_two_dimensional_file(tmp_path):
    suggestion = suggest(write(tmp_path / "a.tif", (10, 12), "ome", "YX"))
    assert suggestion.layout == "YX"
    assert suggestion.voxel_size_nm == {"yx": 65.0, "z": None}
    assert (suggestion.n_planes, suggestion.n_channels) == (1, 1)


def test_two_dimensional_file_with_channels_ignores_a_z_size(tmp_path):
    path = write(tmp_path / "a.tif", (2, 10, 12), "imagej", "CYX")
    suggestion = suggest(path)
    assert suggestion.layout == "CYX"
    assert suggestion.voxel_size_nm["z"] is None
    assert (suggestion.n_planes, suggestion.n_channels) == (1, 2)


def test_file_without_metadata_offers_the_layouts_for_its_axes(tmp_path):
    suggestion = suggest(write(tmp_path / "a.tif", (5, 10, 12), "plain"))
    assert suggestion.layout is None
    assert suggestion.possible_layouts == ("ZYX", "CYX")
    assert suggestion.voxel_size_nm == {"yx": None, "z": None}
    assert (suggestion.n_planes, suggestion.n_channels) == (None, None)
    assert suggestion.counts_by_layout == {"ZYX": (5, 1), "CYX": (1, 5)}
    assert suggestion.problems == []


def header(shape, layout=None):
    """File information written by hand, for files whose axes the metadata does not give."""
    return io.ImageInfo(
        path=Path("a.tif"), shape=shape, axes="Q" * (len(shape) - 2) + "YX", dtype=np.dtype(np.uint16),
        layout=layout, n_timepoints=1, n_positions=1, voxel_size_z=None, voxel_size_y=None,
        voxel_size_x=None, bits_per_sample=16,
    )


def test_four_axes_without_metadata():
    suggestion = io.suggest_image_settings(header((3, 2, 10, 12)))
    assert suggestion.layout is None
    assert suggestion.possible_layouts == ("ZCYX", "CZYX")
    assert suggestion.counts_by_layout == {"ZCYX": (3, 2), "CZYX": (2, 3)}


def test_plain_two_dimensional_file(tmp_path):
    suggestion = suggest(write(tmp_path / "a.tif", (10, 12), "plain"))
    assert suggestion.layout is None and suggestion.possible_layouts == ("YX",)
    assert suggestion.counts_by_layout == {"YX": (1, 1)}


def test_different_x_and_y_pixel_sizes(tmp_path):
    path = write(tmp_path / "a.tif", (3, 2, 10, 12), "ome", "ZCYX", um=(0.2, 0.065, 0.1))
    suggestion = suggest(path)
    assert suggestion.voxel_size_nm == {"yx": None, "z": 200.0}
    assert suggestion.notes == [
        "The pixel size differs between x (100 nm) and y (65 nm). One pixel size is used for both: "
        "enter the value to use."
    ]
    assert suggestion.problems == []


def test_file_with_several_time_points(tmp_path):
    suggestion = suggest(write(tmp_path / "a.tif", (4, 3, 2, 10, 12), "ome", "TZCYX"))
    assert suggestion.layout is None and suggestion.possible_layouts == ()
    assert suggestion.problems == ["a.tif: the image has 4 time points; only one is accepted"]


def test_file_with_a_pixel_type_that_cannot_be_used(tmp_path):
    suggestion = suggest(write(tmp_path / "a.tif", (3, 2, 10, 12), "ome", "ZCYX", dtype=np.float32))
    assert len(suggestion.problems) == 1
    assert suggestion.problems[0].startswith("a.tif: the pixel type is 32-bit with decimal values (float32)")
    assert suggestion.layout is None and suggestion.possible_layouts == ()
    assert suggestion.pixel_type == "32-bit with decimal values (float32)"


def test_eight_bit_file(tmp_path):
    suggestion = suggest(write(tmp_path / "a.tif", (3, 2, 10, 12), "ome", "ZCYX", dtype=np.uint8))
    assert suggestion.problems == [] and suggestion.pixel_type == "8-bit (uint8)"


@pytest.mark.parametrize("shape", [(2, 2, 3, 2, 10, 12), (2,)])
def test_file_with_a_number_of_axes_that_no_layout_has(shape):
    suggestion = io.suggest_image_settings(header(shape))
    assert suggestion.possible_layouts == ()
    assert len(suggestion.problems) == 1
    assert suggestion.problems[0].startswith(f"a.tif: the image has {len(shape)} axes")
    assert "the layouts have 2 to 4: ZCYX, CZYX, ZYX, CYX, YX" in suggestion.problems[0]


def test_suggestion_fills_a_config(tmp_path):
    suggestion = suggest(write(tmp_path / "a.tif", (3, 2, 10, 12), "imagej", "ZCYX"))
    config = new_config(
        suggestion.layout, suggestion.voxel_size_nm, [{"index": 1, "assay_type": "smFISH"}], cell_results=True
    )
    assert config.image.voxel_size_nm.yx == 65 and config.image.voxel_size_nm.z == 200
    assert parse_config(config.to_dict()) == config


def test_two_dimensional_suggestion_fills_a_config(tmp_path):
    suggestion = suggest(write(tmp_path / "a.tif", (10, 12), "imagej", "YX"))
    config = new_config(suggestion.layout, suggestion.voxel_size_nm, [{"index": 0, "assay_type": "amplified"}])
    assert config.image.axes == "YX" and config.image.voxel_size_nm.z is None


@pytest.mark.parametrize("name", ["sypN_DAPI_Phal_jim-exon_crop.tif", "culture_DAPI_cellmask_exon_crop.tif"])
def test_test_kit_images(name):
    from conftest import TEST_DATA

    suggestion = suggest(TEST_DATA / name)
    assert suggestion.layout == "ZCYX" and suggestion.possible_layouts == ("ZCYX",)
    assert suggestion.voxel_size_nm == {"yx": 65.0, "z": 200.0}
    assert suggestion.n_channels == 3
    assert suggestion.n_planes == (11 if name.startswith("syp") else 31)
    assert suggestion.size_yx == (384, 384)
    assert suggestion.problems == [] and suggestion.notes == []


def test_image_counts(tmp_path):
    info = io.get_image_info(write(tmp_path / "a.tif", (5, 10, 12), "plain"))
    assert io.image_counts(info, "ZYX") == (5, 1)
    assert io.image_counts(info, "CYX") == (1, 5)
    with pytest.raises(ValueError, match="The layout ZCYX needs 4 axes, but the image has 3."):
        io.image_counts(info, "ZCYX")
    with pytest.raises(ValueError, match="Layout must be one of"):
        io.image_counts(info, "XYZ")


# --- OMERO images -------------------------------------------------------------------------


def test_omero_image():
    suggestion = io.suggest_image_settings(omero_info())
    assert suggestion.layout == "ZCYX"
    assert suggestion.possible_layouts == ("ZCYX", "CZYX")
    assert suggestion.voxel_size_nm == {"yx": 65.0, "z": 200.0}
    assert (suggestion.n_planes, suggestion.n_channels) == (3, 2)
    assert suggestion.counts_by_layout == {"ZCYX": (3, 2), "CZYX": (3, 2)}
    assert suggestion.size_yx == (8, 10)
    assert suggestion.channel_names == ["DAPI", "exon"]
    assert suggestion.name == "a.tif (image ID 7)"
    assert suggestion.problems == []
    assert suggestion.notes == [
        "OMERO does not store the order of planes and channels, so ZCYX and CZYX work equally well."
    ]


@pytest.mark.parametrize(
    "size_z, size_c, layout",
    [(1, 1, "YX"), (3, 1, "ZYX"), (1, 2, "CYX")],
)
def test_omero_images_with_fewer_axes(size_z, size_c, layout):
    suggestion = io.suggest_image_settings(omero_info(size_z, size_c, names=()))
    assert suggestion.layout == layout and suggestion.possible_layouts == (layout,)
    assert suggestion.notes == []


def test_omero_image_without_pixel_sizes():
    suggestion = io.suggest_image_settings(omero_info(sizes=(None, None, None)))
    assert suggestion.voxel_size_nm == {"yx": None, "z": None}


def test_omero_two_dimensional_image_has_no_z():
    suggestion = io.suggest_image_settings(omero_info(1, 2, sizes=(200.0, 65.0, 65.0)))
    assert suggestion.voxel_size_nm == {"yx": 65.0, "z": None}


def test_omero_different_x_and_y_pixel_sizes():
    suggestion = io.suggest_image_settings(omero_info(sizes=(200.0, 65.0, 100.0)))
    assert suggestion.voxel_size_nm == {"yx": None, "z": 200.0}
    assert "The pixel size differs between x (100 nm) and y (65 nm)" in suggestion.notes[0]


def test_omero_several_time_points():
    suggestion = io.suggest_image_settings(omero_info(size_t=3))
    assert suggestion.problems == ["OMERO image 7: the image has 3 time points; only one is accepted"]
    assert suggestion.layout is None and suggestion.possible_layouts == ()


def test_omero_pixel_type_that_cannot_be_used():
    suggestion = io.suggest_image_settings(omero_info(pixel_type="float", dtype=np.float32))
    assert len(suggestion.problems) == 1
    assert suggestion.problems[0].startswith("OMERO image 7: the pixel type is 32-bit with decimal values")


def test_omero_unknown_pixel_type():
    suggestion = io.suggest_image_settings(omero_info(pixel_type="bit", dtype=None))
    assert suggestion.pixel_type == "'bit'"
    assert len(suggestion.problems) == 1


# --- text for printing --------------------------------------------------------------------


def test_text_for_a_file_with_metadata(tmp_path):
    text = io.describe_suggestion(suggest(write(tmp_path / "a.tif", (3, 2, 10, 12), "ome", "ZCYX")))
    assert text.splitlines() == [
        "Image: a.tif",
        "Size: 10 × 12 pixels",
        "Layout: ZCYX (3 planes, 2 channels)",
        "Pixel size in x and y: 65 nm",
        "Distance between planes (z): 200 nm",
        "Pixel type: 16-bit (uint16)",
    ]


def test_text_for_a_file_without_metadata(tmp_path):
    text = io.describe_suggestion(suggest(write(tmp_path / "a.tif", (5, 10, 12), "plain")))
    assert text.splitlines() == [
        "Image: a.tif",
        "Size: 10 × 12 pixels",
        "Layout: not given by the image. It could be one of:",
        "  ZYX: 5 planes, 1 channel",
        "  CYX: 1 plane, 5 channels",
        "Pixel size in x and y: not given by the image, so enter it yourself",
        "Distance between planes (z): not given by the image, so enter it yourself",
        "Pixel type: 16-bit (uint16)",
    ]


def test_text_for_a_two_dimensional_file_leaves_out_z(tmp_path):
    text = io.describe_suggestion(suggest(write(tmp_path / "a.tif", (10, 12), "ome", "YX")))
    assert "Distance between planes" not in text and "Layout: YX (1 plane, 1 channel)" in text


def test_text_for_an_omero_image_with_notes():
    text = io.describe_suggestion(io.suggest_image_settings(omero_info(sizes=(200.0, 65.0, 100.0))))
    lines = text.splitlines()
    assert lines[0] == "Image: a.tif (image ID 7)"
    assert "Pixel size in x and y: not given by the image, so enter it yourself" in lines
    assert "Channels: 0 DAPI, 1 exon" in lines
    assert any(line.startswith("Note: The pixel size differs between x") for line in lines)


def test_text_for_an_image_that_cannot_be_used():
    text = io.describe_suggestion(io.suggest_image_settings(omero_info(size_t=2)))
    assert "Layout: the image cannot be used" in text
    assert text.splitlines()[-1] == "Cannot be used: OMERO image 7: the image has 2 time points; only one is accepted"


def test_text_for_a_12_bit_file(tmp_path):
    info = io.get_image_info(write(tmp_path / "a.tif", (3, 2, 10, 12), "ome", "ZCYX"))
    info.bits_per_sample = 12
    assert io.suggest_image_settings(info).pixel_type == "12-bit (read as 16-bit)"


# --- numbered lists -----------------------------------------------------------------------


def test_numbered_local_images(tmp_path):
    for name in ("b.tif", "a.tif", "c.tif"):
        (tmp_path / name).write_bytes(b"")
    images = io.list_images(tmp_path)
    assert io.numbered_images(images) == "0  a.tif\n1  b.tif\n2  c.tif"
    assert images[1].name == "b.tif"


def test_numbered_omero_images():
    images = [(12, "first.tif"), (7, "second.tif")]
    assert io.numbered_images(images) == "0  first.tif  (image ID 12)\n1  second.tif  (image ID 7)"


def test_numbers_are_aligned_when_there_are_ten_or_more():
    lines = io.numbered_images([f"img{n}.tif" for n in range(11)]).splitlines()
    assert lines[0] == " 0  img0.tif" and lines[10] == "10  img10.tif"


def test_numbered_list_with_no_images(tmp_path):
    assert io.numbered_images(io.list_images(tmp_path)) == "No images found."
    assert io.numbered_images([]) == "No images found."


def test_numbered_list_accepts_any_sequence(tmp_path):
    (tmp_path / "a.tif").write_bytes(b"")
    assert io.numbered_images(iter(io.list_images(tmp_path))) == "0  a.tif"
