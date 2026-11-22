# MSP development log

Results, installed versions, deviations from `msp-spec.md` and benchmark numbers, phase by phase. Tasks are numbered as in `msp-plan.md`.

## Phase 0: Foundations

Development computer: MacBook Pro, Apple M1 Pro, 10 CPU cores, 16 GB memory, macOS (Darwin 25.5.0), conda 26.1.0 (Miniforge).

### 0.1 Spec, tag and branch (22 Nov 2026)

- `main` tagged `v1.0` at commit `264ffde`; branch `msp` created from it.

### 0.2 Local test data and v1 copy of the code (22 Nov 2026)

- `~/bigfish-testdata/` holds:
  - `20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001.tiff` (1.18 GB), copied from `~/Desktop/`. SHA-256 `1c45c3099e465bfb42d13bd83efd9e110fbb7116111f1c157d13a65c6d78f953`, identical to the original.
  - `jim_stability_smFISH_analysis_config.yaml`, copied from `~/Documents/Laboratory/LCLIP/analysis_data/jim_stability/batch_script/smFISH_analysis_config.yaml`.
- Image as read by `tifffile`: axes `ZCYX`, shape 35 × 4 × 2048 × 2048, `uint16`. ImageJ metadata gives a Z spacing of 0.2 µm and a resolution of 15.3846 pixels per µm (65 nm pixels), matching the spec.
- The image metadata gives the refractive index of the immersion oil as 1.518. The reference run and the test kit config use RI 1.45, as decided in brief R6.
- v1 code: `git worktree add ../bigfish-pypeline-v1 v1.0` (commit `264ffde`). The v1 batch scripts are always run from this folder.
- Check: the general and HCRv3 batch scripts both start and finish without error in the main env when run from the v1 copy with a config that matches no images.
- Main env at the time of the reference runs: Python 3.9.23, big-fish 0.6.2, numpy 1.21.6, scipy 1.7.3, scikit-image 0.19.3, tifffile 2024.6.18.

### 0.3 Package skeleton (22 Nov 2026)

- `pyproject.toml`: setuptools build (77 or newer) with the `src` layout, project name `bigfish-pypeline`, Python 3.12 or newer.
- The version, `2.0.0.dev0`, is written once, as `__version__` in `src/bigfish_pypeline/__init__.py`; `pyproject.toml` reads it from there.
- `pyproject.toml` lists no dependencies. The conda env file installs them all, so `pip install -e .` cannot replace a conda package with a pip one.
- The `bigfish-pypeline` command (spec section 4.2) is not declared yet; it is added in Phase 1 together with `cli.py`.
- `pytest` collects from `tests/` only, so the archived tests under `docs/archive/` are left out.
- `tests/test_package.py` imports the package and checks its version.
- Check, in a throwaway Python 3.13 virtual environment: `pip install -e .` installs version `2.0.0.dev0` and `pytest` passes (1 test). The v1 scripts can still import `bigfish_pypeline.image_utils` in the main env.

### 0.4 `bigfish-msp` env (22 Nov 2026)

- `msp-environment.yml` builds the env with one command from the repository root: `conda env create -f docs/modularisation-streamlit-project/msp-environment.yml`.
- Every version in the spec's table (section 4.3) has a conda-forge build for Apple silicon and Python 3.12, so nothing differs from the targets. The env file pins the versions installed.

