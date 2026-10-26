from __future__ import annotations

import numpy as np

from bigfish_processing import (
    background_subtract_stack,
    calculate_psf,
    count_spots_in_clusters,
    detect_clusters,
    detect_spots_manual,
    get_spot_radius_px,
    log_filter_and_mip,
)


def test_calculate_psf_confocal_returns_positive_values():
    psf_z, psf_yx = calculate_psf(200, 65, 570, 610, 1.45, 1.45, "confocal")
    assert psf_z > 0
    assert psf_yx > 0
    assert psf_z > psf_yx


def test_calculate_psf_invalid_microscope_raises_value_error():
    try:
        calculate_psf(200, 65, 570, 610, 1.45, 1.45, "invalid")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected calculate_psf to raise ValueError for an invalid microscope type.")


def test_background_subtract_stack_preserves_shape():
    image_stack = np.random.randint(0, 255, size=(4, 32, 32), dtype=np.uint16)
    result = background_subtract_stack(image_stack, bg_radius=3)
    assert result.shape == image_stack.shape


def test_log_filter_and_mip_shapes_match_input():
    image_stack = np.random.randint(0, 255, size=(3, 16, 16), dtype=np.uint16)
    spot_radius_px = get_spot_radius_px(200, 65, 250, 150)
    filtered_stack, filtered_mip = log_filter_and_mip(image_stack, spot_radius_px)
    assert filtered_stack.shape == image_stack.shape
    assert filtered_mip.shape == image_stack.shape[1:]


def test_detect_spots_manual_returns_mask_shape():
    image_stack = np.zeros((3, 16, 16), dtype=np.uint16)
    image_stack[:, 8, 8] = 500
    spot_radius_px = get_spot_radius_px(200, 65, 250, 150)
    filtered_stack, _ = log_filter_and_mip(image_stack, spot_radius_px)
    spots, mask = detect_spots_manual(filtered_stack, spot_radius_px, threshold=0)
    assert mask.shape == image_stack.shape
    assert spots.ndim == 2


def test_detect_clusters_empty_input_returns_empty_arrays():
    clustered_spots, clusters = detect_clusters(np.empty((0, 3)), 200, 65, radius=600, nb_min_spots=12)
    assert clustered_spots.shape == (0, 4)
    assert clusters.shape == (0, 5)
    assert count_spots_in_clusters(clustered_spots) == 0