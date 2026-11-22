# v1 reference results on the test crop

Results of the v1 pipeline (tag `v1.0`) on the test crop `../sypN_DAPI_Phal_jim-exon_crop.tif`, channel 2. The automated tests compare the new pipeline with these files. Do not change them.

## How they were made

- The v1 batch scripts were run unchanged from a copy of the code at tag `v1.0` (`v1_commit.txt`), in the main conda env `bigfish-pypeline` (`conda_env_export.yml`, big-fish 0.6.2).
- Settings: voxel size 200 nm (Z) and 65 nm (YX); excitation 570 nm, emission 610 nm, NA 1.45, refractive index 1.45, confocal; top-hat background removal with a 5-pixel radius; one worker. General script only: alpha 0.5, beta 1, cluster radius 600 nm, at least 12 spots per cluster.
- Each run folder holds the settings file the script read and `command.txt` (the command, the folder it was run from and the exit code).
- The four general runs were each run twice; the saved results were identical both times.
- The picture files (elbow plots, detection images) and the run logs are kept outside the repository, in `~/bigfish-testdata/reference_v1/crop/`.

## Runs

| Folder | Script | Threshold | Subpixel fitting |
|---|---|---|---|
| `general_manual18_subpixel-off` | general | 18 | off |
| `general_manual18_subpixel-on` | general | 18 | on |
| `general_auto_subpixel-off` | general | automatic | off |
| `general_auto_subpixel-on` | general | automatic | on |
| `hcr_manual18_subpixel-off` | HCRv3 | 18 | off |
| `hcr_manual18_subpixel-on` | HCRv3 | 18 | on |
| `hcr_auto_subpixel-off` | HCRv3 | automatic | off |
| `hcr_auto_subpixel-on` | HCRv3 | automatic | on |
| `hcr_auto_bailout` | HCRv3 | automatic, bailout on (limit 100 spots) | off |

`summary.csv` gives, for each run, the threshold used and the numbers of spots and clusters. The v1 scripts do not save the automatic threshold, so the `hcr_auto_bailout` run exists to record it: with bailout on and more than 100 spots found, the script writes the threshold and the spot count to `..._bailout.txt` and stops there. The general script uses the same calculation on the same filtered image, so the same value (13.0) applies to the general automatic runs.

## Files in each run folder

**General runs**

- `..._bfoutput.npz`, with two arrays:
  - `spots_post_clustering`: one row per spot after dense regions are split into single spots; columns z, y, x (in pixels) and the cluster number (-1 for a spot outside any cluster).
  - `clusters`: one row per cluster; columns z, y, x of the cluster centre (in pixels), number of spots, cluster number.
- `..._bfoutput_dataframe.csv`: the `spots_post_clustering` array as a table.
- `..._referencespot.tif`: the average spot (5 × 5 × 5 pixels) built from the image after background removal.

**HCRv3 runs**

- `..._bfoutput.npz`, with one array, `spots`: one row per detected spot; columns z, y, x (in pixels). HCRv3 runs do not split dense regions or look for clusters.

With subpixel fitting off the positions are whole pixels; with it on they are decimals.

**`hcr_auto_bailout`**: only `..._bailout.txt`, with the automatic threshold and the number of spots it gives.

## Spots per nucleus

`per_cell_counts.py` makes `per_cell_counts.csv` in the four runs with subpixel fitting off. It hands the spots (and, for the general runs, the clusters) and the nuclear label image `../sypN_DAPI_Phal_jim-exon_crop_seglabels.tif` to big-fish `multistack.extract_cell`, as the v1 optimise notebook does, keeping nuclei that touch the image edge.

Columns:

- `label`: the nucleus's number in the label image.
- `touches_border`: `True` if the nucleus reaches the edge of the image (18 of 44). The tests compare only the nuclei that do not.
- `n_spots`: spots inside the nucleus.
- General runs only: `n_spots_in_clusters`, `n_spots_outside_clusters`, and `n_clusters` (clusters whose centre lies inside the nucleus).

A spot or cluster belongs to a nucleus when its (y, x) position falls on that nucleus in the label image; its z position is not used. Spots outside every nucleus are not listed. Runs with subpixel fitting on are left out because big-fish 0.6.2 rounds decimal positions and stops with an error when a spot rounds to just beyond the image edge.

To remake the tables, from the repository folder:

```
conda run -n bigfish-pypeline python tests/data/reference_v1/per_cell_counts.py
```

The script also looks each spot up directly in the label image and prints whether the two counts agree.