| Package | Installed | Source |
|---|---|---|
| python | 3.12.16 | conda-forge |
| numpy | 2.5.5 | conda-forge |
| scipy | 1.18.1 | conda-forge |
| scikit-image | 0.26.0 | conda-forge |
| scikit-learn | 1.9.1 | conda-forge |
| matplotlib | 3.11.2 | conda-forge |
| pandas | 3.1.1 | conda-forge |
| tifffile | 2026.11.16 | conda-forge |
| pyyaml | 6.0.3 | conda-forge |
| tqdm | 4.70.1 | conda-forge |
| pytorch | 2.14.1 (build `cpu_generic_py312_hfc0fe18_3`) | conda-forge |
| zeroc-ice | 3.6.5 | conda-forge |
| omero-py | 5.22.1 | conda-forge |
| mrc | 0.4.0 (changed in 0.5; first built with 0.3.1 from conda-forge) | pip |
| pydantic | 2.14.4 | conda-forge |
| plotly | 7.1.0 | conda-forge |
| tk | 8.6.13 | conda-forge |
| jupyterlab | 4.6.6 | conda-forge |
| ipykernel | 7.4.0 | conda-forge |
| pytest | 9.2.0 | conda-forge |
| pip | 26.2.2 | conda-forge |
| setuptools | 84.2.1 (not pinned) | conda-forge |
| cellpose | 4.2.1.1 | pip |
| big-fish | 0.6.2.post1, from the fork's tag `v0.6.2.post1` (first built with the local fork in editable mode) | pip |
| bigfish-pypeline | 2.0.0.dev0, editable from the repository | pip |

- Installed by pip as Cellpose's own requirements, not pinned in the env file: torchvision 0.29.2, opencv-python-headless 5.1.0.95, segment-anything 1.0, imagecodecs 2026.11.11, fastremap 1.21.0, fill-voids 2.1.2, natsort 8.4.0, roifile 2026.11.6.
- pip installed no second copy of a conda package: PyTorch and numpy are present once each, from conda-forge, and `pip check` reports no broken requirements.
- Device: PyTorch uses the Apple GPU. `torch.backends.mps.is_available()` is true and a test calculation on the `mps` device gives the right answer. The conda-forge build is named `cpu_generic` but includes the Apple GPU support.
- `bigfish`, `bigfish.stack`, `bigfish.detection`, `cellpose` and `omero` all import.
- `BIGFISH_TEST_DATA=/Users/jefflee/bigfish-testdata` is stored as a variable of the env.

Additions to the spec's package table:

- `mrc`, which big-fish requires.
- Streamlit and `streamlit-image-coordinates` are left out until Phase 5.

Notes:

- The env file installs the pipeline with `-e ../..`, because conda runs pip from the folder that holds the env file, two levels below the repository root.
- Tests are run with `conda run -n bigfish-msp python -m pytest`. On this laptop `conda run -n bigfish-msp pytest` picks up a separate pytest in `~/.local/bin`, which cannot see the env's packages.
- Check: `python -m pytest` passes in `bigfish-msp` (1 test). The main env is unchanged (numpy 1.21.6, big-fish 0.6.2).

### 0.5 big-fish fork (22 Nov 2026)

Fork: `/Users/jefflee/Documents/Incubator/big-fish`, branch `msp-patches` from `master` (0.6.2, commit `e951ea8`). Three commits, pushed to `JeffLeeLab/big-fish` with the tag `v0.6.2.post1` (commit `4e7cb28`) after the user's approval.

big-fish's own tests in `bigfish-msp` (`conda run -n bigfish-msp python -m pytest bigfish`, run from the fork):

| | Passed | Failed | Errors |
|---|---|---|---|
| Unpatched 0.6.2 | 664 | 33 | 4 |
| `msp-patches` with `mrc` 0.4.0 | 697 | 0 | 0 |

No test is skipped and no test file was changed. The four segmentation test files in big-fish are empty.

Causes of the failures in unpatched 0.6.2:

- 4 errors: `skimage.morphology.selem` no longer exists, so `bigfish.segmentation` could not be imported.
- 29 failures: `save_image` could not write 2D png, jpg or jpeg images of most data types. The current `imageio` hands the array to Pillow unchanged, and Pillow refuses these types. In the main env the same call already fails for jpg (every type except 8-bit) and for png with decimal numbers.
- 4 failures: the `.dv` test writes its input file with `mrc.imsave`, which in `mrc` 0.3.1 uses a type code that numpy 2 removed. Reading `.dv` files was not affected.

Changes to big-fish:

