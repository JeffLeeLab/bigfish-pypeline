"""Core image-processing helpers for the BigFISH Streamlit app."""

from __future__ import annotations

import numpy as np
import bigfish.detection as detection
import bigfish.stack as stack

from bigfish_pypeline.image_utils import calculate_psf, subtract_background


def get_spot_radius_px(voxel_size_z, voxel_size_yx, psf_z, psf_yx):
    """Convert PSF sizes from nanometres to pixel units."""
    return detection.get_object_radius_pixel(
        voxel_size_nm=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        object_radius_nm=(psf_z, psf_yx, psf_yx),
        ndim=3,
    )


def background_subtract_stack(rna_zyx, bg_radius=5):
    """Apply slice-wise background subtraction across a z-stack."""
    return np.stack([subtract_background(z_slice, bg_radius) for z_slice in rna_zyx])


def log_filter_and_mip(rna_zyx, spot_radius_px):
    """Apply a LoG filter and compute the filtered maximum projection."""
    rna_log = stack.log_filter(rna_zyx, sigma=spot_radius_px)
    rna_log_mip = stack.maximum_projection(rna_log)
    return rna_log, rna_log_mip


def detect_spots_auto(rna_log, spot_radius_px):
    """Detect spots using the BigFISH automated threshold."""
    mask = detection.local_maximum_detection(rna_log, min_distance=spot_radius_px)
    threshold = detection.automated_threshold_setting(rna_log, mask)
    spots, _ = detection.spots_thresholding(rna_log, mask, threshold)
    return spots, float(threshold), mask


def detect_spots_manual(rna_log, spot_radius_px, threshold):
    """Detect spots using a user-provided threshold."""
    mask = detection.local_maximum_detection(rna_log, min_distance=spot_radius_px)
    spots, _ = detection.spots_thresholding(rna_log, mask, threshold)
    return spots, mask


def build_reference_spot(rna_zyx, spots, voxel_size_z, voxel_size_yx, psf_z, psf_yx, alpha=0.5):
    """Build the denoised and display reference spots used for decomposition."""
    kernel_size = detection.get_object_radius_pixel(
        voxel_size_nm=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        object_radius_nm=(psf_z, psf_yx, psf_yx),
        ndim=3,
    )
    large_kernel_size = tuple(kernel_size_value * 5 for kernel_size_value in kernel_size)
    rna_denoised = stack.remove_background_gaussian(rna_zyx, sigma=large_kernel_size)

    reference_spot = detection.build_reference_spot(
        image=rna_denoised,
        spots=spots,
        voxel_size=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        spot_radius=(psf_z, psf_yx, psf_yx),
        alpha=alpha,
    )
    reference_spot_display = detection.build_reference_spot(
        image=rna_zyx,
        spots=spots,
        voxel_size=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        spot_radius=(psf_z, psf_yx, psf_yx),
        alpha=alpha,
    )
    return reference_spot, reference_spot_display, rna_denoised


def decompose_dense_regions(rna_denoised, spots, reference_spot, voxel_size_z, voxel_size_yx, psf_z, psf_yx, beta=1):
    """Run dense-region decomposition and return the updated spot coordinates."""
    if len(spots) == 0:
        return np.empty((0, 3), dtype=float)

    voxel_size = (voxel_size_z, voxel_size_yx, voxel_size_yx)
    spot_radius = (psf_z, psf_yx, psf_yx)

    sigma_z, sigma_yx, amplitude, background = detection.modelize_spot(
        reference_spot=reference_spot,
        voxel_size=voxel_size,
        spot_radius=spot_radius,
    )

    regions_to_decompose, spots_out_regions, region_size = detection.get_dense_region(
        image=rna_denoised,
        spots=spots,
        voxel_size=voxel_size,
        spot_radius=spot_radius,
        beta=beta,
    )

    if len(regions_to_decompose) == 0:
        return spots_out_regions

    max_grid = max(200, int(region_size) + 1)
    precomputed_gaussian = detection.precompute_erf(
        ndim=3,
        voxel_size=voxel_size,
        sigma=(sigma_z, sigma_yx, sigma_yx),
        max_grid=max_grid,
    )

    spots_in_regions, _ = detection.simulate_gaussian_mixture(
        image=rna_denoised,
        candidate_regions=regions_to_decompose,
        voxel_size=voxel_size,
        sigma=(sigma_z, sigma_yx, sigma_yx),
        amplitude=amplitude,
        background=background,
        precomputed_gaussian=precomputed_gaussian,
    )

    if len(spots_in_regions) == 0:
        return spots_out_regions
    if len(spots_out_regions) == 0:
        return spots_in_regions[:, :3]
    return np.concatenate((spots_out_regions, spots_in_regions[:, :3]), axis=0)


def fit_subpixel(rna_zyx, spots, voxel_size_z, voxel_size_yx, psf_z, psf_yx):
    """Optionally refine spot coordinates to subpixel positions."""
    if len(spots) == 0:
        return np.empty((0, 3), dtype=float)
    return detection.fit_subpixel(
        image=rna_zyx,
        spots=spots,
        voxel_size=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        spot_radius=(psf_z, psf_yx, psf_yx),
    )


def detect_clusters(spots, voxel_size_z, voxel_size_yx, radius=600, nb_min_spots=12):
    """Cluster spots using the BigFISH DBSCAN-based implementation."""
    if len(spots) == 0:
        return np.empty((0, 4), dtype=float), np.empty((0, 5), dtype=float)
    return detection.detect_clusters(
        spots=spots,
        voxel_size=(voxel_size_z, voxel_size_yx, voxel_size_yx),
        radius=radius,
        nb_min_spots=nb_min_spots,
    )


def count_spots_in_clusters(clustered_spots):
    """Count how many detected spots were assigned to a cluster."""
    if len(clustered_spots) == 0:
        return 0
    return int(np.sum(clustered_spots[:, -1] >= 0))