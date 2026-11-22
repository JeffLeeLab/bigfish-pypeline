"""Theoretical size of the point spread function (PSF)."""

import numpy as np


def calculate_psf(voxel_size_z, voxel_size_yx, Ex, Em, NA, RI, microscope):
    """
    Calculate the theoretical PSF size with the formula of the Matlab
    function sigma_PSF_BoZhang_v1.

    Ex and Em are the excitation and emission wavelengths, NA the numerical
    aperture and RI the refractive index of the immersion medium. microscope
    is "widefield", "confocal" or "nipkow" (spinning disk, treated as
    confocal). voxel_size_z and voxel_size_yx are not used by the formula.

    Returns (psf_z, psf_yx) in the unit of the wavelengths.
    """
    if microscope == "widefield":
        psf_yx = 0.225 * Em / NA
        psf_z = 0.78 * RI * Em / (NA ** 2)
    elif microscope in ("confocal", "nipkow"):
        psf_yx = 0.225 / NA * Ex * Em / np.sqrt(Ex ** 2 + Em ** 2)
        psf_z = 0.78 * RI / NA ** 2 * Ex * Em / np.sqrt(Ex ** 2 + Em ** 2)
    else:
        raise ValueError(
            "Unrecognised microscope argument for function calculate_psf()."
        )
    return psf_z, psf_yx