| # | File | Change | Reason |
|---|---|---|---|
| 1 | `segmentation/nuc_segmentation.py` | `disk` is imported from `skimage.morphology.footprints` (from `selem` on scikit-image below 0.19), as `features.py` and `filter.py` already did | `selem` module removed |
| 2 | `segmentation/nuc_segmentation.py` | `reconstruction(..., selem=s)` → `footprint=s` | `selem=` keyword removed |
| 3 | `classification/features.py` | `binary_opening(..., selem=s)` → `footprint=s` | `selem=` keyword removed |
| 4 | `detection/utils.py` | `.astype(np.int)` → `.astype(int)`, twice, in `compute_snr_spots` | `np.int` removed from numpy |
| 5 | `stack/projection.py` | `one_hot.shape = …` → `one_hot = one_hot.reshape(…)` in `_one_hot_3d` | setting `.shape` is deprecated in numpy 2.5 |
| 6 | `plot/plot_images.py` | `RegularPolygon((x, y), 5, radius, …)` → `radius=radius` | matplotlib accepts `radius` by name only; without this, `plot_detection` cannot draw clusters as polygons |
| 7 | `stack/io.py` | `save_image` converts 2D png, jpg and jpeg images to 8-bit before saving (16-bit png is saved as it is), using `imageio.core.image_as_uint` | restores what `imageio` did when big-fish 0.6.2 was released; answers the 29 failures. TIFF saving, the only kind the pipeline uses, is unchanged |
| 8 | `__init__.py` | version `0.6.2.post1` | |

Changes 1–6 are in commit `5ff991e`, change 7 in `a75f00f`, change 8 in `4e7cb28`.

Change 7 alters behaviour, not only a removed call: in the main env, png images with whole numbers of more than 8 bits keep their values, and with the patch they are rescaled to 8-bit. It sits in its own commit. The user reviewed it and chose to keep it.

Env change that followed: `mrc` 0.4.0 from pip replaces 0.3.1 from conda-forge (conda-forge has no 0.4.0). It fixes the 4 `.dv` failures.

pandas 3.1.1 stays: no failure is linked to pandas.

Smoke check of the functions the pipeline uses, which big-fish's tests do not cover, on a 35 × 512 × 512 crop of channel 2 with top-hat at 5 px: `log_filter`, `local_maximum_detection`, `automated_threshold_setting`, `spots_thresholding`, `remove_background_gaussian`, `build_reference_spot`, `modelize_spot`, `get_dense_region`, `precompute_erf`, `simulate_gaussian_mixture`, `fit_subpixel`, `detect_clusters`, `maximum_projection`, `save_image` (TIFF), `plot_elbow`, `plot_detection` and `extract_cell` all run without error in `bigfish-msp`. The check led to change 6. It does not compare numbers with v1; that is Phase 1.

Calls that still work but are due to be removed, left unchanged:

- `square`, `rectangle` (`stack/filter.py`): removed in scikit-image 0.27. Not used by the pipeline. The env keeps scikit-image below 0.27.
- `binary_dilation`, `binary_erosion`, `binary_opening` (`stack/filter.py`, `classification/features.py`): removed in scikit-image 0.28. `plot_cell` and `plot_segmentation_boundary` use `binary_dilation`.
- `region.mean_intensity` (`detection/dense_decomposition.py`), used by `simulate_gaussian_mixture`, which the pipeline calls; `convex_area`, `equivalent_diameter` and `remove_small_objects(min_size=)` in `segmentation/`: removed in scikit-image 2.0.
- `sklearn.utils.fixes.parse_version`: an internal scikit-learn helper that big-fish uses for its version checks.
- `deep_learning/` needs an old TensorFlow, which is not installed; the pipeline does not use it.

After the push, `msp-environment.yml` installs big-fish from `git+https://github.com/JeffLeeLab/big-fish.git@v0.6.2.post1`, and `bigfish-msp` was removed and built again from the file. In the rebuilt env:

- big-fish 0.6.2.post1 is installed from the tag, with `mrc` 0.4.0; all other versions are as in 0.4, and `pip check` reports no broken requirements.
- big-fish's tests, run on the installed copy (`python -m pytest --pyargs bigfish`): 697 passed.
- The smoke check runs through.
- `python -m pytest` in the repository: 1 passed.
- PyTorch still uses the Apple GPU, and `BIGFISH_TEST_DATA` is set.

