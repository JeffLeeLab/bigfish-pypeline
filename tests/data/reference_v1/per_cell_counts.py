"""Per-cell spot counts for the v1 reference runs on the test crop.

Run in the main conda env (big-fish 0.6.2):

    conda run -n bigfish-pypeline python tests/data/reference_v1/per_cell_counts.py

For each run with subpixel fitting off, the spots (and, for the general runs,
the clusters) are given to big-fish `multistack.extract_cell` together with
the nuclear label image, as in v1 `general/smFISH-quantification_optimise-parameters.ipynb`.
One CSV per run is written next to the run's .npz file: `per_cell_counts.csv`.

As a cross-check, each spot and cluster is also looked up directly in the
label image at its (y, x) position. The result of the comparison is printed;
the CSVs hold the `extract_cell` counts only.
"""

import pathlib

import numpy as np
import pandas as pd
import tifffile
import bigfish.multistack as multistack

HERE = pathlib.Path(__file__).resolve().parent
LABELS = HERE.parent / "sypN_DAPI_Phal_jim-exon_crop_seglabels.tif"
NPZ_NAME = "sypN_DAPI_Phal_jim-exon_crop_ch2_bfoutput.npz"

RUNS = {
    "general_manual18_subpixel-off": "general",
    "general_auto_subpixel-off": "general",
    "hcr_manual18_subpixel-off": "hcr",
    "hcr_auto_subpixel-off": "hcr",
}


def touches_border(mask):
    return bool(mask[0, :].any() or mask[-1, :].any()
                or mask[:, 0].any() or mask[:, -1].any())


def direct_lookup(label_image, coord):
    """Label value at each object's (y, x) position (columns 1 and 2)."""
    y = coord[:, 1].astype(np.int64)
    x = coord[:, 2].astype(np.int64)
    return label_image[y, x]


def main():
    label_image = tifffile.imread(LABELS)

    for run, kind in RUNS.items():
        data = np.load(HERE / run / NPZ_NAME)
        if kind == "general":
            spots = data["spots_post_clustering"]
            others = {"clusters": data["clusters"]}
        else:
            spots = data["spots"]
            others = None

        fov_results = multistack.extract_cell(
            cell_label=label_image,
            ndim=3,
            rna_coord=spots,
            others_coord=others,
            remove_cropped_cell=False,
        )

        rows = []
        for cell in fov_results:
            label = int(cell["cell_id"])
            rna = cell["rna_coord"]
            row = {
                "label": label,
                "touches_border": touches_border(label_image == label),
                "n_spots": len(rna),
            }
            if kind == "general":
                row["n_spots_in_clusters"] = int((rna[:, 3] >= 0).sum())
                row["n_spots_outside_clusters"] = int((rna[:, 3] < 0).sum())
                row["n_clusters"] = len(cell["clusters"])
            rows.append(row)
        table = pd.DataFrame(rows)
        table.to_csv(HERE / run / "per_cell_counts.csv", index=False)

        # cross-check against a direct look-up in the label image
        spot_labels = direct_lookup(label_image, spots)
        n_assigned = int(table["n_spots"].sum())
        print(f"{run}: {len(table)} cells, {len(spots)} spots, "
              f"{n_assigned} in a cell, {len(spots) - n_assigned} outside any cell")
        inner = table[~table["touches_border"]]
        checks = [("n_spots", spot_labels)]
        if kind == "general":
            checks.append(("n_clusters", direct_lookup(label_image, data["clusters"])))
            checks.append(("n_spots_in_clusters", spot_labels[spots[:, 3] >= 0]))
        for column, looked_up in checks:
            direct = np.array([(looked_up == lab).sum() for lab in inner["label"]])
            differ = inner[inner[column].to_numpy() != direct]
            print(f"  {column}: direct look-up agrees for "
                  f"{len(inner) - len(differ)} of {len(inner)} cells not touching the border")
            for _, d in differ.iterrows():
                print(f"    label {d['label']}: extract_cell {d[column]}, "
                      f"direct {(looked_up == d['label']).sum()}")


if __name__ == "__main__":
    main()
