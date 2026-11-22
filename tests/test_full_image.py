"""The full-size image through the whole pipeline, against the v1 reference run.

Needs the full-size image (`BIGFISH_TEST_DATA`); takes about a minute and 5 GB of memory.
"""

import numpy as np
import pandas as pd
import pytest

from bigfish_pypeline import batch, outputs
from bigfish_pypeline.config import load_config, parse_config
from conftest import FISH_CHANNEL, FULL_IMAGE_NAME


@pytest.mark.full_image
def test_full_image_general_manual_18(full_image_path, full_reference_folder, crop_config_path, tmp_path):
    """Detection is identical to v1. After decomposition v1 itself varies from run to run
    (it builds its reference spot from a random 2,000 spots), so counts are compared."""
    settings = load_config(crop_config_path).to_dict()
    settings["run"]["input"]["folder"] = str(full_image_path.parent)
    settings["run"]["input"]["extension"] = ".tiff"
    settings["segmentation"]["enabled"] = False
    config = parse_config(settings)

    summary = batch.process_image(config, FULL_IMAGE_NAME, full_image_path, tmp_path)
    row = summary["rows"][0]
    assert row["status"] == "done"
    assert row["channel"] == FISH_CHANNEL
    assert row["threshold"] == 18
    assert row["n_spots_detected"] == 24631

    reference = np.load(next((full_reference_folder / "general_manual18_subpixel-off").rglob("*_bfoutput.npz")))
    n_spots_v1 = len(reference["spots_post_clustering"])
    n_clusters_v1 = len(reference["clusters"])
    assert (n_spots_v1, n_clusters_v1) == (37086, 207)
    # v1's own runs gave 36,490 to 37,086 spots and 199 to 207 clusters
    assert abs(row["n_spots"] - n_spots_v1) / n_spots_v1 < 0.03
    assert abs(row["n_clusters"] - n_clusters_v1) / n_clusters_v1 < 0.10

    spots = pd.read_csv(outputs.per_image_path(tmp_path, FULL_IMAGE_NAME, "spots"))
    assert len(spots) == row["n_spots"]
    # most positions are the same as in the v1 run
    new_positions = set(map(tuple, spots[["z_px", "y_px", "x_px"]].to_numpy()))
    v1_positions = set(map(tuple, reference["spots_post_clustering"][:, :3].astype(int)))
    assert len(new_positions & v1_positions) / len(v1_positions) > 0.95