The fixes have not been offered to the original big-fish project (optional in the spec).

Found along the way, for task 0.9 and Phase 1: `multistack.extract_cell` stops with an `IndexError` when a subpixel coordinate rounds up to the image size (for example 511.5 on a 512 px image). This is in big-fish 0.6.2 itself and does not depend on package versions. The per-cell reference counts in 0.9 therefore use whole-pixel coordinates.

### 0.6 v1 reference run on the full-size image (22 Nov 2026)

Stored in `~/bigfish-testdata/reference_v1/full/`: one folder per run with its config, `command.txt`, `run.log`, `time.txt`, `bf_output/` and `bf_output_qc/`; plus `summary.csv`, `conda_env_export.yml`, `v1_commit.txt` and `image_sha256.txt`.

All runs use the unmodified v1 scripts (commit `264ffde`) in the main env, on channel 2, with one worker. Settings: voxel sizes 200 nm (Z) and 65 nm (YX), ex 570, em 610, NA 1.45, RI 1.45, confocal, top-hat background at 5 px, alpha 0.5, beta 1, cluster radius 600 nm, minimum spots 12. The general configs are the earlier config with only the input, output, worker, threshold-mode and subpixel lines changed. No v1 script needed a code change.

| Run folder | Script | Threshold | Subpixel | Spots | Clusters | Time (s) | Peak memory (GB) |
|---|---|---|---|---|---|---|---|
| `general_manual18_subpixel-off` | general | manual 18 | off | 37,086 | 207 | 98 | 3.7 |
| `general_manual18_subpixel-on` | general | manual 18 | on | 36,699 | 200 | 329 | 4.9 |
| `general_auto_subpixel-off` | general | auto (15) | off | 41,274 | 234 | 137 | 4.1 |
| `general_auto_subpixel-on` | general | auto (15) | on | 41,861 | 240 | 437 | 5.1 |
| `hcr_manual18_subpixel-off` | HCRv3 | manual 18 | off | 24,631 | – | 74 | 4.6 |
| `hcr_manual18_subpixel-on` | HCRv3 | manual 18 | on | 24,631 | – | 239 | 4.7 |
| `hcr_auto_subpixel-off` | HCRv3 | auto (15) | off | 27,514 | – | 106 | 5.2 |
| `hcr_auto_subpixel-on` | HCRv3 | auto (15) | on | 27,514 | – | 339 | 5.5 |
| `hcr_auto_bailout` | HCRv3 | auto (15), bailout at 100 spots | off | 27,514 (from the bailout file) | – | 96 | 5.5 |

Times and peak memory are for the whole script (image loading included), measured with `/usr/bin/time -l` while a conda env was being built on the same laptop, so the times are a rough guide only. Task 0.10 measures the steps properly.

Additions to the plan:

- `hcr_auto_bailout`: neither v1 script writes the automatic threshold anywhere except the HCRv3 bailout text file. This extra run, with bailout switched on, records it with unmodified v1 code: **15.0**, with 27,514 spots, matching the two HCRv3 auto runs. The general script takes the same steps up to the threshold, so the value applies to its auto runs too.
- `extra_general_manual18_subpixel-off_repeat`: a second run of `general_manual18_subpixel-off` with the same settings (see below). Its config points to a temporary output folder; the outputs were copied here afterwards.

What the saved arrays hold:

- HCRv3 `spots`: the detected spots (z, y, x), before any decomposition. Whole numbers with subpixel fitting off, decimal numbers with it on.
- General `spots_post_clustering` (z, y, x, cluster index; -1 outside clusters) and `clusters` (z, y, x, number of spots, index): after decomposition and clustering.

Checks on the outputs:

- HCRv3 runs with subpixel fitting on and off hold the same number of spots; fitting moves a spot by 0.3 px on average and never by more than 2 px in any direction.
- Every spot detected at threshold 18 is also detected at the automatic threshold of 15.
- In each general run, the number of spots marked as belonging to a cluster equals the sum of the cluster sizes.

