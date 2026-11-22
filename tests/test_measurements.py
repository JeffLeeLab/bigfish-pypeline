"""Tests for measurements.py: SNR against the posthoc function on the crop, synthetic spots and log_intensity."""

import numpy as np
import pytest
import tifffile
import bigfish.detection as detection

from bigfish_pypeline import detection as bp_detection
from bigfish_pypeline import measurements
from synthetic import make_image

FISH_CHANNEL = 2
VOXEL_SIZE = (200, 65, 65)
OPTICS = dict(ex=570, em=610, NA=1.45, RI=1.45, microscope="confocal")
SPOT_RADIUS_NM = bp_detection.get_spot_radius_nm(VOXEL_SIZE, **OPTICS)
SPOT_RADIUS_PX = bp_detection.get_spot_radius_px(VOXEL_SIZE, **OPTICS)
SPOT_RADIUS_PX_2D = bp_detection.get_spot_radius_px(VOXEL_SIZE[1:], **OPTICS)


# Reference: compute_snr_spots_individual from
# posthoc_analysis/snr/formamide_ec/batch_script_20260120/smFISH_snr_analysis_multiprocess.py
def compute_snr_spots_individual(
    image,
    spots,
    voxel_size,
    spot_radius
):
    """
    Compute SNR for each individual spot.

    Parameters
    ----------
    image : np.ndarray
        Image with shape (z, y, x).
    spots : np.ndarray
        Coordinates of spots with shape (nb_spots, 3) for zyx coordinates.
    voxel_size : tuple
        Voxel size in nanometers (voxel_size_z, voxel_size_yx, voxel_size_yx).
    spot_radius : tuple
        Theoretical spot radius in nanometers (radius_z, radius_yx, radius_yx).

    Returns
    -------
    snr_values : np.ndarray
        Array of SNR values for each spot with shape (nb_spots,).
    """
    # Convert spot radius from nm to pixels
    spot_radius_px = detection.get_object_radius_pixel(
        voxel_size_nm=voxel_size,
        object_radius_nm=spot_radius,
        ndim=3
    )

    # Define the region sizes for signal and background
    signal_radius = tuple([int(np.ceil(r)) for r in spot_radius_px])
    background_inner_radius = tuple([int(np.ceil(r * 1.5)) for r in spot_radius_px])
    background_outer_radius = tuple([int(np.ceil(r * 2.5)) for r in spot_radius_px])

    snr_values = []

    for spot_coord in spots:
        z, y, x = int(spot_coord[0]), int(spot_coord[1]), int(spot_coord[2])

        # Define bounds for extraction (with boundary checks)
        z_min = max(0, z - background_outer_radius[0])
        z_max = min(image.shape[0], z + background_outer_radius[0] + 1)
        y_min = max(0, y - background_outer_radius[1])
        y_max = min(image.shape[1], y + background_outer_radius[1] + 1)
        x_min = max(0, x - background_outer_radius[2])
        x_max = min(image.shape[2], x + background_outer_radius[2] + 1)

        # Extract local region
        local_region = image[z_min:z_max, y_min:y_max, x_min:x_max]

        # Create coordinate grids relative to spot center
        zz, yy, xx = np.ogrid[
            z_min-z:z_max-z,
            y_min-y:y_max-y,
            x_min-x:x_max-x
        ]

        # Calculate distances (accounting for anisotropic voxels)
        distances = np.sqrt(
            (zz / spot_radius_px[0])**2 +
            (yy / spot_radius_px[1])**2 +
            (xx / spot_radius_px[2])**2
        )

        # Create masks for signal and background regions
        signal_mask = distances <= 1.0
        background_mask = (distances > 1.5) & (distances <= 2.5)

        # Calculate signal and background
        if np.sum(signal_mask) > 0 and np.sum(background_mask) > 0:
            signal = np.mean(local_region[signal_mask])
            background = np.mean(local_region[background_mask])
            background_std = np.std(local_region[background_mask])

            # Calculate SNR
            if background_std > 0:
                snr = (signal - background) / background_std
            else:
                snr = 0
        else:
            snr = 0

        snr_values.append(snr)

    return np.array(snr_values)


