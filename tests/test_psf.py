"""Tests for psf.py: the same values as image_utils.calculate_psf."""

import numpy as np
import pytest

from bigfish_pypeline import image_utils
from bigfish_pypeline.psf import calculate_psf

SETTINGS = dict(voxel_size_z=200, voxel_size_yx=65, Ex=570, Em=610, NA=1.45, RI=1.45)


@pytest.mark.parametrize("microscope", ["confocal", "widefield", "nipkow"])
def test_matches_image_utils(microscope):
    got = calculate_psf(microscope=microscope, **SETTINGS)
    expected = image_utils.calculate_psf(microscope=microscope, **SETTINGS)
    assert got == expected


def test_widefield_values():
    psf_z, psf_yx = calculate_psf(microscope="widefield", **SETTINGS)
    assert psf_yx == pytest.approx(0.225 * 610 / 1.45)
    assert psf_z == pytest.approx(0.78 * 1.45 * 610 / 1.45 ** 2)


def test_nipkow_is_confocal():
    assert calculate_psf(microscope="nipkow", **SETTINGS) == calculate_psf(
        microscope="confocal", **SETTINGS
    )
    psf_z, psf_yx = calculate_psf(microscope="confocal", **SETTINGS)
    assert psf_yx == pytest.approx(0.225 / 1.45 * 570 * 610 / np.sqrt(570 ** 2 + 610 ** 2))


def test_positional_arguments():
    args = (200, 65, 570, 610, 1.45, 1.45, "confocal")
    assert calculate_psf(*args) == image_utils.calculate_psf(*args)


@pytest.mark.parametrize("microscope", ["lightsheet", "Confocal", ""])
def test_unknown_microscope_raises_as_image_utils(microscope):
    with pytest.raises(ValueError) as expected:
        image_utils.calculate_psf(microscope=microscope, **SETTINGS)
    with pytest.raises(ValueError) as got:
        calculate_psf(microscope=microscope, **SETTINGS)
    assert str(got.value) == str(expected.value)