**The v1 general script does not give the same result twice on this image.** The repeat run gave 36,490 spots and 199 clusters against 37,086 and 207 in the stored run, a difference of 1.6 % in spots. Cause: with more than 2,000 detected spots, big-fish builds the reference spot from 2,000 spots picked at random, with no fixed seed (`bigfish/detection/utils.py`, `build_reference_spot`), and the reference spot decides how dense regions are split. Consequences:

- The differences between the general runs with subpixel fitting on and off (37,086 against 36,699; 41,274 against 41,861) are of the same size as this run-to-run variation and cannot be read as an effect of subpixel fitting.
- For the full-size image, Phase 1 can compare detected spots exactly (HCRv3 outputs) but decomposed spots and clusters only as counts, within about 2 %, as the spec expects.
- The crop for the test kit must hold fewer than 2,000 detected spots so that its v1 results are repeatable. This is added to the conditions for the crop in 0.7.

### 0.7 Crop for the test kit (22 Nov 2026)

Chosen by the user from three candidates: **crop A**, top-left corner y = 1408, x = 1632, 384 × 384 px, planes 17–27 counted from 0 (11 planes), channels 0–2. Saved as `tests/data/sypN_DAPI_Phal_jim-exon_crop.tif` (9.7 MB, ImageJ TIFF, `ZCYX`, 65 nm pixels and 200 nm Z-steps in the metadata). The pixel values are identical to the same region of the full-size image.

Conditions used in the search, on top of the plan's:

- Fewer than 2,000 detected spots (see 0.6), so the v1 results on the crop are repeatable.
- "Isolated" spot: at least 10 px from the Y and X sides, not in the first or last two planes, no other spot within 10 px in YX, and left unchanged by decomposition.
- Spot and cluster numbers were taken from the v1 general script run on each candidate crop itself, not cut out of the full-image results.

| | A (chosen) | B | C |
|---|---|---|---|
| Top-left corner (y, x) | 1408, 1632 | 544, 1504 | 32, 1184 |
| Planes | 17–27 | 22–32 | 22–32 |
| Whole nuclei, counted by eye | about 16 | about 12 | about 12 |
| Detected spots at threshold 18 | 473 | 651 | 463 |
| Isolated spots | 51 | 61 | 55 |
| Spots after decomposition, manual 18 | 692 | 978 | 699 |
| Clusters, manual 18 | 6 | 6 | 4 |
| Auto threshold on the crop | 13 | 12 | 12 |
| Detected spots at the auto threshold | 610 | 1,015 | 845 |
| Spots after decomposition, auto | 869 | 1,493 | 1,247 |
| Clusters, auto | 6 | 10 | 6 |

For all three, a second v1 run with the same settings gave identical arrays, with the manual and with the automatic threshold.

Notes:

- All candidates are 384 px with 11 planes. At 256 px and 320 px the best positions had only 33 and 46 isolated spots.
- Eleven planes cover 2.2 µm, less than the depth of a nucleus. Nuclei in the crop are whole in Y and X but cut in Z. More planes at 384 px would exceed the 10 MB limit.
- In a crop's own run the first and last planes hold extra spots (for A, 85 and 75 against a median of 34 per plane), from signal whose peak lies just outside the Z range.
- The automatic threshold is 12–13 on the crops against 15 on the full-size image, because cropping changes the background.
- The candidates, their figures, the search scripts and the v1 runs on each are in `~/bigfish-testdata/crop_candidates/`.

Config: `tests/data/sypN_DAPI_Phal_jim-exon_crop_config.yaml`, written in the version 1 layout of spec section 6.2 with the settings of 0.6 (top-hat at 5 px, manual threshold 18, alpha 0.5, beta 1, cluster radius 600 nm, minimum spots 12, `confocal`, RI 1.45, subpixel fitting off) and per-cell results from label files in the same folder. It is checked against the config schema once that exists (Phase 1); the tests change the threshold mode and subpixel fitting from this base.

Point for Phase 1: with the label image stored next to the crop, the file filter of the config also matches `…_seglabels.tif`. File discovery needs a rule for label files that sit in the input folder.
