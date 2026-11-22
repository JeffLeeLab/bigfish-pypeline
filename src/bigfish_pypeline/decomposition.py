"""Dense-region decomposition: reference spot, spot model and Gaussian mixtures.

Every function works on 3D images (z, y, x) and 2D images (y, x). Voxel
sizes and spot radii have three values (z, y, x) in 3D and two (y, x) in 2D.
"""

import hashlib
import unicodedata
import warnings

import numpy as np
import bigfish.stack as stack
import bigfish.detection as detection

NO_SPOTS_WARNING = "Decomposition skipped: no spots were detected in this channel."
NO_REFERENCE_SPOT_WARNING = (
    "Decomposition skipped: no reference spot could be built, because every "
    "detected spot is too close to the image edge."
)
NO_SPOT_MODEL_WARNING = (
    "Decomposition skipped: no Gaussian could be fitted to the reference spot."
)
FEW_SPOTS_WARNING = (
    "The reference spot was built from 30 spots or fewer, so the "
    "decomposition of dense regions may be less reliable."
)

# start of the big-fish warning given when a reference spot is built from 30 spots or fewer
_BIGFISH_FEW_SPOTS_TEXT = "Problem occurs during the computation of a reference spot."


def get_seed(run_seed, image_name, channel):
    """
    Random seed for one image and channel, from the run seed, the image name
    and the channel number.

    The number is worked out with SHA-256, so it is the same in every
    process and on every computer. Returns an integer from 0 to 2**32 - 1.
    """
    image_name = unicodedata.normalize("NFC", str(image_name))
    text = f"{int(run_seed)}\n{image_name}\n{int(channel)}"
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def decompose_dense_regions(rna, spots, voxel_size, spot_radius_nm, alpha=0.5,
                            beta=1, seed=None):
    """
    Split dense regions of one channel into single spots.

    rna: the image after background subtraction, (z, y, x) or (y, x).
    spots: detected spots, one row per spot (z, y, x or y, x).
    voxel_size, spot_radius_nm: in nm, one value per image axis.
    alpha: intensity score of the reference spot (0 to 1).
    beta: multiple of the reference spot peak above which pixels belong to a
        dense region.
    seed: random seed (from get_seed). big-fish builds a reference spot from
        2,000 spots picked at random when there are more; the seed is set
        before each of its three reference spots (two here, one inside
        get_dense_region), so all three use the same spots. The state of
        numpy's random generator is restored afterwards. None leaves the
        generator as it is.

    Returns a dict with:
    - "spots_post_decomposition": spots outside dense regions followed by
      the spots found inside them; the detected spots unchanged when
      decomposition is skipped,
    - "reference_spot": the reference spot built from rna, or None when no
      reference spot could be built,
    - "skipped": True when the detected spots are passed on unchanged (no
      spots, no reference spot, no spot model or no dense regions),
    - "warning": a message when decomposition was skipped for a reason other
      than finding no dense regions, or when the reference spot was built
      from 30 spots or fewer; otherwise None.
    """
    rna = np.asarray(rna)
    ndim = rna.ndim
    voxel_size = tuple(voxel_size)
    spot_radius_nm = tuple(spot_radius_nm)
    if len(voxel_size) != ndim or len(spot_radius_nm) != ndim:
        raise ValueError(
            f"The image has {ndim} dimensions but the voxel size has "
            f"{len(voxel_size)} values and the spot radius {len(spot_radius_nm)}."
        )

    result = {
        "spots_post_decomposition": spots,
        "reference_spot": None,
        "skipped": True,
        "warning": None,
    }
    if len(spots) == 0:
        result["warning"] = NO_SPOTS_WARNING
        return result

    # denoised copy of the image
    kernel_size = detection.get_object_radius_pixel(
        voxel_size_nm=voxel_size,
        object_radius_nm=spot_radius_nm,
        ndim=ndim,
    )
    large_kernel_size = tuple([kernel_size_ * 5 for kernel_size_ in kernel_size])
    rna_denoised = stack.remove_background_gaussian(rna, sigma=large_kernel_size)

    random_state = np.random.get_state()
    try:
        if seed is not None:
            np.random.seed(seed)
        sample_state = np.random.get_state()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            # reference spots, from the denoised copy and from rna
            reference_spot_denoised = detection.build_reference_spot(
                image=rna_denoised,
                spots=spots,
                voxel_size=voxel_size,
                spot_radius=spot_radius_nm,
                alpha=alpha,
            )
            np.random.set_state(sample_state)
            reference_spot = detection.build_reference_spot(
                image=rna,
                spots=spots,
                voxel_size=voxel_size,
                spot_radius=spot_radius_nm,
                alpha=alpha,
            )

            if reference_spot_denoised.sum() > 0:
                # Gaussian model of the reference spot
                try:
                    parameters = detection.modelize_spot(
                        reference_spot=reference_spot_denoised,
                        voxel_size=voxel_size,
                        spot_radius=spot_radius_nm,
                    )
                except RuntimeError:
                    parameters = None

                # dense regions (get_dense_region builds its own reference spot)
                if parameters is not None:
                    np.random.set_state(sample_state)
                    regions_to_decompose, spots_out_regions, region_size = (
                        detection.get_dense_region(
                            image=rna_denoised,
                            spots=spots,
                            voxel_size=voxel_size,
                            spot_radius=spot_radius_nm,
                            beta=beta,
                        )
                    )

        few_spots = _pass_on_warnings(caught)
    finally:
        np.random.set_state(random_state)

    # big-fish returns an empty frame when every spot is cut by the image edge
    if reference_spot_denoised.sum() == 0:
        result["warning"] = NO_REFERENCE_SPOT_WARNING
        return result
    result["reference_spot"] = reference_spot
    messages = []
    if few_spots:
        messages.append(FEW_SPOTS_WARNING)
    if parameters is None:
        messages.append(NO_SPOT_MODEL_WARNING)
    if messages:
        result["warning"] = " ".join(messages)
    if parameters is None or regions_to_decompose.size == 0:
        return result

    if ndim == 3:
        sigma_z, sigma_yx, amplitude, background = parameters
        sigma = (sigma_z, sigma_yx, sigma_yx)
    else:
        sigma_yx, amplitude, background = parameters
        sigma = (sigma_yx, sigma_yx)

    # fill each dense region with as many Gaussian spots as it holds
    max_grid = max(200, region_size + 1)
    precomputed_gaussian = detection.precompute_erf(
        ndim=ndim,
        voxel_size=voxel_size,
        sigma=sigma,
        max_grid=max_grid,
    )
    spots_in_regions, _ = detection.simulate_gaussian_mixture(
        image=rna_denoised,
        candidate_regions=regions_to_decompose,
        voxel_size=voxel_size,
        sigma=sigma,
        amplitude=amplitude,
        background=background,
        precomputed_gaussian=precomputed_gaussian,
    )

    spots_post_decomposition = np.concatenate(
        (spots_out_regions, spots_in_regions[:, :ndim]), axis=0
    )
    result["spots_post_decomposition"] = spots_post_decomposition
    result["skipped"] = False
    return result


def _pass_on_warnings(caught):
    """
    Issue the caught warnings again, except the big-fish warning about a
    reference spot built from few spots. Returns True when that warning was
    among them.
    """
    few_spots = False
    for warning in caught:
        if (issubclass(warning.category, UserWarning)
                and str(warning.message).startswith(_BIGFISH_FEW_SPOTS_TEXT)):
            few_spots = True
            continue
        warnings.warn_explicit(
            warning.message, warning.category, warning.filename, warning.lineno,
            source=warning.source,
        )
    return few_spots
