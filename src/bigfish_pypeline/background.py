"""Background subtraction for 2D images and 3D stacks."""

import numpy as np
from skimage.morphology import white_tophat, black_tophat, disk

from bigfish_pypeline import rolling_ball

METHODS = ("rolling_ball", "tophat")


def subtract_background(image, radius, light_bg=False, method="rolling_ball"):
    """
    Remove uneven background from a 2D image (y, x) or a 3D stack (z, y, x).

    A 3D stack is processed one Z-plane at a time; a 2D image directly.

    method:
    - "rolling_ball": ImageJ's Process > Subtract Background (rolling ball,
      smoothing on). radius is the ball radius in pixels. A uint8 or uint16
      image gives the same dtype, rounded and clipped as ImageJ does; any
      other dtype gives float64, with values below the background kept
      negative.
    - "tophat": morphological white top-hat with a disk of the given radius
      (black top-hat when light_bg is True). The result has the same dtype
      as the image.

    light_bg: True for a bright background with dark objects. The two
    methods then give opposite results: rolling ball keeps the objects dark
    on a white background (as ImageJ does), top-hat makes them bright on a
    dark background.
    """
    if method not in METHODS:
        raise ValueError(
            f"Unknown background subtraction method '{method}'. "
            f"Use one of: {', '.join(METHODS)}."
        )
    image = np.asarray(image)
    if image.ndim == 2:
        return _subtract_plane(image, radius, light_bg, method)
    if image.ndim == 3:
        planes = [_subtract_plane(z, radius, light_bg, method) for z in image]
        return np.stack(planes)
    raise ValueError(
        f"Background subtraction needs a 2D (y, x) or 3D (z, y, x) image; "
        f"this image has {image.ndim} dimensions."
    )


def _subtract_plane(plane, radius, light_bg, method):
    """Subtract the background from one 2D plane."""
    if method == "rolling_ball":
        return rolling_ball.subtract_background(
            plane, radius, light_background=light_bg
        )
    str_el = disk(radius)
    if light_bg:
        return black_tophat(plane, str_el)
    else:
        return white_tophat(plane, str_el)
