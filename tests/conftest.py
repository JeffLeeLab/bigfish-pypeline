"""Shared paths for the tests: the test kit, its v1 reference results and the full-size image."""

import os
from pathlib import Path

import pytest

TEST_DATA = Path(__file__).parent / "data"
CROP_NAME = "sypN_DAPI_Phal_jim-exon_crop"
FULL_IMAGE_NAME = "20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001"
FISH_CHANNEL = 2


@pytest.fixture(scope="session")
def test_kit_folder():
    """Folder holding the crop, its label image and its config."""
    return TEST_DATA


@pytest.fixture(scope="session")
def crop_path():
    return TEST_DATA / f"{CROP_NAME}.tif"


@pytest.fixture(scope="session")
def crop_labels_path():
    return TEST_DATA / f"{CROP_NAME}_seglabels.tif"


@pytest.fixture(scope="session")
def crop_config_path():
    return TEST_DATA / f"{CROP_NAME}_config.yaml"


@pytest.fixture(scope="session")
def crop_reference_folder():
    """v1 reference results for the crop, one folder per run (see its README)."""
    return TEST_DATA / "reference_v1"


@pytest.fixture(scope="session")
def full_data_folder():
    """Local folder with the full-size image; tests using it are skipped when it is absent."""
    folder = os.environ.get("BIGFISH_TEST_DATA")
    if not folder:
        pytest.skip("BIGFISH_TEST_DATA is not set")
    folder = Path(folder).expanduser()
    if not (folder / f"{FULL_IMAGE_NAME}.tiff").is_file():
        pytest.skip(f"full-size image not found in {folder}")
    return folder


@pytest.fixture(scope="session")
def full_image_path(full_data_folder):
    return full_data_folder / f"{FULL_IMAGE_NAME}.tiff"


@pytest.fixture(scope="session")
def full_reference_folder(full_data_folder):
    """v1 reference results for the full-size image, one folder per run."""
    return full_data_folder / "reference_v1" / "full"
