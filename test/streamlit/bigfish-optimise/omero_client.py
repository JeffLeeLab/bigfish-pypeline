"""Thin OMERO wrapper for the Streamlit parameter-optimisation app."""

from __future__ import annotations

from typing import Optional

from bigfish_pypeline.omero_tools import connect_to_omero, get_omero_image


PIXEL_TYPE_BYTES = {
    "int8": 1,
    "uint8": 1,
    "int16": 2,
    "uint16": 2,
    "int32": 4,
    "uint32": 4,
    "float": 4,
    "float32": 4,
    "double": 8,
    "float64": 8,
}


def normalize_image_id(image_id):
    """Accept either raw numeric IDs or Image:<id> strings."""
    normalized = str(image_id).replace("Image:", "").strip()
    if not normalized:
        raise ValueError("Enter an OMERO image ID.")
    return normalized


def _length_to_nm(length_obj) -> Optional[float]:
    if length_obj is None:
        return None

    value = float(length_obj.getValue())
    unit = str(length_obj.getUnit()).upper()
    conversions = {
        "NANOMETER": 1.0,
        "NANOMETRE": 1.0,
        "MICROMETER": 1000.0,
        "MICROMETRE": 1000.0,
        "MILLIMETER": 1_000_000.0,
        "MILLIMETRE": 1_000_000.0,
    }
    for token, factor in conversions.items():
        if token in unit:
            return round(value * factor, 3)
    return round(value, 3)


def _get_pixel_type(image_obj):
    getters = (
        lambda: image_obj.getPixelsType().getValue(),
        lambda: image_obj.getPrimaryPixels().getPixelsType().getValue(),
    )
    for getter in getters:
        try:
            pixel_type = getter()
        except Exception:
            continue
        if pixel_type:
            return str(pixel_type)
    return None


def _get_channel_name(channel_obj, default_name):
    getters = (
        lambda: channel_obj.getName(),
        lambda: channel_obj.getLabel(),
        lambda: channel_obj.getLogicalChannel().getName(),
    )
    for getter in getters:
        try:
            value = getter()
        except Exception:
            continue
        if value:
            return str(value)
    return default_name


def omero_connect(username, password, host="10.34.168.89", port=4064):
    """Establish an OMERO connection using the shared repo helper."""
    return connect_to_omero(
        username=username,
        host=host,
        port=port,
        password=password,
        secure=True,
    )


def omero_disconnect(conn):
    """Close an OMERO connection without surfacing cleanup errors."""
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def omero_load_image_metadata(conn, image_id):
    """Fetch image metadata without pulling the full array into memory."""
    normalized_id = normalize_image_id(image_id)
    image_obj = conn.getObject("Image", normalized_id)
    if image_obj is None:
        raise ValueError(f"Image ID '{image_id}' was not found on OMERO.")

    size_z = int(image_obj.getSizeZ())
    size_c = int(image_obj.getSizeC())
    size_y = int(image_obj.getSizeY())
    size_x = int(image_obj.getSizeX())
    pixel_type = _get_pixel_type(image_obj)
    bytes_per_pixel = PIXEL_TYPE_BYTES.get(str(pixel_type).lower()) if pixel_type else None
    estimated_bytes = None
    if bytes_per_pixel is not None:
        estimated_bytes = size_z * size_c * size_y * size_x * bytes_per_pixel

    pixels = image_obj.getPrimaryPixels()
    channel_names = [
        _get_channel_name(channel_obj, f"Channel {index}")
        for index, channel_obj in enumerate(image_obj.getChannels())
    ]

    return {
        "image_id": normalized_id,
        "image_name": image_obj.getName(),
        "size_z": size_z,
        "size_c": size_c,
        "size_y": size_y,
        "size_x": size_x,
        "pixel_type": pixel_type,
        "estimated_bytes": estimated_bytes,
        "channel_names": channel_names,
        "voxel_size_yx": _length_to_nm(pixels.getPhysicalSizeX()),
        "voxel_size_z": _length_to_nm(pixels.getPhysicalSizeZ()),
    }


def omero_load_channel_stack(conn, image_id, channel_index, order="ZCYX"):
    """Fetch one channel as a ZYX numpy array to limit memory usage."""
    normalized_id = normalize_image_id(image_id)
    image_obj = conn.getObject("Image", normalized_id)
    if image_obj is None:
        raise ValueError(f"Image ID '{image_id}' was not found on OMERO.")

    size_c = int(image_obj.getSizeC())
    if channel_index < 0 or channel_index >= size_c:
        raise ValueError(f"Channel {channel_index} is outside the valid range 0-{size_c - 1}.")

    image_array, image_name = get_omero_image(
        conn,
        normalized_id,
        channels=channel_index,
        order=order,
    )
    if image_array.ndim != 4 or image_array.shape[1] != 1:
        raise ValueError("Unexpected OMERO image shape returned for single-channel fetch.")
    return image_array[:, 0, :, :], image_name