def _ring_is_empty_or_flat(image, spot, spot_radius_px):
    """True when the reference fell back to 0 because of an empty or flat ring."""
    ndim = image.ndim
    outer = [int(np.ceil(r * 2.5)) for r in spot_radius_px]
    window = tuple(
        slice(max(0, spot[a] - outer[a]), min(image.shape[a], spot[a] + outer[a] + 1))
        for a in range(ndim)
    )
    grids = np.ogrid[tuple(slice(w.start - spot[a], w.stop - spot[a]) for a, w in enumerate(window))]
    distances = np.sqrt(sum((grids[a] / spot_radius_px[a]) ** 2 for a in range(ndim)))
    ring = image[window][(distances > 1.5) & (distances <= 2.5)]
    return ring.size == 0 or np.std(ring) == 0


# --------------------------------------------------------------------------
# test kit crop against the posthoc function
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def crop_filtered(crop_path):
    image = tifffile.imread(crop_path)[:, FISH_CHANNEL]
    return bp_detection.filter_channel(image, SPOT_RADIUS_PX, bg_radius=5, bg_method="tophat")


@pytest.fixture(scope="module")
def crop_spots(crop_reference_folder):
    files = sorted((crop_reference_folder / "general_manual18_subpixel-off").glob("*.npz"))
    assert len(files) == 1
    spots = np.load(files[0])["spots_post_clustering"][:, :3]
    assert spots.shape == (692, 3)
    return spots


def test_crop_snr_as_posthoc(crop_filtered, crop_spots):
    rna = crop_filtered["rna"]
    expected = compute_snr_spots_individual(rna, crop_spots, VOXEL_SIZE, SPOT_RADIUS_NM)
    snr = measurements.compute_snr_spots_individual(rna, crop_spots, SPOT_RADIUS_PX)
    assert snr.shape == (692,)
    assert snr.dtype == np.float64

    fallback = np.array([_ring_is_empty_or_flat(rna, s, SPOT_RADIUS_PX) for s in crop_spots])
    assert np.array_equal(np.isnan(snr), fallback)
    assert np.all(expected[fallback] == 0)
    assert np.array_equal(snr[~fallback], expected[~fallback])


def test_crop_log_intensity(crop_filtered, crop_spots):
    rna_log = crop_filtered["rna_log"]
    log_intensity = measurements.compute_log_intensity(rna_log, crop_spots)
    z, y, x = crop_spots.T
    assert np.array_equal(log_intensity, rna_log[z, y, x])


def test_crop_extra_columns_ignored(crop_filtered, crop_reference_folder, crop_spots):
    files = sorted((crop_reference_folder / "general_manual18_subpixel-off").glob("*.npz"))
    spots_4col = np.load(files[0])["spots_post_clustering"]
    got = measurements.measure_spots(
        crop_filtered["rna"], crop_filtered["rna_log"], spots_4col, SPOT_RADIUS_PX
    )
    expected = measurements.measure_spots(
        crop_filtered["rna"], crop_filtered["rna_log"], crop_spots, SPOT_RADIUS_PX
    )
    np.testing.assert_array_equal(got["snr"], expected["snr"])
    np.testing.assert_array_equal(got["log_intensity"], expected["log_intensity"])


def test_crop_plane_2d_as_3d_without_z(crop_filtered, crop_spots):
    """2D on one plane equals the 3D reference on a one-plane stack (no Z neighbours)."""
    plane = crop_filtered["rna"][5]
    spots_2d = crop_spots[crop_spots[:, 0] == 5][:, 1:]
    assert len(spots_2d) > 10
    spots_3d = np.column_stack([np.zeros(len(spots_2d), dtype=np.int64), spots_2d])
    expected = compute_snr_spots_individual(plane[None], spots_3d, VOXEL_SIZE, SPOT_RADIUS_NM)
    snr = measurements.compute_snr_spots_individual(plane, spots_2d, SPOT_RADIUS_PX_2D)
    finite = ~np.isnan(snr)
    assert np.array_equal(snr[finite], expected[finite])
    assert np.all(expected[~finite] == 0)


# --------------------------------------------------------------------------
# hand-built arrays with known values
# --------------------------------------------------------------------------


def _hand_built(spot_radius_px, size=15, signal=10.0, ring_values=(1.0, 3.0), other=1000.0):
    """
    Image with one spot in the centre: signal inside the radius, the ring
    alternating between two values, and a very different value elsewhere.
    """
    ndim = len(spot_radius_px)
    centre = (size // 2,) * ndim
    image = np.full((size,) * ndim, other)
    grids = np.ogrid[tuple(slice(-c, size - c) for c in centre)]
    distances = np.sqrt(sum((grids[a] / spot_radius_px[a]) ** 2 for a in range(ndim)))
    image[distances <= 1.0] = signal
    ring = np.argwhere((distances > 1.5) & (distances <= 2.5))
    assert len(ring) % 2 == 0
    for i, position in enumerate(ring):
        image[tuple(position)] = ring_values[i % 2]
    return image, np.array([centre])


@pytest.mark.parametrize("spot_radius_px", [(1.0, 1.0), (1.0, 1.0, 1.0), (2.0, 1.0, 1.0), (1.3, 1.7)])
def test_hand_built_exact(spot_radius_px):
    image, spots = _hand_built(spot_radius_px)
    # signal 10, ring mean 2 and standard deviation 1
    snr = measurements.compute_snr_spots_individual(image, spots, spot_radius_px)
    assert snr.tolist() == [8.0]


def test_hand_built_2d_ring_size():
    # radius 1 in 2D: 5 signal pixels and a ring of 12 pixels
    image, spots = _hand_built((1.0, 1.0), size=7, signal=0.0, ring_values=(0.0, 0.0), other=1.0)
    assert np.count_nonzero(image == 0) == 17


def test_flat_ring_gives_nan():
    for spot_radius_px in [(1.0, 1.0), (1.0, 1.0, 1.0)]:
        image, spots = _hand_built(spot_radius_px, ring_values=(2.0, 2.0))
        snr = measurements.compute_snr_spots_individual(image, spots, spot_radius_px)
        assert np.isnan(snr).all()
        assert snr.shape == (1,)


def test_flat_image_gives_nan():
    image = np.full((5, 20, 20), 100, dtype=np.uint16)
    spots = np.array([[2, 10, 10], [0, 0, 0]])
    snr = measurements.compute_snr_spots_individual(image, spots, SPOT_RADIUS_PX)
    assert np.isnan(snr).all()


def test_empty_ring_gives_nan():
    # a radius this small leaves no pixel between 1.5 and 2.5 radii
    image = np.random.default_rng(0).normal(100, 10, (20, 20))
    snr = measurements.compute_snr_spots_individual(image, np.array([[10, 10]]), (0.3, 0.3))
    assert np.isnan(snr).all()


# --------------------------------------------------------------------------
# synthetic spots
# --------------------------------------------------------------------------


@pytest.mark.parametrize("shape, spot_radius_px", [
    ((10, 256, 256), SPOT_RADIUS_PX),
    ((256, 256), SPOT_RADIUS_PX_2D),
])
def test_synthetic_spot_height(shape, spot_radius_px):
    amplitude, noise = 400, 10
    ndim = len(shape)
    # narrow spots, so the ring holds only background and noise
    spot_sigma = (0.6, 0.5, 0.5)[-ndim:]
    noisy, spots, _ = make_image(
        shape, n_spots=150, spot_sigma=spot_sigma, amplitude=amplitude, noise=noise, min_spacing=10, margin=8
    )

    # expected: mean of the Gaussian spot within the radius minus its mean
    # in the ring, over the noise level
    grids = np.ogrid[tuple(slice(-5, 6) for _ in range(ndim))]
    distances = np.sqrt(sum((grids[a] / spot_radius_px[a]) ** 2 for a in range(ndim)))
    gaussian = amplitude * np.exp(-sum(grids[a] ** 2 / (2 * spot_sigma[a] ** 2) for a in range(ndim)))
    height = gaussian[distances <= 1.0].mean() - gaussian[(distances > 1.5) & (distances <= 2.5)].mean()
    expected = height / noise

    snr = measurements.compute_snr_spots_individual(noisy, spots, spot_radius_px)
    assert snr.shape == (150,)
    assert not np.isnan(snr).any()
    # the ring holds few pixels, so single values vary; the median is close
    assert np.median(snr) == pytest.approx(expected, rel=0.2)

    # a spot twice as high gives about twice the SNR
    noisy_2, _, _ = make_image(
        shape, n_spots=150, spot_sigma=spot_sigma, amplitude=2 * amplitude, noise=noise, min_spacing=10, margin=8
    )
    snr_2 = measurements.compute_snr_spots_individual(noisy_2, spots, spot_radius_px)
    assert np.median(snr_2 / snr) == pytest.approx(2, rel=0.05)


def test_synthetic_2d_as_3d_without_z():
    """2D result on a plane equals the 3D reference on that plane as a one-plane stack."""
    image, spots, _ = make_image((128, 128), n_spots=30, amplitude=300, noise=10)
    expected = compute_snr_spots_individual(
        image[None], np.column_stack([np.zeros(len(spots), dtype=np.int64), spots]),
        VOXEL_SIZE, SPOT_RADIUS_NM,
    )
    snr = measurements.compute_snr_spots_individual(image, spots, SPOT_RADIUS_PX_2D)
    assert np.array_equal(snr, expected)


def test_synthetic_3d_as_posthoc():
    image, spots, dense = make_image(
        (10, 128, 128), n_spots=30, amplitude=300, noise=10,
        dense_region={"centre": (5, 64, 64), "n_spots": 10, "spread": 2},
    )
    all_spots = np.concatenate([spots, dense])
    expected = compute_snr_spots_individual(image, all_spots, VOXEL_SIZE, SPOT_RADIUS_NM)
    snr = measurements.compute_snr_spots_individual(image, all_spots, SPOT_RADIUS_PX)
    assert np.array_equal(snr, expected)


@pytest.mark.parametrize("shape, spot_radius_px", [
    ((6, 40, 40), SPOT_RADIUS_PX),
    ((40, 40), SPOT_RADIUS_PX_2D),
])
def test_corner_and_edge_spots(shape, spot_radius_px):
    image = np.random.default_rng(1).normal(100, 10, shape)
    last = np.array(shape) - 1
    corners = [np.zeros(len(shape), dtype=int), last]
    edges = [np.array(shape) // 2, np.array(shape) // 2]
    edges[0][-1] = 0
    edges[1][-2] = last[-2]
    spots = np.array(corners + edges)
    snr = measurements.compute_snr_spots_individual(image, spots, spot_radius_px)
    assert snr.shape == (4,)
    assert np.isfinite(snr).all()

    if len(shape) == 3:
        expected = compute_snr_spots_individual(image, spots, VOXEL_SIZE, SPOT_RADIUS_NM)
    else:
        expected = compute_snr_spots_individual(
            image[None], np.column_stack([np.zeros(4, dtype=int), spots]), VOXEL_SIZE, SPOT_RADIUS_NM
        )
    assert np.array_equal(snr, expected)

    log_intensity = measurements.compute_log_intensity(image, spots)
    assert np.array_equal(log_intensity, image[tuple(spots.T)])


@pytest.mark.parametrize("ndim", [2, 3])
def test_zero_spots(ndim):
    image = np.zeros((4, 20, 20)[-ndim:])
    radius = SPOT_RADIUS_PX if ndim == 3 else SPOT_RADIUS_PX_2D
    for spots in [np.zeros((0, ndim), dtype=np.int64), np.zeros((0, ndim + 1)), []]:
        result = measurements.measure_spots(image, image, spots, radius)
        assert result["snr"].shape == (0,)
        assert result["log_intensity"].shape == (0,)


@pytest.mark.parametrize("ndim", [2, 3])
def test_extra_columns_ignored(ndim):
    shape = (6, 64, 64)[-ndim:]
    radius = SPOT_RADIUS_PX if ndim == 3 else SPOT_RADIUS_PX_2D
    image, spots, _ = make_image(shape, n_spots=10, amplitude=300, noise=10)
    extra = np.column_stack([spots, np.arange(10), -np.ones(10, dtype=np.int64)])
    for key, values in measurements.measure_spots(image, image, extra, radius).items():
        expected = measurements.measure_spots(image, image, spots, radius)[key]
        np.testing.assert_array_equal(values, expected)


def test_log_intensity_2d_and_dtype():
    rna_log = np.arange(30, dtype=np.uint16).reshape(5, 6)
    spots = np.array([[0, 0], [4, 5], [2, 3]])
    log_intensity = measurements.compute_log_intensity(rna_log, spots)
    assert log_intensity.tolist() == [0, 29, 15]
    assert log_intensity.dtype == np.uint16


def test_measure_spots_switches():
    image = np.zeros((20, 20))
    spots = np.array([[10, 10]])
    assert measurements.measure_spots(image, image, spots, (1, 1), snr=False, intensity=False) == {}
    assert list(measurements.measure_spots(image, image, spots, (1, 1), snr=False)) == ["log_intensity"]
    assert list(measurements.measure_spots(image, image, spots, (1, 1), intensity=False)) == ["snr"]


def test_wrong_sizes_rejected():
    with pytest.raises(ValueError, match="dimensions"):
        measurements.compute_snr_spots_individual(np.zeros((5, 20, 20)), [[1, 1, 1]], (1, 1))
    with pytest.raises(ValueError, match="columns"):
        measurements.compute_snr_spots_individual(np.zeros((5, 20, 20)), [[1, 1]], (1, 1, 1))
