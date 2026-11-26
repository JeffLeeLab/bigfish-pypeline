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

### 0.8 Nuclear label image for the crop (22 Nov 2026)

`tests/data/sypN_DAPI_Phal_jim-exon_crop_seglabels.tif`: 2D, 384 × 384, `uint16`, 0 as background, 44 labels numbered 1–44, 18 of them touching the border; 65 nm pixel size in the metadata. Checked: 2D, same Y × X as the crop, whole numbers of 0 or more, 0 as background, every label in one piece.

How it was made, in the main env (Cellpose 3.1.1.2, CPU):

- DAPI channel, maximum projection over the 11 planes; brightest spots capped at the 97th percentile; Gaussian smoothing of 2 px; divided by a 60 px blur to even out the brightness.
- Cellpose `nuclei` model, `diameter=60`, `flow_threshold=0.8`, `cellprob_threshold=-2.0`.
- For each label only the largest piece kept, holes filled, labels under 200 px dropped (none were), labels renumbered.
- A threshold-and-watershed draft was also made and set aside: it cut nuclei into pieces and left gaps in the dense centre.

Cellpose's default thresholds missed about half the nuclei, and its automatic diameter (17.5 px) outlined the bright DNA spots instead of nuclei.

**Deviation from the plan:** the user reviewed the draft overlay and accepted it without hand correction. Reason given: Cellpose is never fully accurate on DAPI in brain tissue, and the project implements Cellpose, it does not test its accuracy. The label image is used to test the assignment of spots to labels, which works the same for any label image (brief R7). Known weak points of the draft: labels 18, 22, 34 and 39 may each hold two nuclei; labels 10, 29, 37, 41, 42 and 43 are small round objects that may not be nuclei; a few dim nuclei have no label.

Working rule from this: segmentation quality on the test image is not brought to the user for judgement.

The draft, the DAPI projection, the figures and the scripts are in `~/bigfish-testdata/label_draft/`.

### 0.10 Benchmarks on the full-size image (22 Nov 2026)

Scripts, raw logs, `benchmarks.csv` and `conditions.txt` are in `~/bigfish-testdata/benchmarks/phase0/`.

Conditions: `bigfish-msp` (Python 3.12.16, numpy 2.5.5, scipy 1.18.1, scikit-image 0.26.0, big-fish 0.6.2.post1), channel 2 of the full-size image (35 × 2048 × 2048), settings of 0.6. `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` set to 1, as in a batch worker. One process at a time. Rolling ball from `misc/python-rolling-ball/imagej_rolling_ball.py` in JeffLeeLab/Image-analysis, commit `24bbbd4bf4f1d1c431faec62761dd7bd24a761f1`, called as `subtract_background(plane, radius=5)` on each Z-plane. The laptop was short of free memory during the runs (6–7 GB of swap in use), and other programs were open (load average 3–5).

Memory is given as the process's physical footprint, the figure Activity Monitor shows as "Memory". The more common measure (resident memory, as reported by `/usr/bin/time`) leaves out memory that macOS has compressed and read 0.6–1.9 GB lower in these runs.

**Background subtraction, whole channel (35 planes), 3 repeats each**

| Method | Time, median (range) | Per plane | Peak memory |
|---|---|---|---|
| Top-hat, disk of radius 5 | 31.9 s (31.6–32.2) | 0.91 s | 0.6 GB |
| Rolling ball, radius 5, one plane at a time | 42.0 s (42.0–42.4) | 1.20 s | 0.6 GB |
| Rolling ball, radius 5, whole stack in one call | 45.5 s (1 run) | 1.30 s | 4.7 GB |

- Rolling ball takes about 10 s longer per channel than top-hat (1.3 times), which is about 15 % of a worker's time for one channel with subpixel fitting off and about 3 % with it on. It stays the default method.
- Rolling ball has to be called one plane at a time. Given the whole stack, the file makes a copy of all planes as decimal numbers and needs about 4.4 GB more.

**v1 steps on the top-hat result** (3 repeats; 2 for subpixel fitting). "Extra memory" is the rise during the step.

| Step | Time, median | Extra memory |
|---|---|---|
| Read the whole file (4 channels) | 0.16 s | 1.1 GB |
| Read channel 2 only | 0.04 s | 0.3 GB |
| LoG filter | 15.1 s | **4.4 GB** |
| Local-maximum detection | 4.7 s | 0.4 GB |
| Automatic threshold | 1.4 s | 0.3 GB |
| Thresholding at 18 | 1.6 s | 0.8 GB |
| Gaussian background removal (denoised copy for decomposition) | 8.7 s | 3.5 GB |
| `build_reference_spot`, twice; `modelize_spot` | under 0.1 s | – |
| `get_dense_region` | 2.2 s | 0.7 GB |
| `precompute_erf` and `simulate_gaussian_mixture` | 0.9 s | – |
| `fit_subpixel` (36,550 spots) | 241 s | – |
| `detect_clusters` | 0.1 s | – |
| Maximum projection | under 0.1 s | – |

**One worker, one channel, from reading to clusters** (new process each, 1 run each)

| Background | Subpixel | Image read | Time | Peak memory |
|---|---|---|---|---|
| Top-hat | off | channel 2 only | 67 s | 4.8 GB |
| Top-hat | on | channel 2 only | 306 s | 4.8 GB |
| Rolling ball | off | channel 2 only | 77 s | 4.8 GB |
| Rolling ball | on | channel 2 only | 304 s | 4.8 GB |
| Top-hat | off | whole file first, as v1 does | 68 s | 5.9 GB |

**First estimate of memory per worker: about 5 GB for a 2048 × 2048 × 35 channel**, and about 4.4 GB for 30 planes. This is above the 3–4 GB the spec expected (section 7.2).

- The LoG filter sets the peak: big-fish works on four copies of the channel as 64-bit decimal numbers at once (about 1.2 GB each). The Gaussian background removal for decomposition is the second-highest point (4.6 GB in total).
- The background method and subpixel fitting do not change the peak.
- Rule of thumb from these runs: 0.14 GB + 17 × (planes × height × width × 2 bytes).
- Reading only the channel needed saves about 1.1 GB per worker on this 4-channel image.
- Not included: Cellpose, QC figures, writing tables, cell assignment. A worker that keeps one channel's arrays while it processes the next would need about 1.7 GB more.
- On this 16 GB laptop the estimate allows two workers at most. Lowering the peak would mean running the LoG filter on 32-bit numbers or on blocks of planes, which is a change to how big-fish is called and would have to be shown not to change the spots.

**Checks made along the way**

- Spots detected in `bigfish-msp` with top-hat at threshold 18 are identical to the v1 reference (`hcr_manual18_subpixel-off`): 24,631 spots, same coordinates, same order. The automatic threshold is 15.0, as in v1, with 27,514 spots. Detection therefore gives the same result on the new stack.
- With `np.random.seed(0)` before `build_reference_spot`, decomposition gives 36,550 spots and 196 clusters every time (v1 without a seed: 36,490–37,086 spots and 199–207 clusters).
- Rolling ball, for information: 23,680 spots at threshold 18; its own automatic threshold is 13.0, with 28,199 spots; 36,623 spots after decomposition and 261 clusters at threshold 18. Rolling ball sets 36 % of pixels to zero against 4.8 % for top-hat. The comparison of the two methods is Phase 2 work.
- Repeated by the orchestrator on three planes: 0.92 s per plane for top-hat and 1.25 s for rolling ball.

### 0.9 v1 reference run on the crop (22 Nov 2026)

The same nine runs as in 0.6, on `tests/data/sypN_DAPI_Phal_jim-exon_crop.tif` itself, with unmodified v1 scripts (commit `264ffde`) in the main env and the same settings. No script needed a code change.

| Run folder | Script | Threshold | Subpixel | Spots | Clusters |
|---|---|---|---|---|---|
| `general_manual18_subpixel-off` | general | manual 18 | off | 692 | 6 |
| `general_manual18_subpixel-on` | general | manual 18 | on | 692 | 6 |
| `general_auto_subpixel-off` | general | auto (13) | off | 869 | 6 |
| `general_auto_subpixel-on` | general | auto (13) | on | 869 | 6 |
| `hcr_manual18_subpixel-off` | HCRv3 | manual 18 | off | 473 | – |
| `hcr_manual18_subpixel-on` | HCRv3 | manual 18 | on | 473 | – |
| `hcr_auto_subpixel-off` | HCRv3 | auto (13) | off | 610 | – |
| `hcr_auto_subpixel-on` | HCRv3 | auto (13) | on | 610 | – |
| `hcr_auto_bailout` | HCRv3 | auto (13), bailout at 100 spots | off | 610 (from the bailout file) | – |

The automatic threshold on the crop is 13.0 (15.0 on the full-size image), read from the bailout file as in 0.6.

Where the files are:

- `tests/data/reference_v1/` (in the repository, 0.3 MB): for each run its config, `command.txt` and `.npz` output; for the general runs also the spot table and the reference-spot TIFF; the bailout text file; `summary.csv`, `conda_env_export.yml`, `v1_commit.txt`, the per-cell tables with the script that makes them, and a `README.md`.
- `~/bigfish-testdata/reference_v1/crop/`: the complete run folders, with logs and QC images.

Repeatability: each of the four general runs was run twice and gave identical arrays, tables and reference spots. The two subpixel-off general runs are also identical to the runs made on candidate A during the crop search (0.7), and the HCRv3 spots are identical to the detection computed then. With fewer than 2,000 detected spots, subpixel fitting on and off now give the same number of spots and clusters, unlike on the full-size image.

Per-cell reference counts (`per_cell_counts.csv` in the four subpixel-off run folders, made by `tests/data/reference_v1/per_cell_counts.py` in the main env):

- big-fish `multistack.extract_cell` with the nuclear label image, `ndim=3`, clusters passed as `others_coord`, and `remove_cropped_cell=False`, as in the v1 notebook `general/smFISH-quantification_optimise-parameters.ipynb`. The v1 notebook `smFISH-quantification_get-cell-level-results.ipynb` does not call `extract_cell`, so the call could not be taken from there.
- Columns: `label`, `touches_border`, `n_spots`, and for the general runs `n_spots_in_clusters`, `n_spots_outside_clusters` and `n_clusters`.

| Run | Spots | In a nucleus | Outside any nucleus | Clusters with their centre in a nucleus |
|---|---|---|---|---|
| `general_manual18_subpixel-off` | 692 | 413 | 279 | 5 of 6 |
| `general_auto_subpixel-off` | 869 | 510 | 359 | 5 of 6 |
| `hcr_manual18_subpixel-off` | 473 | 255 | 218 | – |
| `hcr_auto_subpixel-off` | 610 | 333 | 277 | – |

How `extract_cell` (big-fish 0.6.2) behaves, read from its source and confirmed on the crop:

- The `cell_id` it returns is the label value in the label image.
- With `remove_cropped_cell=True` (its default) it drops every cell that touches the outermost row or column, which leaves the 26 nuclei away from the border. The reference tables keep all 44 and mark the 18 border nuclei in `touches_border`.
- A spot is assigned by looking up its (y, x) position in the cell's 2D mask; z is not used. Decimal positions are rounded, not cut down to the whole number below. A cluster is assigned by its centre.
- `n_spots_in_clusters` in the reference tables counts each spot in the nucleus it sits in, the same definition as the spec's `cells.csv` (section 8.2).

Cross-check: looking each spot and cluster centre up directly in the label image gives the same counts as `extract_cell` for every nucleus, in all four runs. The new cell assignment (spec section 5.8) uses this direct look-up.

Notes:

- Only the subpixel-off runs have per-cell tables, because of the `extract_cell` error described in 0.5. On this crop no subpixel position rounds beyond the image edge, so the error would not have appeared here.
- The configs and `command.txt` files in `tests/data/reference_v1/` contain the folder paths of the laptop the runs were made on. They are records of what was run, not files to run again as they are.

### 0.11 Phase 0 review (22 Nov 2026)

Checks run in a fresh shell:

| Check | Result |
|---|---|
| `conda run -n bigfish-msp python -m pytest` in the repository | 1 passed |
| big-fish's own tests on the installed fork tag (`python -m pytest --pyargs bigfish`) | 697 passed |
| PyTorch device in `bigfish-msp` | Apple GPU available |
| `BIGFISH_TEST_DATA` | set; full-size image and reference results present |
| Main env | `conda env export` identical to the export stored with the reference run; `environment.yml` unchanged since `v1.0` |
| v1 copy of the code | no changes |

Phase 0 "done when" (spec section 11):

| Condition | Where recorded |
|---|---|
| big-fish's tests pass in `bigfish-msp` | 0.5 and the table above |
| Reference outputs recorded | 0.6 (full-size image), 0.9 (crop) |
| Test kit recorded | 0.7 (crop and config), 0.8 (labels), 0.9 (reference results in `tests/data/`) |
| Benchmark numbers recorded | 0.10 |
| `pytest` runs in `bigfish-msp` | 0.3, 0.4 and the table above |

**Summary of the phase**

- Stack: every version in the spec's table was available for Apple silicon; versions and device are listed in 0.4.
- big-fish: eight changes in the fork, tagged `v0.6.2.post1` and pushed (0.5).
- Detection on the new stack gives exactly the v1 spots on the full-size image (0.10).
- Test kit: a 384 × 384 × 11 crop with 44 nuclear labels, its config and nine v1 reference runs, all repeatable (0.7–0.9).
- Rolling ball costs about 10 s more per channel than top-hat and stays the default. Memory per worker is about 5 GB for a 35-plane channel (0.10).

**Deviations from the spec and the plan**

| # | Deviation | Task |
|---|---|---|
| 1 | `mrc` 0.4.0 from pip added to the env (big-fish needs it; conda-forge stops at 0.3.1, which fails with numpy 2). | 0.4, 0.5 |
| 2 | Streamlit and `streamlit-image-coordinates` are not in the env until Phase 5. | 0.4 |
| 3 | `pyproject.toml` lists no dependencies and does not yet declare the `bigfish-pypeline` command. | 0.3 |
| 4 | The env file installs the pipeline with `-e ../..`, not `-e .`, because of where the file sits. | 0.4 |
| 5 | big-fish change 7 (`save_image` converts png and jpg to 8-bit) alters behaviour beyond replacing a removed call. Kept by the user's decision. | 0.5 |
| 6 | The big-fish fixes have not been offered to the original project. | 0.5 |
| 7 | An extra HCRv3 run with bailout on records the automatic threshold, for the full-size image and for the crop. | 0.6, 0.9 |
| 8 | An extra repeat of one general run on the full-size image shows that v1 results vary from run to run there. | 0.6 |
| 9 | Added condition for the crop: fewer than 2,000 detected spots. | 0.7 |
| 10 | The nuclear label image is the Cellpose 3 draft, accepted by the user without hand correction. | 0.8 |
| 11 | Per-cell reference tables keep the nuclei that touch the border and mark them, instead of leaving them out. | 0.9 |
| 12 | Memory is measured as physical footprint, which reads higher than resident memory. | 0.10 |
| 13 | Tests are run with `python -m pytest`, because `conda run … pytest` finds another pytest on this laptop. | 0.4 |

**Points carried into Phase 1**

1. Memory per worker is about 5 GB for 35 planes and 4.4 GB for 30, above the 3–4 GB in spec section 7.2. The LoG filter sets the peak. `workers: auto` has to use the measured figure; lowering it would mean changing how the LoG filter is run and showing the spots stay the same.
2. Rolling ball has to be applied one plane at a time (0.10).
3. On the full-size image the v1 decomposition is not repeatable, so decomposed spots and clusters are compared as counts there (within about 2 %), and exactly on the crop.
4. The config's file filter also matches `…_seglabels.tif` when labels sit next to the images; file discovery needs a rule for this.
5. `extract_cell` rounds decimal positions and fails at the image edge; the new cell assignment looks positions up directly and has to handle the edge.
6. The first and last planes of a Z-cropped image hold extra spots; this affects any image whose signal continues beyond the stack.
7. big-fish still uses calls that scikit-image will remove in 0.27, 0.28 and 2.0 (listed in 0.5); the env keeps scikit-image below 0.27.
8. The test kit config is written in the version 1 layout and is checked against the schema once it exists.

**Manual checks for the user**

1. Look at `~/bigfish-testdata/reference_v1/full/general_manual18_subpixel-off/bf_output_qc/…_finaldetection.png` and the matching elbow plot in `general_auto_subpixel-off`: do the spots, clusters and the automatic threshold of 15 look right for this image?
2. Open `tests/data/sypN_DAPI_Phal_jim-exon_crop.tif` in Fiji: three channels, 11 planes, pixel size 0.065 µm and Z-step 0.2 µm shown correctly.
3. Read through the deviations above, and deviation 5 and point 1 in particular.
4. Confirm that `msp` can be pushed to GitHub (the commits for tasks 0.2–0.11 are on this laptop only) and say when to merge it into `main`.

**Housekeeping**

- `~/bigfish-testdata/` holds 2.1 GB: the image (1.1 GB), the crop search (0.9 GB, mostly working copies that can be deleted), reference results (51 MB), benchmarks and the label draft.
- `tests/data/` adds 10 MB to the repository.
- An older, empty `test/` folder sits next to `tests/` in the working copy; it is not tracked by git.

**Sign-off (22 Nov 2026):** the user signed off Phase 0 and approved pushing `msp` to GitHub. `msp` was then merged into `main` and both were pushed. The repository's address on this laptop was updated to `JeffLeeLab/bigfish-pypeline`.

## Phase 1: Package and unified pipeline

### 1.0 Decisions and test helpers (22 Nov 2026)

Decisions by the user before the tasks started:

1. **OMERO server:** host `10.34.168.89`, port 4064, stored in the package as the default.
2. **Label files next to images:** a file whose name ends in `_seglabels` is never listed as an image.
3. **Memory per worker:** the LoG filter is run as in v1, and `workers: auto` is sized from the 5 GB measured in Phase 0 (two workers on a 16 GB laptop). This replaces the 3–4 GB expected in spec section 7.2 until the Phase 2 measurements.

Set up for the phase:

- `image_utils.py` and `omero_tools.py` stay unchanged until Phase 8, because the v1 scripts and notebooks on `main` import them in the main env.
- `tests/conftest.py` gives the tests the paths to the test kit, its v1 reference results and the full-size image.
- Tests that need the full-size image carry the mark `full_image`. They are skipped when `BIGFISH_TEST_DATA` is not set, and can be left out with `python -m pytest -m "not full_image"`.

### 1.1 PSF and background (22 Nov 2026)

- `psf.py`: `calculate_psf`, with the same values as v1 for confocal, widefield and nipkow.
- `rolling_ball.py`: `imagej_rolling_ball.py` copied unchanged from JeffLeeLab/Image-analysis (commit `24bbbd4`), with its tests and the ImageJ fixture (`tests/data/rolling_ball/`, 0.3 MB).
- `background.py`: `subtract_background(image, radius, light_bg=False, method="rolling_ball")` for 2D images and 3D stacks, one plane at a time.
- Checks: top-hat at 5 px on channel 2 of the crop is identical to v1; rolling ball through `subtract_background` agrees with the ImageJ fixture; 74 tests pass.

Choices the spec does not settle:

- Data type of the result. Top-hat returns the type of the image, as in v1. Rolling ball follows ImageJ: 8-bit and 16-bit images keep their type, with values below the background set to 0; other types come back as 64-bit float.
- `light_bg=True` gives a different kind of result for the two methods: rolling ball keeps dark objects on a white background, as ImageJ does; top-hat turns them bright on a dark background, as v1 does. The pipeline never sets `light_bg`, because fluorescence images have a dark background.

### 1.2 Config (22 Nov 2026)

- `config.py`: the layout and defaults of spec 6.2 as `pydantic` models, `load_config`, `save_config`, `parse_config` (for the notebook and the app) and `apply_overrides` (command-line values).
- Every problem in a file is reported at once, each as one plain message naming the setting, e.g. "`channels[0].clusters.nb_min_spot` is not a known setting – did you mean `min_spots`?".
- Checks: the test kit config loads unchanged and is the same after saving and loading again; 112 tests pass.

Choices the spec does not settle:

- Required with no default, besides `image.axes` and `image.voxel_size_nm`: `config_version`, at least one channel, and each channel's `index`.
- Messages name a setting by its full path (`channels[0].threshold.value`), not by its bare name as in the spec's example.
- The `resolved` block holds `images` (a list of names) and `thresholds` (channel index → calibrated value).
- A new input folder, filter, dataset ID or list of image IDs drops `resolved`; a new output folder or number of workers keeps it.
- `yes`, `no`, `on` and `off` given where a number or text is expected are reported with a note that YAML reads them as true or false.
- Not checked when a file is loaded, left to `check` and `batch`: an OMERO source without a dataset ID or image IDs.

### 1.7 Cell assignment and label files (22 Nov 2026)

- `segmentation.py`: `read_label_file` reads `<image>_seglabels.tif` and accepts only a 2D image of the image's Y × X size holding whole numbers of 0 or more. Whole numbers saved as decimals (as Fiji may do) are accepted. Each kind of unusable file gives a one-line reason.
- `cells.py`: `assign_cells` gives the `cell_id` of every spot and cluster and the cell table of spec 8.2.
- Checks: on the crop, the cell table equals the v1 per-cell reference for all 44 labels in the four subpixel-off runs, including the 18 nuclei that touch the border; 39 tests pass.

Choices the spec does not settle:

- A cluster centre given as a decimal number is rounded to the nearest pixel and kept inside the image, so a centre on the edge cannot fail as it does in `extract_cell`.
- With clustering switched off, `n_spots_in_clusters` and `n_clusters` are 0 and `mean_spots_per_cluster` is empty.
- A label file with an extra axis of length 1 is rejected as not 2D.

### 1.3 Local image input (22 Nov 2026)

- `io.py`: `list_images` (file list), `output_name` and `check_output_names`, `get_image_info` (shape, data type, suggested layout, time points, positions and voxel sizes from the file header), `read_channel` and `read_channels` (one array per channel, `ZYX` or `YX`), `check_voxel_sizes` (warning when a file disagrees with the config).
- Only the planes of the channels asked for are read. On the full-size image, channel 2 takes 0.3 s and 0.3 GB, against 1.2 GB for reading the whole file.
- Checks: generated files in every layout and in 8-bit, 16-bit and 32-bit float; the crop and the full-size image are reported as `ZCYX` with 200 nm and 65 nm; 96 tests pass.

Choices the spec does not settle:

- An axis of length 1 is not counted, so a file with one channel is `ZYX`, not `ZCYX`.
- The confirmed layout decides how the axes are read, even when the file's metadata suggests another order.
- A TIFF without ImageJ or OME metadata can only be read as `ZYX`, `CYX` or `YX`, because such a file cannot record both Z and channels. v1 had the same limit.
- Voxel sizes are taken from ImageJ and OME metadata only, not from the general TIFF resolution tags.
- The extension is matched whatever its case (`.TIF` is listed); the filter text is case-sensitive; hidden files are left out. Two names that differ only in case count as a clash, because their result files would overwrite each other on macOS and Windows.
- `x.ome.tif` gives the output name `x.ome`.
- NaN and infinite values are checked only in the channels that are read. Colour (RGB) files are rejected.
- ImageJ files over 4 GB store the whole image as one block; these are read through a memory map, one channel at a time.
- A file cut short is reported as damaged, using the problems `tifffile` logs while reading. This check is per process, which suits the batch workers.

### 1.8 Tables and run folder (22 Nov 2026)

- `outputs.py`: the spots, clusters, cells, images and calibration tables of spec 8.2; per-image files in `per_image/`; the combined tables; the run folder; `run_config.yaml`.
- An image's files are written under temporary names (`….csv.tmp`) and renamed once all are written, `_images.csv` last, so an image whose `_images.csv` exists is complete.
- The combined tables are made by joining the per-image files as text, so a large run does not have to fit in memory.
- Checks: column names and order against spec 8.2 for 2D and 3D; `run_config.yaml` loads back to an equal config; 42 tests pass.

Choices the spec does not settle:

- The optional spots columns (subpixel positions, `snr`, `log_intensity`) are set once for the whole run: they are present when any channel uses them and stay empty for the other channels. Every per-image file of a run therefore has the same columns.
- An image that failed as a whole writes only its `_images.csv`. `_cells.csv` is written only when the image has cell results; when segmentation found no cells it holds the column names only.
- A combined table is written only when at least one image has that kind of file.
- CSV files are plain UTF-8 without a byte-order mark, with the same line endings on every system. Excel on Windows may show accented image names wrongly; R and pandas read them correctly.
- In the run name, characters Windows does not allow are replaced with `_`, and spaces and full stops at the end are removed.
- A local run with neither an input folder nor an output folder is stopped with a message.

### 1.4 Spot detection (22 Nov 2026)

- `detection.py`: `get_spot_radius_px`, `filter_channel` (gives `rna`, `rna_log`, `rna_mip`), `detect_spots` (manual, auto with lower limit, or a calibrated value), `get_elbow_values`, `calibrate_threshold` (median of the usable automatic thresholds) and `exceeds_bailout`. All work in 2D and 3D.
- `tests/synthetic.py`: generator of test images with Gaussian spots at known positions, used by later tasks.

Comparison with v1 (top-hat 5 px, reference settings), position for position:

| Image | Threshold | v1 spots | New code |
|---|---|---|---|
| Crop | manual 18 | 473 | identical |
| Crop | auto, 13.0 | 610 | identical, threshold 13.0 |
| Full-size | manual 18 | 24,631 | identical |
| Full-size | auto, 15.0 | 27,514 | identical, threshold 15.0 |

18 tests pass; the full-size test takes about a minute.

Findings and choices:

- big-fish gives no automatic threshold when 7 or fewer candidate spots have a LoG value above 0. In practice this means blank or nearly empty images. The channel then has zero spots, an empty threshold and a warning; the lower limit is not used in place of a missing threshold.
- The elbow values are worked out from the `rna_log` already in hand, so the LoG filter runs once. The automatic threshold is taken from the same calculation and equals big-fish `automated_threshold_setting`. This uses two internal big-fish functions (`_get_candidate_thresholds`, `_get_spot_counts`), which is safe while the env installs the fork at a fixed tag.
- The bailout limit is exceeded when the count is above the limit, as in v1.

### 1.6 Spot measurements (22 Nov 2026)

- `measurements.py`: `compute_snr_spots_individual` (from the posthoc script, extended to 2D), `compute_log_intensity` (value of `rna_log` at the spot's own position) and `measure_spots` (both, according to the switches).
- Checks: for the 692 spots of the crop, the SNR equals the posthoc function exactly; 2D values equal the 3D formula with Z left out; 25 tests pass.
- Time: SNR for 40,000 spots in a 2048 × 2048 × 30 image takes 1.6 s.

Choices and differences from the posthoc function:

- The SNR is empty when the ring is empty or has no variation, where the posthoc function gave 0. None of the crop's spots is affected.
- The function takes the spot radius in pixels (`spot_radius_px`), which the pipeline already has; the posthoc function converted it from nm itself, with the same result.
- `log_intensity` keeps the data type of `rna_log` (16-bit whole numbers for a 16-bit image).

### 1.13 OMERO input, first part (22 Nov 2026)

Written and tested without a server; the check on the lab server is still to be run by the user.

- `io.py`, OMERO section: `list_omero_images` (by dataset ID or image IDs), `omero_output_name` (`<image ID>_<image name>`), `get_omero_image_info` (sizes, pixel type, voxel sizes in nm, channel names), `read_omero_channel` and `read_omero_channels`, `read_omero_channels_with_retry`, and the session helpers `session_key`, `join_session` and `detach_session`.
- `connect_to_omero` and `get_omero_image` in `omero_tools.py` are used as they are.
- `omero` is loaded only when an OMERO function is called, so local runs do not need it.
- `tests/manual/omero_session_check.py`: the script for the lab-server check. The main process logs in, two helper processes join the login, read the image and leave, and the main login is tested again afterwards.
- Checks: 60 tests with stand-in connections pass.

omero-py calls used: the session key from `conn.c.getSessionId()`; joining with `BlitzGateway(host, port, secure=True).connect(sUuid=key)`; leaving with `conn.close(hard=False)`.

Choices the spec does not settle:

- A dataset's images are sorted by name, then ID. A list of image IDs keeps its order, with repeats left out.
- As for local files, an axis of length 1 is not counted. OMERO stores no axis order, so `ZCYX` and `CZYX` are both accepted for an image with several planes and channels.
- A voxel size with a unit the code does not know is treated as missing, where the archived app used the number as if it were nm.
- An image in another OMERO group is reported as not found; the connection's group is not changed.
- The session key is removed from every error message, and omero-py's own INFO and DEBUG messages, which contain the key, are switched off.
- If the server does not answer while a worker rejoins the session, this is reported as an ended session and stops the run, because omero-py does not tell the two cases apart.

Still to be confirmed on the lab server: that a joined worker can read images, that leaving with `close(hard=False)` keeps the main login alive, and which errors a dropped connection and an ended session really raise.

Carried to Phase 5: the batch process taking over a session handed to it by the app (keeping it alive and closing it at the end).

### 1.5 Decomposition, subpixel fitting and clusters (22 Nov 2026)

- `decomposition.py`: `decompose_dense_regions` (as v1, in 2D and 3D) and `get_seed`. `subpixel.py`: `fit_subpixel`. `clusters.py`: `detect_clusters`.
- Both `fit_subpixel` and `detect_clusters` keep the order of the spots, so row i is the same spot in every output table.
- 42 tests pass (about 40 s; the crop's subpixel fits take most of it).

Comparison with v1 on the crop (top-hat 5 px, alpha 0.5, beta 1, cluster radius 600 nm, minimum 12 spots):

| Result | Manual 18 | Auto (13.0) |
|---|---|---|
| Spots and clusters, subpixel off | identical (692 and 6) | identical (869 and 6) |
| Reference spot from `rna` | identical | identical |
| Cluster membership and cluster sizes, subpixel on | identical | identical |
| Subpixel positions | differ, see below | differ, see below |

**Subpixel positions differ from v1 because of the newer packages, not the new code.** As the spec asks, the unchanged v1 scripts were run in `bigfish-msp` on the crop (`~/bigfish-testdata/phase1/v1_in_new_env/`; the four `.npz` files are kept in `tests/data/reference_v1_new_env/`). Their results are identical to the new code, value for value. Compared with v1 in the main env (scipy 1.7.3, numpy 1.21.6), subpixel fitting in the new env (scipy 1.18.1, numpy 2.5.5) moves:

| Run | Spots | Moved > 0.01 px | Moved > 0.1 px | Moved > 0.5 px | Largest move (z / y / x, px) |
|---|---|---|---|---|---|
| General, manual 18 | 692 | 6.4 % | 3.2 % | 2 | 1.75 / 0.0005 / 0.0007 |
| General, auto | 869 | 6.4 % | 3.2 % | 3 | 0.89 / 1.33 / 0.45 |
| HCRv3, manual 18 | 473 | 8.5 % | 3.8 % | 1 | 0.63 / 0.0005 / 0.0007 |
| HCRv3, auto | 610 | 8.0 % | 3.6 % | 2 | 0.63 / 1.33 / 0.45 |

- The typical spot moves by about 3 × 10⁻⁸ px. The larger moves are almost all in Z; one spot in the auto runs moves in Y and X.
- Cluster centres move by at most 0.08 px. The same spots fail to fit in both envs.
- The tests compare the pipeline with the new-env results to within 10⁻⁶ px, and with the main-env results within the limits above.
- For the user to judge at the phase review: whether this change in subpixel positions is acceptable.

Findings and choices:

- big-fish picks the 2,000 spots for a reference spot with numpy's general random generator, and builds three reference spots for each channel (two in the pipeline, one inside `get_dense_region`). The seed is set before each of the three, so all use the same spots, and the generator is put back as it was afterwards.
- The seed comes from `run.seed`, the image name and the channel number through SHA-256, so it is the same in every process and on every system.
- How big-fish shows each case where decomposition is skipped: no spot clear of the image edge gives an empty reference spot; a model that cannot be fitted raises `RuntimeError`; no dense regions gives an empty list (v1 stopped with an error here). The result carries `skipped` and a warning text for each case except the last.
- With 30 spots or fewer clear of the edge, big-fish still builds a reference spot and decomposition goes on, as in v1. Its own warning is turned into a warning in the result, so it reaches `images.csv`.
- big-fish only accepts a cluster radius in whole nm, so `clusters.radius_nm` in the config must be a whole number (spec 6.2 does not say).

### 1.9 One image through every step (22 Nov 2026)

- `batch.py`: `process_image` runs steps 1–8 and 10 for each FISH channel of one image, one channel at a time, and writes the image's tables. `calibration_threshold` gives one image's automatic threshold for the calibration pass.
- Checks on the crop, through `process_image` and the written tables:

| Settings | Result |
|---|---|
| Test kit config (manual 18) | spots, clusters and cell table identical to v1: 473 detected, 692 spots, 6 clusters, 44 cells |
| Auto threshold | 13.0; 869 spots and 6 clusters, identical to v1 |
| Decomposition and clusters off (HCRv3 case), manual and auto | 473 and 610 spots, identical to v1; cell tables identical |
| Subpixel on | subpixel positions equal the v1 script run in the new env; pixel positions and `cell_id` unchanged |

- Generated images cover three channels with their own thresholds, a failing channel, bailout, a blank image, 2D, a corrupt file, missing and wrong-size label files, voxel sizes that differ from the config, and a calibrated threshold. 28 tests pass; `process_image` also runs in a worker process started with "spawn".

How results are recorded in `images.csv`:

- A channel that fails is `failed` with a one-line reason; its threshold and number of detected spots are kept when detection had finished. The other channels are kept.
- An image that cannot be used at all (unreadable file, layout that does not fit, a channel of the config missing from the image) has every channel `failed` and writes only its `_images.csv`.
- Bailout gives `skipped` with the reason, e.g. "bailout: 5120 spots detected, above the limit of 5000"; the channel has no rows in the other tables.
- An unusable label file gives `segmentation_status` `no_labels` and a warning with the reason; spots are still written with `cell_id = -1`.

Findings and choices:

- With subpixel fitting on, clusters are found on the subpixel positions, as in v1, so cluster membership can differ from a run with subpixel fitting off (one spot on the crop).
- With clustering switched off in every channel, no clusters file is written; `n_clusters` is 0.
- big-fish cannot cluster whole-pixel positions when the voxel sizes are written as decimals. `clusters.py` now handles this: whole voxel sizes are passed as whole numbers (same result as v1), and for voxel sizes such as 64.5 nm the positions are passed as decimals.
- Each worker joins the OMERO session once and keeps the connection for its later images. A dropped connection is retried once while a channel is read, but not while the image information is read.
- If the tables themselves cannot be written (for example a full disk), the error is passed up to the runner, because it is a problem with the output folder and not with the image.

### 1.10 Batch runner (22 Nov 2026)

- `batch.py`: `run_batch(config, …)` carries out the run flow of spec 7.1 without Cellpose and returns the run folder, the final status (`finished`, `cancelled` or `stopped`) and a message. Problems found before any image is processed raise `BatchError` with a plain message, and no run folder is made.
- `psutil` 7.2.2 (already installed as a dependency of other packages) is now listed in `msp-environment.yml`; it gives the free memory for the number of workers.
- Checks: the test kit with 1 and 2 workers gives identical tables that agree with v1; a cancelled run, a run whose worker stops once, twice, or with a single worker, and a repeated run all behave as the spec describes; 27 tests pass (about 40 s) and no worker processes are left behind.

Number of workers (`workers: auto`): the smaller of (CPU cores − 1) and (free memory − 2 GB) ÷ (memory per worker), not more than the number of images. Memory per worker is 35 bytes for each voxel of one channel of the largest image, at least 0.5 GB; this gives 5.1 GB for 2048 × 2048 × 35, as measured in Phase 0. A number given in the config is used as it is, with a warning in the log when memory may run short.

`progress.json` holds: `status` (`running`, `finished`, `cancelled`, `stopped`), `step` (`calibration`, `images`, `end`), `n_images`, `n_finished`, `in_progress` (names), `channels` (counts of done, failed and skipped), `calibration` (total and finished), `workers`, `started`, `updated` and `message`.

Sample of `run.log` (test kit):

```
2026-11-22 22:44:31  1 image(s):
                       sypN_DAPI_Phal_jim-exon_crop.tif
2026-11-22 22:44:31  Workers: 1 worker(s), as set in the config.
2026-11-22 22:44:31  sypN_DAPI_Phal_jim-exon_crop: started
2026-11-22 22:44:33  sypN_DAPI_Phal_jim-exon_crop, channel 2: done, threshold 18, 692 spots, 6 clusters, 44 cells
2026-11-22 22:44:33  sypN_DAPI_Phal_jim-exon_crop: finished
2026-11-22 22:44:33  Summary: 1 of 1 image(s) finished, 0 not processed; channels: 1 done, 0 failed, 0 skipped. Total time 2 s.
```

Findings and choices:

- Python 3.12 has no public way to stop the workers of a `ProcessPoolExecutor` at once. The runner ends each worker process itself (`terminate`, then `kill` if needed), through the executor's internal list of processes. This works the same on macOS, Windows and Linux; Python 3.14 adds a public call for it.
- If the first image cannot be read, the run stops before processing, because that image is used to check the layout and the channels. A later unreadable image only fails.
- A worker that runs out of memory with an error, instead of stopping, is treated like a stopped worker.
- "A single worker" means one worker at the moment of the stop: a run that started with two and has already been halved once ends at the next stop.
- When the OMERO session ends, images in progress are discarded straight away, as for cancel.
- If calibration gives no usable value for a channel, the run ends with status `stopped` and keeps `calibration.csv`.
- If the tables cannot be written (for example a full disk), the run ends with status `stopped`.
- Calibration filters are matched against the file name (local) or `<ID>_<name>` (OMERO).
- The thread settings (`OMP_NUM_THREADS` and the two others) are put back to their old values when the run ends.
- For a `cellpose` source the run stops before processing with a message; Cellpose is added in Phase 2.

### 1.11 Command line (22 Nov 2026)

- `cli.py`: `bigfish-pypeline batch <config.yaml>` and `bigfish-pypeline check <config.yaml>`, both with `--input-folder`, `--filter`, `--output-folder` and `--workers`; `bigfish-pypeline --version`. The command is declared in `pyproject.toml`. `python -m bigfish_pypeline.cli` does the same.
- `check` carries out every check a run makes before processing and prints what the run would do (images in order, channels and thresholds, cell results, output folder, workers), without saving anything. To share these checks, the first part of `run_batch` became `plan_run` in `batch.py`.
- Mistakes in a config, and problems found before the run, are printed as plain messages without a Python traceback.
- Checks: both commands run on the test kit from another folder; 21 tests pass.

Choices the spec does not settle:

- Exit codes: 0 when the run finished (also when some images failed; the last lines say how many), 1 for a problem before or during the run, 130 when the run was cancelled.
- `check` on an OMERO config logs in, so it asks for the password.
- The `app` command is added in Phase 5.

### Decision: `workers: auto` when little memory is free (22 Nov 2026)

Deviation from spec section 7.2, decided by the user. On a Mac in everyday use the free memory reported is low: about 4 GB of 17 GB on this laptop with an editor and a browser open. A worker for the full-size image is estimated at 5.1 GB, so the spec's rule would refuse to start a run that v1 carries out without trouble.

- When the free memory, less the 2 GB reserve, is too small for one worker but the computer's total memory is enough, the run goes on with one worker and a warning in the log that it may be slow.
- The run stops before processing only when the computer's total memory is too small for one worker.
- More than one worker is still chosen from the free memory.

### 1.12 End-to-end tests (22 Nov 2026)

`tests/test_end_to_end.py` starts `bigfish-pypeline batch` as a separate process, as a user would, with the real pipeline. 18 tests pass in about 75 s, and no processes are left behind.

| Case | Result |
|---|---|
| Test kit with label files | spots, clusters and cell counts agree with v1 (692 spots, 44 cells) |
| Test kit with segmentation off | no cells table; `cell_id` −1; spots unchanged |
| Mixed batch of 8 images, 2 workers: different sizes, a blank image, another layout, a corrupt file, NaN values, a name with spaces, accents and Japanese characters, a missing label file, a `bigfish_results/` folder from an earlier run | the run finishes; 5 images done, 3 failed with their reasons; tables in name order; earlier results not picked up as images |
| Three FISH channels with their own manual thresholds | all three processed (v1 allowed two) |
| 2D batches (`YX`, `CYX`) | no Z columns |
| 8-bit, 16-bit and 32-bit float input | processed; float gives the same spots as 16-bit |
| Empty `output_folder`, and a second run in the same minute | results in `<input>/bigfish_results/`; second folder numbered |
| Repeat from `run_config.yaml` | same tables |
| Ctrl+C, and a `cancel` file | exit code 130, status `cancelled`, tables hold exactly the finished images, no temporary files |
| One worker process killed during a run with 2 workers | restart with 1 worker, lost images tried again, all 8 images done |
| First image unreadable or of another layout; output folder not writable | plain message, exit code 1, no run folder |

Not covered: Ctrl+C on Windows (left to Phase 7; the `cancel` file is tested on every system).

Carried forward: `outputs.label_images` has no effect yet, because label files given by the user are not copied into the run folder; the `labels/` folder comes with Cellpose in Phase 2.

### 1.14 Full-size image comparison (22 Nov 2026)

Five runs of `bigfish-pypeline batch` on channel 2 of the full-size image, with top-hat at 5 px and the reference settings, one worker. Configs, printed output and run folders are in `~/bigfish-testdata/phase1/full/`.

| Run | Threshold | Detected spots | Spots | Clusters | v1 spots / clusters | Time (v1) | Peak memory |
|---|---|---|---|---|---|---|---|
| HCRv3 settings, manual | 18 | 24,631 | 24,631 | – | 24,631, identical positions | 62 s (74 s) | 4.1 GB |
| HCRv3 settings, auto | 15.0 | 27,514 | 27,514 | – | 27,514, identical positions | 61 s (106 s) | 4.8 GB |
| General, manual | 18 | 24,631 | 36,360 | 199 | 37,086 / 207 | 73 s (98 s) | 4.4 GB |
| General, auto | 15.0 | 27,514 | 41,249 | 246 | 41,274 / 234 | 75 s (137 s) | 4.0 GB |
| General, manual, subpixel on | 18 | 24,631 | 36,360 | 201 | 36,699 / 200 | 306 s (329 s) | 4.8 GB |

Peak memory is the largest resident memory of one process, which reads lower than the physical footprint used in Phase 0.

**Detection is identical to v1.** After decomposition the counts differ by up to 2 %, which v1's random reference spot explains:

- v1 itself gave 37,086, 36,699 and 36,490 spots in its three runs at threshold 18 (207, 200 and 199 clusters).
- The new code with six different seeds gave 36,360, 36,915, 36,528, 37,126, 36,756 and 36,441 spots (197 to 212 clusters). All three v1 results lie inside this range.
- 96 % of the positions in the v1 run are also found by the new run with seed 0; two v1 runs share 98 % with each other.
- A repeat of the new run with the same seed gives identical tables, which v1 could not do.

Because the difference is explained, the v1 script was not run in the new env on the full-size image; on the crop, where no random choice is made, that comparison gave identical results (1.5).

The auto runs are faster than v1 mainly because v1 ran the LoG filter a second time for its elbow plot.

`tests/test_full_image.py` keeps this check: identical detection, spot count within 3 % and cluster count within 10 % of the v1 run, and at least 95 % of v1's positions found.

### 1.15 Phase 1 review (22 Nov 2026)

Checks run in a fresh shell:

| Check | Result |
|---|---|
| `conda run -n bigfish-msp python -m pytest` (whole suite, with the full-size image) | 604 passed in 5 min 21 s |
| The same without the full-size image (`-m "not full_image"`) | 600 passed in about 3 min |
| v1 imports in the main env (`image_utils`, `omero_tools` from `src/`, Python 3.9) | work as before |
| Main env | `conda env export` identical to the export stored with the reference run |
| v1 files (`environment.yml`, `image_utils.py`, `omero_tools.py`, the v1 folders) | unchanged since `v1.0` |
| Worker processes left after the tests | none |

Phase 1 "done when" (spec section 11):

| Condition | Result | Entry |
|---|---|---|
| Detected spots identical to v1, crop and full-size image | identical, position for position | 1.4, 1.14 |
| Decomposed spots and clusters identical on images with up to 2,000 spots | identical on the crop | 1.5, 1.9 |
| Above 2,000 spots, counts compared and the difference recorded | within the range of v1's own runs | 1.14 |
| Per-cell counts on the crop match `extract_cell` | identical for all 44 nuclei, border ones included | 1.7, 1.9 |
| A cancelled run and a run with a stopped worker leave combined tables | yes, with stand-ins and with the real pipeline | 1.10, 1.12 |
| Any difference from v1 explained | subpixel positions: caused by the newer packages, shown by running the v1 script in the new env | 1.5 |

Still open: the check of OMERO session sharing on the lab server (1.13), to be run by the user.

**What Phase 1 delivered**

- The package modules of spec 4.1 except `qc.py`, with Cellpose still to be added to `segmentation.py`: 5,700 lines in `src/bigfish_pypeline/`, 604 tests.
- `bigfish-pypeline check` and `bigfish-pypeline batch`, for local folders and OMERO, 2D and 3D images, any number of FISH channels.
- A run folder with `run_config.yaml`, `run.log`, `progress.json`, per-image tables and combined tables.
- On the full-size image a run takes 61–75 s where v1 took 74–137 s, with the same peak memory.

**v1 faults fixed** (spec section 11): manual thresholds for more than two channels; errors recorded for each image and channel, and stopped workers restarted, in place of workers ending silently; the config given as a file and read with the safe loader; images processed in name order; bailout recorded in the log and in `images.csv`. Also: an image without dense regions made the v1 general script stop with an error.

**Deviations from the spec and the plan**

| # | Deviation | Entry |
|---|---|---|
| 1 | `workers: auto` uses 5 GB per worker for a full-size channel, not 3–4 GB. User's decision. | 1.0 |
| 2 | With little free memory, `workers: auto` runs one worker with a warning and stops only when the computer's total memory is too small. User's decision. | Decision entry |
| 3 | Files ending in `_seglabels` are never listed as images. User's decision. | 1.0 |
| 4 | `image_utils.py` and `omero_tools.py` are kept unchanged until Phase 8, so `calculate_psf` and the top-hat exist twice. | 1.0 |
| 5 | Subpixel positions differ from v1 for 3–4 % of spots by more than 0.1 px, because of the newer packages. | 1.5 |
| 6 | `clusters.radius_nm` must be a whole number. | 1.5 |
| 7 | `psutil` added to the env file. | 1.10 |
| 8 | An extra reference folder, `tests/data/reference_v1_new_env/` (0.1 MB). | 1.5 |
| 9 | A TIFF without ImageJ or OME metadata can only be read as `ZYX`, `CYX` or `YX`. | 1.3 |
| 10 | An SNR that cannot be worked out is empty, where the posthoc script gave 0. | 1.6 |
| 11 | Workers are stopped through an internal part of Python's process pool, because Python 3.12 offers no public way. | 1.10 |
| 12 | Taking over an OMERO session handed over by the app is left to Phase 5. | 1.13 |
| 13 | The elbow values are not worked out during a run yet; they come with the elbow plot in Phase 3. `outputs.label_images` has no effect until Phase 2. | 1.9, 1.12 |
| 14 | The v1 script was run in the new env on the crop only, not on the full-size image, because the difference there is explained by the random reference spot. | 1.14 |

**Points carried into Phase 2 and Phase 3**

1. Cellpose: the run stops with a message for `source: cellpose` until Phase 2; labels then reach the workers as files in `labels/`.
2. The final per-worker memory figure and reserve, with every step switched on and with the Cellpose model loaded (Phase 2).
3. QC images, `run_info.yaml`, `.npz` files, keep-awake and the full `run.log` contents (Phase 3). `decompose_dense_regions` already returns the reference spot and whether decomposition was skipped.
4. OMERO: after the lab-server check, a small real OMERO batch; a retry when the connection drops while image information is read; what the errors of a dropped connection and an ended session really look like.
5. Ctrl+C on Windows (Phase 7).
6. The guide should explain: plain TIFFs need ImageJ or OME metadata to hold Z and channels; CSV files are UTF-8 without a byte-order mark; the meaning of `finished`, `cancelled` and `stopped`.

**Manual checks for the user**

1. Run the OMERO check on the lab network: `python tests/manual/omero_session_check.py --image-id <ID>` in the `bigfish-msp` env, and pass on the printed lines.
2. Try the commands on the test kit, from the repository folder with `bigfish-msp` active:
   `bigfish-pypeline check tests/data/sypN_DAPI_Phal_jim-exon_crop_config.yaml --output-folder ~/Desktop/bigfish_test`, then the same with `batch`. Look at `run.log`, `images.csv`, `spots.csv` and `cells.csv` in the run folder: are the wording and the columns what you expect?
3. Look at a full-size run folder, e.g. `~/bigfish-testdata/phase1/full/runs/2026-11-22_2258_general_manual18_subpixel-off/`.
4. Decide whether the change in subpixel positions (deviation 5, numbers in 1.5) is acceptable.
5. Read the "choices the spec does not settle" in entries 1.2, 1.3, 1.8, 1.9 and 1.10, which decide what users see.

**Housekeeping**

- `~/bigfish-testdata/phase1/` holds the full-size runs of this phase and the v1 runs in the new env (about 100 MB).
- `tests/data/` holds about 10 MB.
- `msp` is 17 commits ahead of GitHub: only the Phase 1 plan has been pushed, none of the Phase 1 work.

**Decisions by the user (22 Nov 2026):** the change in subpixel positions caused by the newer packages (deviation 5) is accepted. `msp` is pushed to GitHub. Sign-off on Phase 1 and the merge into `main` wait for the OMERO check on the lab server.

**Sign-off (22 Nov 2026):** the user signed off Phase 1 and asked for `msp` to be merged into `main`. The OMERO check on the lab server (manual check 1) has not been run; it is left as a follow-up and stays in the plan's open points, together with the small real OMERO batch.

## Phase 2: Cellpose 4 and comparisons

### 2.0 Decisions (22 Nov 2026)

The user agreed the three proposals in the plan before any task started:

1. **Label files given by the user** are not copied into the run folder. `outputs.label_images` applies to Cellpose labels only; `run_config.yaml` and `run.log` name the label folder used.
2. **When the chosen device does not work:** with `device: auto` the next device is tried (CUDA, then Apple GPU, then CPU) and a warning is logged; a device named in the config that does not work stops the run before processing.
3. **Rolling ball comparison:** the full-size test image (exon channel 2 and intron channel 3) and the crop. No other images were added.

`main` (Phase 1) and `msp` (with the Phase 2 plan) were pushed to GitHub. The tasks have not started.

### 2.0 Test marker (23 Nov 2026)

- `pyproject.toml`: marker `cellpose`. `tests/conftest.py`: tests with this marker are skipped when the model file `cpsam_v2` is not in Cellpose's model folder (`~/.cellpose/models/`, or the folder named by `CELLPOSE_LOCAL_MODELS_PATH`). Tests never download it.

### 2.1 Pre-treatment (23 Nov 2026)

- `segmentation.py`: `pretreat_channel(image, projection, clip, clip_value, background, bg_method, bg_radius, median_px, gaussian_sigma_px)` turns the segmentation channel into the 2D image given to Cellpose, in the order of spec 5.7. `describe_pretreatment` gives the same settings as one line for the QC figure title, e.g. "max projection | rolling ball 200 px".
- Checks: each step alone and all steps in order on generated images; 2D and 3D input; with every step off the projection comes back unchanged; rolling ball at 200 px on the crop's DAPI projection equals a direct call of `subtract_background`. 40 new tests; 641 pass without the full-size image.

Choices the spec does not settle:

- Projection: max keeps the image's data type; mean gives 64-bit float. A 2D image is used as it is, whichever projection is set.
- Clip: as in the v1 tissue-culture script (`np.clip(image, 0, value)`), so values below 0 are also set to 0. The data type is kept, so a 16-bit image stays 16-bit for the rolling ball, and a clip value with decimals acts as the whole number below it on such an image. A clip value above the image's range changes nothing.
- Background: data types follow `subtract_background` (devlog 1.1). A mean projection with rolling ball therefore keeps values below the background as negative numbers; a max projection of an 8-bit or 16-bit image has them set to 0.
- Median filter (`scipy.ndimage.median_filter`, as in the workbook): the data type is kept. Gaussian filter (`scipy.ndimage.gaussian_filter`): whole-number images are turned into 64-bit float first, so that the smoothing is not rounded. With both on, the median runs first.
- The result is not converted to 32-bit float at the end as the workbook does; Cellpose converts its input itself.
- Only an empty setting switches a filter off. A median size or Gaussian sigma of 0 is refused with a plain message, as in the config.

### 2.2 Device, model and segmentation (23 Nov 2026)

- `segmentation.py`, with `cellpose` and `torch` loaded only inside the functions that segment:
  - `choose_device(setting)` gives the device (`cuda`, `mps` or `cpu`), a sentence for the log and a list of warnings. The test calculation is the workbook's (a 256 × 256 matrix of ones multiplied by itself) and also runs for the CPU.
  - `load_cellpose_model(model_name, device, threads=None)` gives the model: `CellposeModel(pretrained_model=..., device=torch.device(...), use_bfloat16=False)`. `threads` sets PyTorch's thread number on the CPU only.
  - `segment_cells(model, image, ...)` gives `masks` (2D, uint32), the model input, Cellpose's flows, the number of cells, the time taken and a warning when there are no cells. `cellpose_eval_settings` takes the seven `eval` settings from the config.
  - `write_label_file(masks, label_folder, image_name)` writes `<image>_seglabels.tif` under the name `<image>_seglabels.tif.tmp` and then renames it.
- Errors: `CellposeSetupError` for what stops a run before processing (device, unknown model, failed download, model that cannot be loaded); `SegmentationError` for one image. A memory error is passed on unchanged, as in the batch runner.
- `tests/cellpose_standin.py`: a stand-in model that returns rectangles as cells and records the settings it was called with, for the tests of 2.4 and 2.5.
- Checks: 37 new tests, 2 of them with the real model; 678 pass without the full-size image. A fresh process that reads a label file has loaded neither `cellpose` nor `torch`.
- Real model on the crop's DAPI channel (384 × 384 px, default pre-treatment), labels of the right form, masks not judged:

| Device | Model load | One image |
|---|---|---|
| Apple GPU | 12 s | 3.2 s the first time, then 2.0 s |
| CPU | 2.8 s | 11 s |

- The first use of PyTorch in a process took 21 s before the device was chosen.
- Repeated runs give identical labels on the Apple GPU and on the CPU (three runs each, no pixel different). The test keeps this check on the device chosen automatically.

Cellpose 4.2.1.1 details:

- An unknown model name is not an error in Cellpose: it logs a warning and loads `cpsam_v2`. The package checks the name itself (a model file, one of Cellpose's models, or a model added in the Cellpose window) and stops with a plain message.
- `device=` overrides `gpu=`, so `gpu=` is not passed. `use_bfloat16` is on by default and is switched off as the spec says.
- A 2D image is passed as it is (32-bit float, `channel_axis=None`); Cellpose adds the channel axis, which gives the same input as the workbook's YXC image with `channel_axis=-1`.
- `eval` removes masks larger than 40% of the image (`max_size_fraction=0.4`). The config has no setting for this, so Cellpose's default applies.
- `eval` returns the flows as a list of three items; the first is the flow picture for the QC figure.
- Each `eval` with the real model gives a PyTorch warning about "sparse invariant checks" from `cellpose/dynamics.py`. It is harmless and shows in the test output.

Choices the spec does not settle:

- Warnings are returned to the caller, which logs them, as `choose_workers` and decomposition do.
- A model name that is a path must be an existing file. When a known model has no file in Cellpose's model folder and loading fails, the message says it could not be downloaded; when the file is there, it says the model could not be loaded and to delete the file so that it is downloaded again.
- GPU memory that PyTorch keeps in reserve is handed back after every image (`torch.mps.empty_cache()` or `torch.cuda.empty_cache()`). Task 2.7 measures memory over five images.

For 2.4: the runner's one-line error text does not yet know the two new error types, and the PyTorch warning above should not reach `run.log` once per image.

### 2.6 Rolling ball against top-hat (23 Nov 2026)

The two background methods at 5 px on the full-size image (exon channel 2, intron channel 3) and on the crop (exon channel 2; it has no intron channel). Everything else is the v1 reference settings with run seed 0: decomposition alpha 0.5 and beta 1, clusters of 12 spots within 600 nm, subpixel fitting off. The manual threshold is 18 for the exon channel and 30 for the intron channel, as in the reference config; the intron channel was also counted at 18. Scripts, logs and tables are in `~/bigfish-testdata/phase2/` (see its `README.md`).

TH is top-hat, RB is rolling ball.

| Image, channel | Automatic threshold TH / RB | Threshold used | Detected TH / RB | After decomposition TH / RB | Clusters TH / RB |
|---|---|---|---|---|---|
| Crop, exon | 13 / 12 | 18 | 473 / 440 | 692 / 664 | 6 / 5 |
| | | each method's automatic | 610 / 601 | 869 / 868 | 6 / 7 |
| Full size, exon | 15 / 13 | 18 | 24,631 / 23,680 | 36,360 / 37,126 | 199 / 273 |
| | | each method's automatic | 27,514 / 28,199 | 41,249 / 43,925 | 246 / 308 |
| Full size, intron | 23 / 22 | 30 | 1,143 / 1,131 | 1,526 / 1,532 | 0 / 0 |
| | | 18 | 3,143 / 2,612 | 6,365 / 4,725 | 22 / 4 |
| | | each method's automatic | 1,643 / 1,654 | 2,404 / 2,462 | 0 / 0 |

**Thresholds.** The automatic threshold is 1 to 2 lower with rolling ball. To detect the same number of spots as top-hat at the manual threshold, rolling ball needs 17 instead of 18 on the exon channel (crop: 464 against 473; full size: 24,623 against 24,631). On the intron channel 30 stays the nearest (1,131 against 1,143). Thresholds are whole numbers here, because the LoG-filtered image is a 16-bit image.

**Run-to-run range** (run seeds 0 to 5, full-size exon channel at 18; devlog 1.14):

| | Spots after decomposition | Clusters |
|---|---|---|
| Top-hat | 36,360 to 37,126 | 197 to 212 |
| Rolling ball | 36,505 to 37,126 | 258 to 273 |

- The difference in spots after decomposition (+766 with rolling ball at seed 0) is as large as the top-hat range itself, so it is not a clear difference.
- The difference in clusters is clear: the two ranges do not overlap, and rolling ball gives about a third more clusters (273 against 199; 4,557 against 3,077 spots in clusters). With each method's automatic threshold it is 308 against 246.
- The intron channel at 30 and the crop have fewer than 2,000 spots, so no random choice is made and their differences are exact. The range was not measured for the intron channel at 18 or for the automatic thresholds on the full-size image.

**Same spots.** Two spots count as the same when they are at most 1 px apart in each of Z, Y and X; each spot is paired once.

| Comparison | Both | Top-hat only | Rolling ball only |
|---|---|---|---|
| Crop, detected at 18 | 439 | 34 | 1 |
| Crop, detected, TH at 18 and RB at 17 | 459 | 14 | 5 |
| Crop, after decomposition at 18 | 636 | 56 | 28 |
| Full-size exon, detected at 18 | 23,516 | 1,115 | 164 |
| Full-size exon, detected at each automatic threshold | 27,090 | 424 | 1,109 |
| Full-size exon, detected, TH at 18 and RB at 17 | 24,153 | 478 | 470 |
| Full-size exon, after decomposition at 18 | 34,349 | 2,011 | 2,777 |
| Full-size intron, detected at 30 | 1,104 | 39 | 27 |
| Full-size intron, detected at 18 | 2,514 | 629 | 98 |

At the same threshold the spots found by one method only are mostly top-hat spots. When rolling ball is given the threshold that matches the count, 98 % of the spots are shared and the rest split evenly.

**Per-cell counts on the crop** (44 nuclei of the label image, spots after decomposition): at 18 the totals are 413 with top-hat and 396 with rolling ball (r = 0.990; largest difference 4 spots, cell 11 with 28 and 24); at each method's automatic threshold 510 and 514 (r = 0.996; largest difference 2 spots). The median difference per cell is 0.

**Other numbers.** Rolling ball sets 36 to 38 % of the pixels to 0 and top-hat about 5 %. At the centre of the spots detected on the full-size exon channel, the raw intensity is the same for both methods (median 195 and 196), and the intensity after background subtraction is lower with rolling ball (median 69 against 80). Decomposition works on the image after background subtraction, so its reference spot differs between the methods; see "Where the extra clusters come from" below. A full-size channel took 46 to 50 s to filter with top-hat and 60 s with rolling ball.

**Figures** (image panels come from the crop only):

- Elbow curves of both methods: [crop](figures/phase2/elbow_crop_ch2.png), [full-size exon](figures/phase2/elbow_full_ch2.png), [full-size intron](figures/phase2/elbow_full_ch3.png).
- Spot intensities, raw and after background subtraction: [crop](figures/phase2/spot-intensities_crop_ch2.png), [full-size exon](figures/phase2/spot-intensities_full_ch2.png), [full-size intron](figures/phase2/spot-intensities_full_ch3.png).
- [Examples from the crop](figures/phase2/crop-examples_raw-background-spots.png): a sparse region, a dense region and the edge of a nucleus, with the raw image, each background result and the spots found with each ([where the regions are](figures/phase2/crop-examples_where.png)).
- [Spots per cell on the crop](figures/phase2/per-cell-counts_crop_ch2.png), top-hat against rolling ball.

**Checked by the orchestrator.** `bigfish-pypeline batch` on the test kit with each method gave the same counts as the table (473 / 440 detected, 692 / 664 spots, 6 / 5 clusters at 18; 601, 868 and 7 for rolling ball at its automatic threshold), the same per-cell totals (413 / 396) and, with a separate matching script, the same shared spots after decomposition (636, 56 and 28). A batch run of the full-size exon channel with rolling ball gave 23,680 detected spots, 37,126 spots and 273 clusters, as in the table. The top-hat numbers are those of devlog 1.5 and 1.14.

**Where the extra clusters come from** (asked for by the user; full-size exon channel at 18; script `clusters.py` in `~/bigfish-testdata/phase2/`).

They come from decomposition on the rolling ball image, not from which spots are detected. With the detected spots of one method decomposed on the image of the other, over seeds 0 to 5:

| Detected spots from | Image for decomposition | Spots after decomposition | Clusters |
|---|---|---|---|
| Top-hat | Top-hat | 36,360 to 37,126 | 197 to 212 |
| Rolling ball | Top-hat | 35,232 to 35,553 | 185 to 198 |
| Top-hat | Rolling ball | 37,946 to 38,546 | 268 to 284 |
| Rolling ball | Rolling ball | 36,505 to 37,126 | 258 to 273 |

- **Same places, more spots in each.** At seed 0, 197 of the 199 top-hat clusters are also found with rolling ball (centres within 600 nm). In these the median is 15 spots with top-hat and 18 with rolling ball; rolling ball has more spots in 172 of them. Of the 76 clusters found with rolling ball only, 73 are places where top-hat has 8 to 11 spots within 600 nm, just under the limit of 12. The other seeds give the same picture (51 to 76 rolling-ball-only clusters, nearly all at 8 to 11 top-hat spots).
- **Clusters here are made by decomposition.** Nearly every spot in a cluster was placed by decomposition in a dense region; only about 2 detected spots lie within 600 nm of a cluster centre.
- **The spot limit.** Rolling ball at `min_spots` 12 (273 clusters) lies between top-hat at 11 (241) and at 10 (307). Rolling ball at 13 gives 229 and at 14 gives 182, on either side of top-hat at 12 (199).
- **A matched threshold does not remove it.** Top-hat at 18 against rolling ball at 17 (the same number of detected spots): 199 against 283 clusters.
- **The places are not dim.** At the rolling-ball-only clusters the brightest raw value nearby is 463 (median), against 562 at the shared clusters, and both methods leave them about as bright (332 after top-hat, 323 after rolling ball).

How big-fish counts the spots of a dense region: it builds a reference spot (the median of up to 2,000 detected spots, on a copy of the background-subtracted image with a wide blur removed), takes as dense regions the connected pixels brighter than the reference spot's peak, and places copies of the reference spot in each region one at a time until one more no longer improves the fit. The number of spots therefore depends on how much light a region holds compared with one reference spot.

Likely reason, which fits the numbers but was not tested directly: the reference spot is smaller and slightly dimmer on the rolling ball image (width 254 nm in Z and 94 nm in YX against 271 and 100 nm; amplitude 61.8 against 62.9), so one reference spot holds about 18 % less light, while the dense regions themselves are only a few per cent dimmer. The same region is then split into about 1.2 times as many spots, which matches the rise from 15 to 18. The lower limit for a dense region (60 against 64 grey levels) adds a little (10,846 against 10,521 regions).

Not settled: which count is nearer the truth. The numbers show that the number of spots given to a bright focus depends on the size of the reference spot, which the background method changes, so the same `min_spots` stands for a slightly different amount of RNA with each method. This is one image and one channel; the intron channel at 30 has no clusters with either method.

Figures: [clusters for the four combinations](figures/phase2/clusters-detection-vs-image_full_ch2.png), [spots per cluster with each method](figures/phase2/spots-per-cluster_full_ch2.png), [clusters against the spot limit](figures/phase2/clusters-vs-min-spots_full_ch2.png).

Checked by the orchestrator with a separate script: pairing the cluster tables of the two batch runs gives 197 shared, 2 top-hat only and 76 rolling ball only, with medians of 15 and 18 spots; `detect_clusters` on the runs' spot tables gives 307, 241 and 199 clusters for top-hat at 10, 11 and 12, and 273, 229 and 182 for rolling ball at 12, 13 and 14; top-hat spots decomposed on the rolling ball image give 38,115 spots and 268 clusters, and the reverse 35,489 and 194.

**Decision by the user (23 Nov 2026):** the comparison is reviewed and rolling ball stays the default background method for FISH channels. For the documentation (Phase 6): a manual threshold and a `min_spots` value chosen with top-hat do not carry over unchanged to rolling ball (here 18 became 17, and 12 spots became 13 to 14).

### 2.3 Cellpose QC figure (23 Nov 2026)

- `qc.py` (new): `write_cellpose_qc(run_folder, image_name, segmentation, channel, pretreatment, diameter, channel_name=None)` writes `qc/<image>_cellpose_qc.png` from the result of `segment_cells`, under a temporary name first. `draw_cellpose_qc` gives the figure without saving it, `cellpose_qc_title` the title text, and `cellpose_qc_path` the file's path.
- Four panels as in the workbook's `qc_figure`, drawn by Cellpose's `show_segmentation`: input (contrast stretched between the 1st and 99th percentile for display only), outlines, masks and flows.
- Title, e.g. "sypN_DAPI_Phal_jim-exon_crop | channel 0 (DAPI) | max projection | rolling ball 200 px | diameter chosen by Cellpose | 43 cells | 2.1 s". The projection and pre-treatment come from `describe_pretreatment`. A title longer than 150 characters continues on a new line.
- The figure is made without `matplotlib.pyplot` and without a screen, so it can be written from any thread and does not change the matplotlib backend of a notebook or the app. `cellpose` is loaded only when the figure is drawn.
- Checks: 20 new tests (cells and no cells, each title item, a thread that is not the main one, a process without a display, no `cellpose` or `torch` loaded by importing `qc.py`); 698 pass without the full-size image.

Choices the spec does not settle:

- The channel's name is shown after its number when it is given.
- A diameter left empty in the config reads "diameter chosen by Cellpose".
- The figure is 18 inches wide at 150 dots per inch (2,700 px, as the workbook saves it); its height follows the shape of the image.
- Cellpose's own panel titles are kept ("original image", "predicted outlines", "predicted masks", "predicted cell pose").
- The colours of the masks panel differ from run to run, because Cellpose picks them at random.

Loading `cellpose.plot` also loads `matplotlib.pyplot` (through `cellpose/io.py`), without making a figure or changing the backend.

### 2.4 Segmentation in the batch runner (23 Nov 2026)

`source: cellpose` now runs in `bigfish-pypeline batch`.

- **Before processing** (`prepare_cellpose` in `batch.py`): the segmentation channel is checked against the first image, the device is chosen and tested, and the model is loaded once. This happens before the run folder is made, so a problem (unknown model, device that does not work) leaves no folder. `bigfish-pypeline check` checks the channel only: it does not test the device or load the model, and does not load PyTorch (its first load takes about 20 s).
- **Run flow.** The main process segments in one background thread, one image at a time and in order: it reads only the segmentation channel (local file, or OMERO through the main connection with the existing retry), pre-treats it, segments it, writes the label file and the QC figure, and hands the image to a worker when one is free. The next image is segmented only when no segmented image is waiting for a worker. The main loop keeps its 1 s rhythm throughout: cancel, `progress.json` (new entry `segmenting`) and finished images.
- **Cancel during a segmentation.** Cellpose cannot be stopped part way through an image, so the segmentation is abandoned: its thread writes nothing more, the image's label file and QC figure are removed, and the command returns. Ctrl+C during a segmentation on the CPU returned after 1.1 s. The abandoned thread uses the processor and holds the model until that one image is done, which matters for the app (Phase 5): a new run started at once could hold two copies of the model for a short time.
- **Label files.** With `outputs.label_images` on they go to `labels/` in the run folder; with it off to `labels_temporary/`, where each file is deleted as its image finishes and the folder is removed at the end, also after a cancel or a stop. Labels and QC figures are kept only for finished images. An image retried after a stopped worker keeps its label file and is not segmented again.
- **Failures.** A segmentation that fails (also an unreadable segmentation channel) leaves the image's spots: `segmentation_status` is `failed`, the channels stay `done`, and the reason is in the `warnings` column ("no cell results: segmentation failed: ...") and in `run.log`. No cells: `segmentation_status` `done`, `n_cells` 0 and a warning. A QC figure that cannot be written gives a warning only.
- **Log.** `run.log` names the model, the channel, the pre-treatment, the device (with the CPU warning and the number of threads) and where the labels go, and gives for each image the segmentation time and the number of cells. The PyTorch "sparse invariant checks" warning is hidden (only that warning, from `cellpose.dynamics`).
- **End of the run.** The model is let go and the GPU memory handed back.
- Checks: 25 new tests in `tests/test_batch_cellpose.py`, one with the real model; 723 pass without the full-size image. With the stand-in model: the test kit with one and two workers gives the same tables; its `labels/` folder reused as label files gives the same spot, cluster and cell tables; `outputs.label_images` off; cancel during a segmentation (cancel file and Ctrl+C); `progress.json` renewed during a long segmentation; a stopped worker; a failed segmentation; no cells; set-up problems; OMERO input with stand-ins for the server; a fresh process that runs with label files loads neither `cellpose` nor `torch`.
- Checked by the orchestrator with the real command on the test kit: Apple GPU, 14 s for the whole command (model ready in 4.9 s, segmentation 2.2 s); CPU with four threads and `label_images` off, 22 s (segmentation 12.2 s), no label folder left; an unknown model name stops with the plain message and no run folder. Both runs: 692 spots, 6 clusters, 43 cells.

**Threads on the CPU.** When PyTorch is first loaded while `OMP_NUM_THREADS` is 1, it stays on one thread whatever it is told later: `torch.set_num_threads(4)` then reports 4 but the work runs on one. The runner therefore sets the thread variables to the Cellpose thread number while it tests the device and loads the model, and to 1 for the workers afterwards. A test with the real PyTorch checks both orders and that the work really runs in parallel. For the app (Phase 5): PyTorch must not be loaded for the first time while the thread variables are 1. Segmentation of the crop on the CPU through the runner took 37.7 s with one thread, 11.5 s with four and 8.9 s with eight.

First estimates, to be replaced by the figures of 2.7:

- `CELLPOSE_CPU_THREADS = 4` (fewer on a computer with fewer cores). With `workers: auto` on the CPU these threads run beside the workers, so the processor is asked for more than it has; 2.7 decides which of the two should give way.
- `CELLPOSE_MEMORY_RESERVE = 3 GB`, on top of the 2 GB kept free without Cellpose. The reason logged for `workers: auto` names it.

Choices the spec does not settle:

- The reason for a failed segmentation goes into the `warnings` column, because the `reason` column belongs to the channel's own status.
- Segmentation starts with the main pass, not during the calibration pass.
- A memory error during a segmentation fails that image only.
- `run_config.yaml` of a Cellpose run keeps the `segmentation.label_folder` of the config, which is not used.
- The line "Getting Cellpose ready: testing the device and loading the model..." is shown in the terminal only, because `run.log` does not exist yet.

Seen, not part of this task: big-fish's `FutureWarning` about `mean_intensity` is printed in the terminal once per run by a worker (there since Phase 1).

### OMERO check on the lab server (23 Nov 2026)

The user ran `tests/manual/omero_session_check.py --image-id 5806` on the lab server over the VPN (manual check 1 of the Phase 1 review). All six steps passed:

- the main process logged in and read the image information;
- two helper processes joined the login, each read channel 0 (35 × 2048 × 2048, 16-bit) and left;
- the main login still worked after the helpers had left, and again 5 seconds later.

This confirms two of the three points left open in 1.13: a joined worker can read images, and leaving with `close(hard=False)` keeps the main login alive. Still open: which errors a dropped connection and an ended session really raise.

Seen in the output:

- Image 5806 is the full-size test image, so an OMERO run can be compared with the local runs.
- Reading one channel took 50 s in each helper, with both reading at once over the VPN. A local file is read in a few seconds, so reading will take most of the time of an OMERO run from outside the lab network.
- OMERO holds no Z voxel size for this image (65 nm in Y and X), so the config's Z value cannot be checked against it.
- The image's name on OMERO ends in `.tiff`, and the output name keeps it: `5806_20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001.tiff`. Tables and label files of this image would be named `5806_..._00001.tiff_spots.csv` and `5806_..._00001.tiff_seglabels.tif`. The spec says `<image ID>_<image name>` and does not mention the extension. Question for the user.
- `get_omero_image` in `omero_tools.py` prints "Fetching ...", "Image fetched from OMERO in ... sec" and the image shape for every read. The file stays unchanged until Phase 8.

Next: a small real OMERO batch with Cellpose on. A config for image 5806 is in `~/bigfish-testdata/phase2/omero/omero_batch.yaml` (rolling ball at 5 px, manual threshold 18, one worker); the user adds a second image ID and runs it.

**Decision by the user (23 Nov 2026): the extension is dropped from OMERO output names.** `omero_output_name` leaves out a `.tif` or `.tiff` at the end of the image name (in any letter case), so image 5806 gives `5806_20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001`. This is a deviation from spec 5.3 and 8.2, which give `<image ID>_<image name>`.

- The rule is the one for local files: `image.ome.tif` gives `image.ome` locally and `12_image.ome` on OMERO.
- Other endings, such as `.czi`, are kept, because cutting at any dot would damage names like `cell 1.5 uM`.
- Label files for OMERO images are therefore named `<image ID>_<image name without .tif>_seglabels.tif`.
- Checks: the expected names in the OMERO tests were updated, with new cases for `.tiff`, `.TIF`, `.ome.tif`, a name with a dot and no extension, and `.czi`; 730 tests pass without the full-size image.

### Real OMERO batch with Cellpose (23 Nov 2026)

The user ran `bigfish-pypeline batch` on OMERO images 5806 and 5795 over the VPN, with Cellpose on the Apple GPU, rolling ball at 5 px, manual threshold 18 and one worker (config `~/bigfish-testdata/phase2/omero/omero_batch.yaml`, run folder `~/bigfish-testdata/phase2/omero/runs/2026-11-23_1751_omero_batch`). The VPN was unstable, and OMERO testing stops here at the user's request.

- **Image 5806 finished and agrees with the local runs:** 23,680 spots detected on the exon channel, exactly as the local rolling ball run; 36,570 spots after decomposition and 258 clusters, inside the ranges of the local runs (36,505 to 37,126 and 258 to 273; the seed depends on the output name, which differs from the local one). Tables, label file and QC figure were written under the new output name without `.tiff`.
- **The whole path worked on a real server:** login, the model loaded before the run folder was made, the main process reading the segmentation channel, a worker joining the login and reading the FISH channel, and segmentation of the second image overlapping with detection of the first.
- **Times:** reading one channel took 23 to 45 s; Cellpose-SAM on a 2048 × 2048 projection took 48.5 and 49.6 s on the Apple GPU, with 5.3 GB of memory free. The run took 3 min 42 s.
- **Image 5795 failed when the connection dropped:** it was segmented, then its worker lost the connection ("lost the connection to OMERO (ConnectionLostException: Ice.ConnectionLostException:)"). The run went on and ended normally, with the failure in `images.csv` and `run.log`. This answers the last open point of 1.13 for a dropped connection: it raises `Ice.ConnectionLostException`, which the code recognises. An ended session was not seen.

Defects found, fixed in the next entry:

1. **No second try.** The connection was lost while the worker read the image information (`get_omero_image_info`), which is not retried; only the reading of channels rejoins the session and tries again. Spec 7.3 asks for one retry after rejoining for a dropped connection.
2. **The session key was printed in the terminal.** omero-py logged the lost connection as a warning with its own traceback, and that text holds the session key. `run.log` and the tables do not contain it (checked). Devlog 1.13 switched off omero-py's INFO and DEBUG messages; its warnings and errors need the same care. The session of this run is closed.
3. **Other lines in the terminal that are not the runner's:** "WARNING:cellpose.vit:Could not import CPDINO ..." when the model loads, and "WARNING:omero.client:Cannot get session service for killSession ..." at the end.

Left as they are: the "Fetching ..." lines printed by `omero_tools.py` (unchanged until Phase 8), and big-fish's `FutureWarning` (there since Phase 1).

### OMERO fix: second try and a clean terminal (23 Nov 2026)

The three defects of the real OMERO batch are fixed. Tested with stand-ins for the server only: the VPN stays off today, so the check on the real server is a manual check of the phase review.

1. **Second try.** One reader (`OmeroImageReader` in `io.py`) now reads the image information and every channel of an image. If the connection drops during any of these reads, the session is rejoined once and the read is tried again; a second drop for the same image marks it failed ("lost the connection to OMERO twice"). The workers, the calibration pass and the main process's reading of the segmentation channel all use it. `run.log` and the terminal get a plain line: "OMERO image 5795: lost the connection to OMERO (...); rejoining the session and trying again".
2. **Session key.** Nothing omero-py logs is shown or written any more, at any level (before: INFO and DEBUG only). A lost connection is reported by the runner itself, with the key removed.
3. **Other lines.** omero-py calls `logging.basicConfig()` each time it makes a connection, which changes how the warnings of every other package are shown; this is where "WARNING:cellpose.vit:..." came from. During `check`, `batch` and in each worker, the runner now prevents this and leaves the program's logging as it found it afterwards. The "killSession" line is one of omero-py's own messages and is gone with point 2.

- After a failed rejoin (server not reachable), the image fails and the next image tries to join again. An ended session still stops the run with the message to log in again.
- If the main process rejoined the session during a run it logged in to, it ends the session at the end through the new connection.
- Checks: 22 new tests, 752 pass without the full-size image. They cover a drop while the information is read and while a channel is read, in a worker, in calibration and in the main process; two drops for one image; an ended session; a server that cannot be reached; and the terminal output of a run in a fresh process, with omero-py's messages (session key included) logged as omero-py logs them.
- Checked by the orchestrator with the real command on the test kit with Cellpose (local files): the terminal shows the runner's lines only, apart from big-fish's `FutureWarning`; 692 spots, 6 clusters and 43 cells, as in 2.4.

Choices the spec does not settle:

- One second try per image and per process: the main process (segmentation channel) and the worker each have their own for the same image.
- omero-py's warnings and errors are dropped rather than rewritten, because their text cannot be trusted to leave out the key.

Known limit, carried to Phase 5 with the keep-alive point of 1.13: once the main process has rejoined the session, its keep-alive (every 60 s, from `connect_to_omero`) no longer reaches the server, so the session stays alive only through the reads of the run. A pause of more than the server's idle time (10 minutes by default) with no read would end the session. This was already so before the fix.

Manual checks on the real server, for the phase review: the batch of images 5806 and 5795 finishes; a dropped connection gives the "rejoining" line and the image finishes; no session key and no `WARNING:` lines in the terminal.

### Mask size limit for Cellpose (23 Nov 2026)

**Decision by the user (23 Nov 2026): the config gets a setting for Cellpose's mask size limit.** Cellpose removes every mask larger than a fraction of the image (devlog 2.2); the fraction was fixed at Cellpose's default of 0.4.

- New setting `segmentation.cellpose.max_size_fraction`, default 0.4, so results do not change. It is passed to Cellpose's `eval` unchanged.
- Accepted values: above 0 and up to 1. With 1, no mask is removed for its size. Any other value gives the message "`segmentation.cellpose.max_size_fraction` must be a number above 0 and up to 1".
- The fraction is of the whole image, so the same value allows larger cells in a larger image. A crop that holds one large cell may need a higher value than the full image.
- This is an addition to spec 5.7 and to the config layout of spec 6.2, which name seven `eval` settings; there are now eight. The test kit config lists the new setting.
- Checks: the setting reaches `eval` (stand-in model); values in and out of range; with the real model on the crop, a limit halfway between the smallest and the largest cell removes exactly the cells above it and leaves valid labels.

For the Optimise notebook (Phase 4) and the app (Phase 5): the setting belongs with the other Cellpose settings.

### 2.5 End-to-end tests with Cellpose (23 Nov 2026)

`tests/test_end_to_end_cellpose.py`: 11 tests in about 60 s, two of them with the real model. No defect was found in the package, and no processes are left behind.

| Case | Result |
|---|---|
| `bigfish-pypeline batch` on the test kit with `source: cellpose` (real model, device chosen automatically) | exit code 0; tables written; the label file is 2D, whole numbers and the image's size; the cells table agrees with the label file; QC figure written; `run.log` names the model and the device |
| The same with `device: cpu` (no GPU) | the run finishes, with the warning about time in `run.log` (about 21 s) |
| Three images of different sizes, 2 workers | each label file has its own image's size; every spot's `cell_id` is the label at its position |
| 2D images (`YX`, `CYX`) | Cellpose gets the 2D image; no Z columns |
| No cells in one image and a failed segmentation in another, with `outputs.label_images` on and off | the other images are not affected; every image keeps its spots; statuses and warnings as in 2.4; no label file or QC figure for the failed image; no label folder when `label_images` is off |
| Cancel while workers are processing, with `label_images` on and off | status `cancelled`; tables, `per_image/`, label files and QC figures hold exactly the finished images; no temporary files |
| Repeat from `run_config.yaml` | same tables and label images |
| The first run's `labels/` folder used as label files | same spots, clusters and cells tables |

- All but the first two cases use the stand-in model with the real pipeline for the spots, on generated images.
- Already covered by the tests of 2.4 and not repeated: cancel during a segmentation (cancel file and Ctrl+C), `label_images` off on the test kit, a stopped worker.
- Checks: 771 tests pass without the full-size image (5 min 40 s).

Choice the spec does not settle: an image with no cells still gets its label file (all zero) and its QC figure.

Seen: on import, Cellpose adds lines to its own log file, `~/.cellpose/run.log`, also during the tests with the real model.

### 2.7 Benchmarks on the full-size image (23 Nov 2026)

Scripts, raw logs, `benchmarks.csv` and `conditions.txt` are in `~/bigfish-testdata/benchmarks/phase2/`.

Conditions: `bigfish-msp` (Python 3.12.16, numpy 2.5.5, scipy 1.18.1, scikit-image 0.26.0, big-fish 0.6.2.post1, PyTorch 2.14.1, Cellpose 4.2.1.1), on the laptop (M1 Pro, 10 cores, 17 GB). Full-size image, 35 × 2048 × 2048 per channel; rolling ball at 5 px; exon channel 2 at threshold 18, intron channel 3 at threshold 30; every step switched on (decomposition, subpixel fitting, clusters, SNR, intensity, cell assignment). One measurement at a time, a new process for each. Memory is the process's physical footprint, as in 0.10. Before each measurement 6.2 to 7.4 GB of memory was available; other programs were open.

**Rolling ball through the package** (3 repeats)

| What | Time, median (range) | Peak memory |
|---|---|---|
| Channel 2, 35 planes, 5 px | 42.1 s (41.8–42.2) | 0.95 GB |
| Channel 3, 35 planes, 5 px | 42.1 s (42.1–42.3) | 0.95 GB |
| DAPI max projection, 200 px | 0.48 s (0.48–0.49) | 0.37 GB, with reading the channel |

The time for a FISH channel is that of 0.10 (42.0 s).

**Cellpose-SAM on the 2048 × 2048 DAPI projection** (default pre-treatment; 1,287 cells every time, on both devices; masks not judged)

| Device | Getting ready (PyTorch, device test, model) | One image | Peak memory | Held between images |
|---|---|---|---|---|
| Apple GPU | 4.8–5.5 s | 47.4 s the first, then 46.6 and 46.9 s | 4.4 GB, during the first image | 2.6–2.7 GB |
| CPU, 1 thread | 4.2 s | 993 s | 2.9 GB, while the model loads | 1.6 GB |
| CPU, 4 threads | 4.3 s | 304 s | 2.9 GB | 1.6 GB |
| CPU, 8 threads | 4.4 s | 218 s | 2.9 GB | 1.6 GB |

- Five images in a row on the Apple GPU: 3.66, 2.60, 2.62, 2.63 and 2.65 GB held after each image, and 48.9 to 49.5 s per image. Memory does not grow.
- The higher memory during the first image on the GPU is memory the graphics driver keeps from loading the model (3.1 GB, then 2.1 GB from the second image on).
- On the CPU, four threads are 3.3 times faster than one and eight threads 4.6 times; from four to eight the gain is 1.4 times.
- The first load of PyTorch in a process took about 1 s here, not the 21 s seen in 2.2.

**One worker, every step on** (`process_image` in a new process, with the Cellpose label file)

| Channels | Time | Peak memory | Bytes per voxel of one channel |
|---|---|---|---|
| 2 | 294 s | 5.49 GB | 37.4 |
| 2, then 3 | 376 s (296 s and 80 s) | 5.50 GB | 37.5 |

- Channel 2: 23,680 spots detected, 37,126 after decomposition, 271 clusters, 1,287 cells. Channel 3 is quick because it has few spots (1,532).
- A second channel does not raise the peak.
- The peak is 0.7 GB above the 4.8 GB of 0.10, which measured the v1 steps only. Which of the added steps accounts for it was not measured.

**Whole runs of `bigfish-pypeline batch` with Cellpose** (three copies of the image, channel 2, one worker)

| Run | Total time | Main process, peak | Main process while a worker runs | Worker, peak | Highest sum at one moment |
|---|---|---|---|---|---|
| Apple GPU | 16 min 0 s | 4.3 GB | 2.7–2.9 GB | 5.52 GB | 8.45 GB |
| CPU, 4 threads | 21 min 15 s | 2.9 GB | 1.7–2.0 GB | 5.51 GB | 7.51 GB |

- The main process's peak comes before the first worker starts (model loading, first segmentation), so it does not add to the workers' peak.
- With Cellpose on the GPU the worker took 296–297 s per image against 291 s alone (2 % slower). With Cellpose on the CPU beside it, the worker took 320–326 s against 289 s alone (10–13 % slower), and Cellpose 315–318 s against 299 s alone (5–6 % slower).
- On the CPU with four threads, a segmentation (about 300 s) takes as long as one channel in a worker with subpixel fitting on (about 290 s), so one worker is not kept waiting.
- Available memory fell to 2.4 GB (GPU run) and 2.8 GB (CPU run) for a short time and swap in use rose from 3.7 to 6.1 GB; the workers' times were not affected.
- A run with two workers was not made: it needs about 11 GB available, and 7.3 GB was.
- `workers: auto` on this laptop with 7.3 GB available: one worker with the warning about little memory when Cellpose is on (room for none after the 5 GB kept free), and one worker without Cellpose.

Checked by the orchestrator against the logs: the worker's peak and bytes per voxel, the CPU time with four threads, the memory over five images, and the times and highest sums of both whole runs.

**What this means for `workers: auto`**

- Memory per worker: the estimate of 35 bytes per voxel (5.1 GB for this image) is about 7 % under the 5.5 GB measured in four runs that agree within 0.03 GB.
- Memory kept free for Cellpose: the main process holds 2.6–2.9 GB with the GPU and 1.7–2.0 GB with the CPU while workers run, of which about 0.15 GB is there without Cellpose. The 3 GB kept free covers both.
- Threads for Cellpose on the CPU: four give most of the gain, and cost a worker beside them 10–13 %.

**Proposed final figures, for the user to agree**

1. Memory per worker: 38 bytes per voxel of one channel (5.6 GB for this image) in place of 35.
2. Memory kept free: 2 GB, and 3 GB more with Cellpose, unchanged.
3. Cellpose on the CPU: 4 threads, unchanged. With `workers: auto`, the workers give way: the number of cores counted for workers is the cores less the Cellpose threads, in place of the cores less one. Not measured with several workers.

**Decisions by the user (23 Nov 2026): the three proposed figures are agreed.**

- `BYTES_PER_VOXEL_PER_WORKER` is 38: 5.6 GB for a 2048 × 2048 × 35 channel and 4.8 GB for 30 planes. Spec 7.2 expected 3–4 GB for 30 planes; this replaces deviation 1 of the Phase 1 review (5 GB).
- `MEMORY_RESERVE` stays 2 GB and `CELLPOSE_MEMORY_RESERVE` 3 GB.
- `CELLPOSE_CPU_THREADS` stays 4. When Cellpose runs on the CPU, `workers: auto` counts the cores less the Cellpose threads for workers (6 of 10 cores), and at least one. The log line says "4 left for Cellpose on the CPU".
- With `device: auto` the device is chosen after the workers are counted (the count is part of `check`, which does not load PyTorch). If the CPU is then chosen, the run lowers the number and adds to the `Workers:` line "lowered to N because Cellpose runs on the CPU with 4 thread(s)". `bigfish-pypeline check` shows the number before this; with `device: cpu` in the settings file it is right from the start.
- A number of workers set in the config is not changed.
- On a 16 GB laptop, one worker beside Cellpose now needs 10.6 GB available to run without the "little memory" warning, so the warning will be usual there. Both whole runs finished at 7.3 GB available without trouble.
- Checks: 4 new tests, 775 pass without the full-size image.

To be checked again in Phase 3, when the QC figures are added to the workers.

### 2.8 Phase 2 review (24 Nov 2026)

Checks run in a fresh shell:

| Check | Result |
|---|---|
| `conda run -n bigfish-msp python -m pytest` (whole suite, with the full-size image) | 778 passed in 7 min 54 s |
| The same without the full-size image (`-m "not full_image"`) | 775 passed in 5 min 41 s |
| The same without the tests that need the Cellpose model (`-m "not cellpose and not full_image"`), as on a computer without the model | 769 passed in 5 min 3 s |
| v1 imports in the main env (`image_utils`, `omero_tools` from `src/`, Python 3.9, Cellpose 3.1.1.2) | work as before |
| Main env | `conda env export` identical to the export stored with the reference run |
| v1 files (`environment.yml`, `image_utils.py`, `omero_tools.py`) | unchanged since `v1.0` |
| Worker processes left after the tests | none |

Phase 2 "done when" (spec section 11, with the plan's additions):

| Condition | Result | Entry |
|---|---|---|
| The package tests pass | yes, see above | – |
| The rolling ball comparison is reviewed by the user | reviewed; rolling ball stays the default for FISH channels | 2.6 |
| The benchmarks are in the devlog | yes | 2.7 |
| The final `workers: auto` figures are agreed | agreed by the user | 2.7 |

Still open, and not part of "done when": the Cellpose 4 mask review on an image the user supplies (spec, comparison 2; before Phase 8), and the OMERO fix tried on the real server.

**What Phase 2 delivered**

- `source: cellpose` in `bigfish-pypeline batch`, for local folders and OMERO: pre-treatment of the segmentation channel, the device chosen and tested, the model loaded once, one image segmented at a time in the main process while the workers go on, label files in `labels/` and the four-panel QC figure in `qc/`.
- `segmentation.py` with Cellpose 4 and the new `qc.py`: 7,060 lines in `src/bigfish_pypeline/`, 778 tests.
- On the full-size image: Cellpose-SAM takes about 48 s on the Apple GPU and about 5 min on the CPU with four threads; a batch of three images with every step on took 16 min with the GPU.
- OMERO tried on the lab server: the shared login works, and image 5806 gives the results of the local runs.
- The comparison of rolling ball and top-hat, with figures, and the reason for the extra clusters with rolling ball.

**Deviations from the spec and the plan**

| # | Deviation | Entry |
|---|---|---|
| 1 | `workers: auto` uses 38 bytes per voxel of one channel for each worker: 5.6 GB for 35 planes and 4.8 GB for 30, not 3–4 GB. User's decision. Replaces deviation 1 of the Phase 1 review. | 2.7 |
| 2 | With Cellpose on the CPU, `workers: auto` leaves four cores to Cellpose. With `device: auto` the number is lowered after the device is chosen, so `check` can show a higher number than the run uses. User's decision. | 2.7 |
| 3 | New setting `segmentation.cellpose.max_size_fraction` (default 0.4), not in spec 5.7 or 6.2. User's decision. | Mask size limit |
| 4 | OMERO output names leave out a `.tif` or `.tiff` ending. User's decision. | OMERO check |
| 5 | Label files given by the user are not copied into the run folder; `outputs.label_images` applies to Cellpose labels only. User's decision. | 2.0 |
| 6 | With `device: auto`, a device that fails its test is passed over for the next one with a warning; a device named in the config that fails stops the run. User's decision. | 2.0 |
| 7 | An unknown Cellpose model name stops the run with a plain message; Cellpose itself would load `cpsam_v2` without saying so. | 2.2 |
| 8 | The reason for a failed segmentation is in the `warnings` column, not in `reason`. | 2.4 |
| 9 | A segmentation under way when a run is cancelled cannot be stopped: it is abandoned and writes nothing more, but uses the processor until that image is done. | 2.4 |
| 10 | Nothing omero-py logs is shown or written, at any level, because its messages can hold the session key. | OMERO fix |
| 11 | After a dropped OMERO connection, the main process and a worker each have their own second try for the same image. | OMERO fix |
| 12 | A whole run with two workers was not measured, because the laptop did not have the 11 GB of available memory it needs. | 2.7 |
| 13 | The mask size limit and the change to the workers estimate were written by the orchestrator, not by an executor, as each was a few lines. | Mask size limit, 2.7 |
| 14 | Cellpose on an NVIDIA GPU (CUDA) is tested with stand-ins only; this laptop has none. | 2.2 |

**Points carried forward**

Phase 3:

1. The workers estimate is checked again once the workers draw QC figures.
2. Lines in the terminal that are not the runner's: big-fish's `FutureWarning` about `mean_intensity` (once per image), and the "Fetching ..." lines of `omero_tools.py` (unchanged until Phase 8).
3. From Phase 1, unchanged: the other QC images, `run_info.yaml`, `.npz` files, keep-awake and the full `run.log` contents.

Phase 4 and Phase 5:

4. `max_size_fraction` belongs with the other Cellpose settings in the notebook and the app.
5. The app must not load PyTorch for the first time while the thread variables are 1 (2.4).
6. After a cancel during a segmentation, the abandoned segmentation holds the model until its image is done; a run started at once could hold two copies for a short time (2.4).
7. OMERO: the batch process taking over a session from the app, and keeping the session alive after the main process has rejoined it (1.13, OMERO fix).
8. Not tested: handing the graphics memory back once after the model is loaded might lower the main process's short peak on the Apple GPU from 4.3 to about 3.3 GB (2.7).

Phase 6 (documentation):

9. A manual threshold and a `min_spots` value chosen with top-hat do not carry over unchanged to rolling ball (2.6).
10. `max_size_fraction` is a fraction of the whole image, so a crop may need a higher value than the full image.
11. On a 16 GB laptop, `workers: auto` with Cellpose usually runs one worker with the warning about little memory.
12. From outside the lab network, reading from OMERO takes most of the time of a run (23 to 50 s per channel over the VPN).
13. `bigfish-pypeline batch` asks for the OMERO password only; the user name is in the settings file.
14. Cellpose keeps its own log file in `~/.cellpose/run.log`.

Phase 7 (Windows and Linux):

15. Cellpose on an NVIDIA GPU, and a whole run with two or more workers beside Cellpose, on a lab machine.

**Manual checks for the user**

1. On a day with a stable VPN, in the `bigfish-msp` env: `bigfish-pypeline batch ~/bigfish-testdata/phase2/omero/omero_batch.yaml` (images 5806 and 5795). Both images should finish. If the connection drops, `run.log` shows a line ending in "rejoining the session and trying again". The terminal should show no session key and no lines starting with `WARNING:`.
2. Try Cellpose on the test kit, from the repository folder with `bigfish-msp` active. Copy `tests/data/sypN_DAPI_Phal_jim-exon_crop_config.yaml` and `tests/data/sypN_DAPI_Phal_jim-exon_crop.tif` into a folder on the Desktop, change `source: label_files` to `source: cellpose` in the copy, and run `bigfish-pypeline batch <the copied config>`. Look at `run.log`, `labels/` and the figure in `qc/`: are the wording and the figure what you expect? The masks themselves are not the point here (brief R8).
3. Look at a full-size run with Cellpose: `~/bigfish-testdata/benchmarks/phase2/runs/2026-11-23_2134_batch_gpu_1w/`.
4. Read the "choices the spec does not settle" in entries 2.1, 2.3 and 2.4, which decide what users see.
5. An image that suits Cellpose-SAM (e.g. cultured cells) for the mask review, any time before Phase 8.

**Housekeeping**

- `~/bigfish-testdata/phase2/` (1.2 GB) holds the rolling ball comparison and the OMERO run; 1.1 GB of it is the `cache/` folder of the comparison scripts, which can be deleted once the phase is signed off.
- `~/bigfish-testdata/benchmarks/phase2/` holds the benchmarks: 0.2 GB of run folders, and three hard links to the full-size image in `images/`, which take no extra space.
- `tests/data/` holds about 10 MB.
- `msp` is about 30 commits ahead of GitHub: none of the Phase 2 work has been pushed.

**Sign-off (24 Nov 2026):** the user signed off Phase 2 and asked for `msp` to be merged into `main` and pushed. The manual checks of this review stay open and do not hold up Phase 3: the OMERO fix on the real server, Cellpose on the test kit, and the image for the Cellpose mask review (before Phase 8).

## Phase 3: Outputs, logs and QC

### 3.0 Decisions (24 Nov 2026)

The user agreed the three proposals in the plan before any task started:

1. **Elbow plot in every threshold mode.** It is written whenever `outputs.qc.elbow_plot` is on. With a manual or calibrated threshold it shows the threshold used and, as a second line, the value the elbow method would have chosen. v1 wrote it in automatic mode only.
2. **Text on the cells in the final QC.** The PNG shows each cell's index and number of spots; the other counts are in `cells.csv` and on hover in the HTML version. Above 300 cells the PNG leaves the text out and says so in its title. The spec asked for the index and all counts on every cell.
3. **Size of the HTML final QC.** The image inside the file is the maximum projection in 8-bit with automatic contrast, at full size up to 2048 × 2048 px and reduced above that. The file size on the full-size image is measured in 3.5 and brought to the user if it is over 5 MB.

`msp` with the Phase 3 plan is not pushed.

### 3.3 Elbow plot and calibration plot (24 Nov 2026)

Drawing and writing functions in `qc.py`; the batch runner calls them from task 3.6 on.

- **Elbow plot**, `qc/<image>_ch<index>_elbow.png`: `write_elbow_plot(run_folder, image_name, detected, channel, threshold_mode, lower_limit=None, channel_name=None)`, with `draw_elbow_plot` for the figure alone and `elbow_path` for the file's path. It is drawn from the elbow values `detect_spots` returns, with the look of big-fish's own plot.
  - Legend: "Selected threshold = 18.0" (the threshold used, also marked on the curve); "Lower limit = 20.0" when one is set; and, for a manual or calibrated threshold, "Automatic threshold = 13.0 (not used)" (decision 1 of 3.0). When the lower limit raised an automatic threshold: "Automatic threshold = 13.0 (raised to the lower limit)". When the elbow method gives no value: "No automatic threshold found".
  - Title: image, channel number and name, and "manual threshold", "automatic threshold" or "calibrated threshold".
  - Without elbow values (no candidate spots) nothing is written and the function returns nothing, so that the runner can log a warning.
- **Calibration plot**, `qc/calibration.png`: `write_calibration_plot(run_folder, calibration, thresholds, lower_limits=None, channel_names=None)`, with `draw_calibration_plot` and `calibration_path`. One panel for each calibrated channel: the automatic value of each image of the subset, a line at the median used ("Median used = 15.0"), the lower limit when set, and a cross at the bottom for each image left out of the median, with their number in the legend. Image names are written along the axis for up to 30 images; above that the images are numbered in the order of `calibration.csv`.
- Both are written under a temporary name and renamed, from any thread and without a screen, as the Cellpose QC figure is.
- Checks: 30 new tests in `tests/test_qc.py` (51 pass): each threshold mode with its exact legend text, no elbow values, a manual value outside the curve, a failed write, a thread that is not the main one, a process without a display; the calibration plot with one and several channels, images left out, no usable median, and 30, 31 and 45 images.
- Looked at by the orchestrator: the crop's elbow plot (top-hat, channel 2) with a manual threshold of 18, with the automatic threshold (13) and with a lower limit of 20, and a calibration plot of 8 images and two channels. Samples in `~/bigfish-testdata/phase3/samples_3.3/`.

Choices the spec does not settle:

- With a manual or calibrated threshold `detect_spots` does not return the elbow method's value, so the plot works it out from the curve with the same big-fish function (`get_breaking_point`).
- In automatic mode the second line is drawn only when the lower limit raised the value.
- The vertical axis keeps big-fish's label "Number of mRNAs detected (log scale)" and its numbers, which are natural logarithms of the counts, as in v1.
- The elbow plot is 6.5 × 5 inches at 150 dots per inch.

### 3.4 Detection plot and reference spot (24 Nov 2026)

Drawing and writing functions in `qc.py`; the batch runner calls them from task 3.6 on.

- **Detection plot**, `qc/<image>_ch<index>_detection.png`: `write_detection_plot(run_folder, image_name, image, spots, channel, spot_radius_px, clusters=None, cluster_radius_px=None, channel_name=None)`, with `draw_detection_plot` for the figure alone, `detection_path`, and `project_for_detection` for the maximum projection of a 3D channel.
  - The v1 picture: the image on the left and the same image with the detections on the right, in matplotlib's default colours, with orange circles of the spot radius for the spots and filled cyan pentagons of the cluster radius for the clusters. The contrast runs from the lowest value to the 99.9th percentile, as big-fish's `contrast=True` does.
  - Title, e.g. "sypN_DAPI_Phal_jim-exon_crop | channel 2 (jim-exon) | 692 spots | 6 clusters". With no spots the image alone is drawn and the title ends "no spots found".
  - Positions are given in pixels with two columns (y, x) or three (z, y, x). `clusters=None` means cluster detection is off; an empty array means it is on and found none.
- **Reference spot**, `qc/<image>_ch<index>_referencespot.tif`: `write_reference_spot(run_folder, image_name, channel, reference_spot)` and `reference_spot_path`. The array is written as it is, with its values and data type. Without a reference spot (decomposition off or skipped) nothing is written.
- Both are written under a temporary name and renamed.
- Checks: 50 new tests (101 pass in `tests/test_qc.py`). On the crop with the v1 reference settings, the reference spot file equals the v1 reference file in values, shape and data type.
- On the full-size image (36,867 spots, 265 clusters), drawing and saving the plot took 1.0 to 1.2 s and added about 0.1 GB to the process's peak. All circles are drawn as one object; the image is shown in 8-bit, which took the peak of the drawing from about 335 MB to about 73 MB.
- Looked at by the orchestrator: the crop's plot with clusters. Samples in `~/bigfish-testdata/phase3/samples_3.4/`.

Where the picture differs from v1's:

- The figure's height follows the shape of the image (v1: always 20 × 16 inches, with white bands above and below), and the file is 3,000 px wide (v1: 2,000 px).
- The figure has a title and a name above each picture.
- The file is named `_detection.png` (v1: `_finaldetection.png`), as in spec 8.3.

For 3.6: the runner chooses the image to draw on (v1 used the channel after background subtraction) and passes the final spot positions (subpixel when on) and the cluster positions without their other columns; the cluster radius is passed in pixels.

### 3.1 Run record (24 Nov 2026)

Every run folder now holds `run_info.yaml`, with every item of spec 8.4. The file of a test kit run:

```yaml
# Run record: when the run took place, on which computer, with which software,
# and how it ended. The settings of the run are in run_config.yaml.
status: finished
message: 'The run finished: 1 image(s) processed.'
started: '2026-11-24 00:43:47+00:00'
ended: '2026-11-24 00:43:49+00:00'
duration: 2 s
command: bigfish-pypeline batch tests/data/sypN_DAPI_Phal_jim-exon_crop_config.yaml --output-folder ~/Desktop/bigfish_test --workers 1
started_in_folder: /Users/jefflee/Documents/Tools/bigfish-pypeline
settings_file: /Users/jefflee/Documents/Tools/bigfish-pypeline/tests/data/sypN_DAPI_Phal_jim-exon_crop_config.yaml
pipeline_version: 2.0.0.dev0
git_commit: 5ba6632974e4632b04d3ddea22c67bd3e9a10021 (with changes not yet committed)
python_version: 3.12.16
package_versions:
  big-fish: 0.6.2.post1
  cellpose: 4.2.1.1
  torch: 2.14.1
  numpy: 2.5.5
  scipy: 1.18.1
  scikit-image: 0.26.0
  tifffile: 2026.11.16
  omero-py: 5.22.1
operating_system: macOS 26.5.1 (arm64)
processor_cores: 10
computer_memory: 17.2 GB
cellpose_device: not used
workers: 1
workers_reason: 1 worker(s), as set in the config
worker_restarts: none
random_seed: 0
calibrated_thresholds: none
omero_server: not used
```

- **When it is written.** The first part is written as soon as the run folder is made, with `status`, `ended` and `duration` reading "not ended". It is completed however the run ends: finished, cancelled, stopped (ended OMERO session, a single worker that stops, calibration without a usable value) or an unexpected error. A run that is killed leaves the first part.
- **Keys** always come in this order and are always present; a value that does not apply is a word ("not used", "none", "not available", "not installed", "not given").
- `worker_restarts` lists each restart of the pool with its time, the new number of workers and the images lost. `calibrated_thresholds` holds the thresholds in use at the end, e.g. `channel 2: 13.0`. `cellpose_device` is `cpu`, `mps` or `cuda`. `omero_server` is the server and port only.
- `workers` is the number the run really used, and `workers_reason` the text of the log's `Workers:` line, with "lowered to N" when Cellpose runs on the CPU (2.7).
- Package versions are read from the installed package details without loading the packages, so a run with label files still loads neither `cellpose` nor `torch`.
- `git_commit` is given when the package runs from the repository folder and git is installed, with "(with changes not yet committed)" when the code differs from the commit.
- The command is the command line as typed, quoted where needed. `run_batch` takes it as the new argument `command`, for the app; without it the file reads "started from Python (run_batch), not from the command line".
- The OMERO session key is hidden in every value, and the user name is never collected.
- Checks: 11 new tests, and the file is checked in the existing tests of calibration, cancel, stopped workers, the ended OMERO session and Cellpose runs; 866 tests pass without the full-size image. Checked by the orchestrator with the real command on the test kit.

Choices the spec does not settle:

- Three keys the spec does not list: `message` (the closing sentence of the run), `started_in_folder` (so that paths in the command can be followed) and `settings_file`.
- The start time is taken after the checks made before a run, so after the OMERO password is typed and before Cellpose is loaded.
- Times are written as "2026-11-24 10:05:31+00:00": local time with the difference from UTC.
- If the first part cannot be written the run stops with a plain message; if the file cannot be completed, a warning goes into `run.log`.

Seen by the executor in the existing code, both given to task 3.2:

- An unexpected error in a run is written to `run.log` with the session key hidden, but then reaches the terminal as a Python error report whose text is not passed through the same hiding.
- If the label folder of a Cellpose run cannot be made, the run ends with a bare error and leaves a run folder without `run.log`.

### 3.2 Log, `.npz` files and terminal (24 Nov 2026)

- **`run.log` against spec 8.4.** Most items were there already. Added, without rewording any existing line:
  - one line for each FISH channel with its threshold setting, e.g. "FISH channel 2 (jim-exon): manual threshold 18", "automatic threshold, found for each image, never below 30" or "calibrated threshold, from the images whose names contain `cal`";
  - after the summary, "Images in which every channel failed: ..." and "Images not processed: ..." (after a cancel or a stop);
  - "Config file: none (the settings were passed from Python)" when `run_batch` is given no file;
  - a summary line after an unexpected problem.
- **`.npz` files** with `outputs.npz` on: `npz/<image>_ch<index>.npz`.
  - With clusters on, the keys of the v1 general script: `spots_post_clustering` (z, y, x, cluster index; −1 outside a cluster) and `clusters` (z, y, x, number of spots, cluster index). With clusters off, the key of the v1 HCR script: `spots` (z, y, x). Whole numbers without subpixel fitting, decimal numbers (the subpixel positions) with it, as in v1.
  - On the crop the arrays equal the reference files in values, shape and data type, for the general and the HCR case, without subpixel fitting (`tests/data/reference_v1/`) and with it (`tests/data/reference_v1_new_env/`).
  - They are written under temporary names and renamed with the image's tables, before `_images.csv`, which is still renamed last. A failed or skipped channel writes none, and a cancelled or stopped run keeps the files of finished images only. No `npz/` folder when the setting is off.
- **An unexpected problem during a run** no longer reaches the terminal as a Python error report. `run_batch` raises `RunStoppedError`, whose text is the problem in one line with any OMERO session key hidden, and the place of the details (`run.log`). `bigfish-pypeline batch` prints these two lines and the run folder, and ends with exit code 1. The `BatchResult` message is passed through the same hiding.
- **An unexpected problem outside a run** (before the run folder is made, or in `check`): the command line shows Python's report with anything that looks like a session key hidden, under the line "The command stopped because of an unexpected problem. Please pass on the lines below when you report it." Added by the orchestrator after the executor pointed out the gap.
- **A label folder that cannot be made** in a Cellpose run gives a plain message ("The folder for the label images, ..., could not be made ..."), also written to `run.log`; `run_info.yaml` records the stop.
- **big-fish's `FutureWarning` about `mean_intensity`** is hidden in the workers and, for the length of a run, in the main process. Other warnings are shown as before.
- Checks: 974 tests pass without the full-size image (6 min 43 s). New tests cover each point above, among them one run whose log is checked against every item of spec 8.4, and the session key after an unexpected problem at three points of a run (exception, terminal, every file of the run folder).

Choices the spec does not settle:

- In `run_info.yaml`, the message after a problem with a plain text of its own (such as the label folder) is that text.
- The `.npz` files of a 2D image use the same keys without the z column; v1 had no 2D case.
- The stop line of an unexpected problem is written to `run.log` and carried by the error, not shown a second time in the terminal.

Seen, not changed:

- "Summary: N of M image(s) finished" counts an image in which every channel failed as finished; the new line after it names such images.
- Ctrl+C at a moment when the run's own handling of it is not in place is recorded as "stopped", not "cancelled".

### 3.5 Final QC (24 Nov 2026)

Drawing and writing functions in `qc.py`; the batch runner calls them from task 3.6 on. Both forms are made from the per-image tables and the label image, as the app's Results page will have them (spec 10.4).

- **PNG**, `qc/<image>_ch<index>_final.png`: `write_final_qc(run_folder, image_name, picture, spots, clusters, cells, labels, channel, channel_name=None)`, with `draw_final_qc` and `final_png_path`. The channel's maximum projection in grey, cell outlines in green, spots inside a cell as orange circles, spots outside the cells as pink crosses, clusters as cyan pentagons, and on each cell its number and its number of spots ("12: 34"). A legend below the picture names each mark.
  - Title, e.g. "sypN_DAPI_Phal_jim-exon_crop | channel 2 (jim-exon) | 44 cells | 692 spots | 6 clusters". Above 300 cells the text on the cells is left out and the title reads "1287 cells (too many to number, over 300)" (decision 2 of 3.0). Without labels the figure is written without outlines and the title reads "no cells".
- **HTML**, `qc/<image>_ch<index>_final.html`: `write_final_html(..., plotly_script="shared")`, with `draw_final_html` and `final_html_path`. The same view made with plotly: it can be zoomed and moved, and outlines, spots and clusters can each be switched off in the legend.
  - Hover on a cell: "Cell 8 / Spots: 26 / Spots in clusters: 15 / Spots outside clusters: 11 / Clusters: 1 / Area: 3,246 px (13.7 µm²)". On a spot: its number, cell and cluster, and SNR and intensity when the table has them. On a cluster: its number, its number of spots and its cell.
  - The picture inside the page is 8-bit with the contrast stretched, at full size up to 2048 px (decision 3 of 3.0).
  - plotly's own script (4.8 MB) is needed to open the page without an internet connection. `plotly_script="shared"` writes one copy, `plotly.min.js`, into the `qc` folder for all pages of that folder; `"embedded"` puts it inside each page. The shared copy is written under a name of its own for each process and renamed, so that several workers can write it at once.
- Checks: 86 new tests (187 pass in `tests/test_qc.py`). The pages were opened in a browser with `playwright-cli`: image, spots and outlines show, and the hover texts appear, also on the full-size image.
- Looked at by the orchestrator: the crop's PNG and a screenshot of its page. Samples in `~/bigfish-testdata/phase3/samples_3.5/`.

On the full-size image (36,867 spots, 265 clusters, 1,287 cells):

| File | Time | Added to the process's peak | Size |
|---|---|---|---|
| `final.png`, 2,400 px wide | 2.3 to 3.0 s | about 0.33 GB | 9.0 MB |
| `final.html`, script shared | 1.5 to 2.3 s | about 0.27 GB | 7.1 MB, and `plotly.min.js` once (4.8 MB) |
| `final.html`, script inside | 1.5 to 2.3 s | about 0.24 GB | 11.9 MB |
| `detection.png`, 3,000 px wide (3.4) | 1.0 to 1.2 s | about 0.1 GB | 7.1 MB |

- The shared page is over the 5 MB of decision 3: 4.5 MB of it is the picture, stored without loss. As a JPEG the picture would take 2.7 MB at quality 90 and 2.3 MB at quality 85.
- Size of the PNG files against their width, measured by the orchestrator: final QC 9.0 MB at 2,400 px, 6.5 MB at 2,000 px, 4.3 MB at 1,600 px; detection plot 7.1 MB at 3,000 px, 5.0 MB at 2,500 px, 3.2 MB at 2,000 px (v1's width).
- With every QC image on, a full-size image takes about 16 MB for each channel, so about 6.5 GB for 200 images with two channels.

Brought to the user: the default for the plotly script, and the size of the QC images.

Choices the spec does not settle:

- The contrast of the final QC is stretched between the 1st and 99th percentile, as in the Cellpose QC figure; the detection plot keeps big-fish's stretch (lowest value to the 99.9th percentile).
- A spot counts as inside a cell by its `cell_id` in the table.
- The number of cells in the title is the number of labels in the label image.
- Hover on a cell is answered by a grid of points that are not drawn, about 8 px apart on a 2048 px image.

**Decisions by the user (24 Nov 2026), after looking at the samples of 3.5:**

- **The HTML final QC holds plotly's script inside each page** (`plotly_script="embedded"`), so that any page opens on its own. A page of a full-size image is then about 12 MB (crop: 5.5 MB). This is above the 5 MB of decision 3 of 3.0, which the user accepts.
- **The final QC and the detection plot are 2,000 px wide**, in place of 2,400 and 3,000 px: 6.5 MB and 3.2 MB on the full-size image, so about 10 MB for each channel and about 4 GB for 200 images with two channels.

Both are changed in `qc.py` once task 3.6 has left that file.

### 3.6 QC outputs in the batch runner (24 Nov 2026)

`bigfish-pypeline batch` now writes the QC files of spec 8.3 according to the switches of `outputs.qc`. The two decisions at the end of 3.5 are in: the final QC and the detection plot are 2,000 px wide, and the HTML final QC holds plotly's script inside each page (also the default of `write_final_html`).

- **For each channel that is done**, the worker writes `_elbow.png` (in every threshold mode, so the elbow values are now worked out whenever the elbow plot is on; devlog 1.15, deviation 13), `_detection.png` (over the maximum projection after background subtraction, as v1, with the final spot positions), `_referencespot.tif` (when decomposition built one) and `_final.png` or `_final.html` (over the maximum projection of the channel as read, from the channel's tables and the label image). A failed or skipped channel writes none.
- **Order.** The files of a channel are drawn as soon as the channel is done, in `qc_temporary/<image>/` in the run folder. When every channel of the image is done they are moved into `qc/`, and then the tables are written, `_images.csv` last. If the tables cannot be written, the image's QC files are removed again.
- **Unfinished images.** A cancel, a stop, a stopped worker and a retried image leave QC files of finished images only, no temporary file, and no `qc_temporary/` folder. An empty `qc/` folder is removed.
- **`qc/calibration.png`** is written by the main process after the calibration pass, with the lower limits and channel names. It follows the `elbow_plot` switch. A run repeated from `run_config.yaml` does not calibrate and writes none.
- **A QC file that cannot be written** gives the warning "the QC file <name> could not be written: <reason>" in the `warnings` column of `images.csv` and in `run.log`; the channel stays done. A channel without candidate spots gets "no elbow plot: too few candidate spots in this channel to draw one".
- **`run.log`** has a new line after the workers line, e.g. "QC images: elbow plot, detection plot, reference spot, final QC (PNG)", or "QC images: none". It names only what applies to the run.
- **Memory.** Each projection is made once, no second copy of the 3D channel is kept, the figures are drawn after the channel's large arrays are let go, and each figure is let go when saved. Task 3.9 measures the worker's peak.
- **With every QC switch off** a run loads neither `matplotlib` nor `plotly`, in the workers or the main process. With QC on the workers load `matplotlib`, and `plotly` for the HTML form. Workers never load `cellpose` or `torch`.
- Checks: 1,011 tests pass without the full-size image. On the test kit the spots, clusters and cells tables are the same, byte for byte, with every QC output on and with all off, and the comparison with the v1 reference still passes. Checked by the orchestrator with the real command on the test kit: `qc/` holds the elbow plot, the detection plot (2,000 × 1,120 px), the reference spot and the final QC (2,000 × 2,000 px).
- Times on the test kit, whole command with one worker: 4.6 s with every QC output off, 6.1 s with all on and the final QC as PNG, 5.6 s with it as HTML.

The test suite now takes 10 min 33 s, against 6 min 43 s before this task, because the QC outputs are on by default in the test configs. Task 3.8 switches them off in the tests that do not look at them.

Choices the spec does not settle:

- The lower limit is shown on the elbow plot for automatic and calibrated thresholds, not for a manual one, on which it has no effect.
- The reference spot is written whenever decomposition built one, also when no dense region was found.
- `runtime_s` in `images.csv` includes the time spent on the QC files.
- With the elbow plot on, a channel without candidate spots has one more entry in its `warnings` than with it off.

For 3.9: with a manual or calibrated threshold and the elbow plot on, detection now works out the elbow values, which uses a mask of the channel's size for a short time; the worker's peak has to be measured with it.

### 3.7 Keep-awake (24 Nov 2026)

With `run.keep_awake` on, the computer is kept from going to sleep on its own for the length of a run.

- **macOS:** `caffeinate -i -w <the runner's process number>`, started when the run starts. The runner ends it when the run ends; because of `-w` it also ends by itself if the runner is killed. It runs apart from the terminal, so that Ctrl+C does not end it before the run has been cancelled in good order.
- **Windows:** the system's keep-awake request (`SetThreadExecutionState` with `ES_CONTINUOUS | ES_SYSTEM_REQUIRED`), made at the start of the run and withdrawn at its end from the same thread. Tested with a stand-in for the system call only; the real check is left to Phase 7.
- **Linux:** nothing is done.
- It starts once the run folder and `run.log` exist, and ends however the run ends: finished, cancelled (cancel file or Ctrl+C), stopped, or an unexpected problem. `check` starts nothing.
- One line in `run.log`, after the workers line:
  - "Keep awake: the computer is kept from sleeping on its own until the run ends (a laptop still sleeps when its lid is closed)."
  - "Keep awake: off (`run.keep_awake` is off), so the computer may go to sleep during the run."
  - "Keep awake: not available on Linux, so the computer may go to sleep during the run."
  - "Warning: the computer could not be kept awake (<reason>); the run goes on, and the computer may go to sleep."
- Checks: 30 new tests in `tests/test_keep_awake.py`. On macOS: `caffeinate` runs during a run with exactly these options and is gone after each kind of ending; a runner killed during a run leaves none a few seconds later. The Windows and Linux paths with stand-ins; `caffeinate` missing or failing to start. Any test that leaves a `caffeinate` process fails. Checked by the orchestrator with the real command on a copy of the test kit with keep-awake on: the log line is there and no `caffeinate` is left.

Choices the spec does not settle:

- Only idle sleep is prevented (`-i`): the screen may still switch off, and a laptop sleeps when its lid is closed.
- After starting `caffeinate` the runner waits 0.2 s to see that it is running, so a failed start gives the warning.

The test kit config has `keep_awake: false`, as the test configs do.

### 3.8 End-to-end tests of the outputs (24 Nov 2026)

`tests/test_end_to_end_outputs.py`: 13 tests in about 66 s. All but one start `bigfish-pypeline batch` as a separate process. No defect was found in the package, and no worker or `caffeinate` process is left behind.

| Case | Result |
|---|---|
| Test kit with every output on, final QC as PNG and as HTML | the run folder holds exactly the files and folders of spec 8.1; `qc/` holds exactly the files of spec 8.3; every PNG opens as an image; the HTML page needs no address on the internet; no temporary file left |
| Run record and log of those runs | `run_info.yaml` complete, status `finished`, the command as typed; the log names the QC images |
| Repeat from `run_config.yaml` | same tables, same file names, equal `.npz` arrays |
| Calibrated thresholds on generated images | `calibration.csv` and `qc/calibration.png` written; the threshold agrees between `run_config.yaml`, `run_info.yaml` and `images.csv`; the repeat does not calibrate again, writes neither file and gives the same tables |
| Every QC image and `npz` off | no `qc/` or `npz/` folder; same tables as with everything on |
| Cancel while an unfinished image already has QC files drawn | exit code 130; tables, `qc/`, `npz/` and `per_image/` hold exactly the finished images; `run_info.yaml` says `cancelled` |
| One worker killed, with two workers and with one | two workers: the restart is in `run_info.yaml` and every image finishes; one worker: status `stopped`, exit code 1, files of finished images only |
| Cellpose with the stand-in model | the final QC shows the cells of the run's own label file, with the counts of its `cells.csv`; the Cellpose QC figure is beside it |
| Keep-awake through the real command (macOS) | one `caffeinate` tied to the command during the run, none afterwards, the log line |

**Run time of the suite.** The QC images are now switched off in the test configs of the tests that do not look at them (`local_config`, `write_settings`, the copies of the kit config); the kit config file itself is unchanged. No assertion was removed and no test skipped.

| | Tests | Time |
|---|---|---|
| Before this task (with 3.7) | 1,041 | 10 min 52 s |
| After, with the 13 new tests | 1,054 | 9 min 36 s to 9 min 40 s |

- The aim of 8 minutes was missed: switching the QC images off saved about 2 min 20 s, and the new tests take 1 min 6 s. Most of what remains is the 1.5 s each test with a worker pool spends starting its workers.
- Run by the orchestrator in two halves: 134 tests in 5 min 49 s (end-to-end, keep-awake, command line, Cellpose batch) and 920 in 3 min 47 s.
- Not done, for the user to decide: running the tests in parallel, which needs the package `pytest-xdist` in `msp-environment.yml`.

### 3.9 Time and memory with the outputs on (24 Nov 2026)

Scripts, raw logs, `benchmarks.csv` and `conditions.txt` are in `~/bigfish-testdata/benchmarks/phase3/`. Conditions and memory measure as in 2.7: full-size image, channel 2, rolling ball at 5 px, threshold 18, every step on, one measurement at a time in a new process. Before each measurement 8.4 to 9.4 GB of memory was available.

**One worker** (`process_image`, with the Cellpose label file of 2.7; 37,126 spots, 271 clusters and 1,287 cells every time)

| Outputs | Time | Peak memory | Bytes per voxel |
|---|---|---|---|
| Every QC image and `npz` off | 293.5 s | 5.49 GB | 37.4 |
| Every QC image on, final QC as PNG, `npz` on | 293.7 s | 5.52 GB | 37.6 |
| The same with the final QC as HTML | 293.4 s | 5.52 GB | 37.6 |
| Elbow plot alone | 290.7 s | 5.51 GB | 37.6 |
| Detection plot alone | 291.4 s | 5.52 GB | 37.6 |
| Final QC as PNG alone | 290.5 s | 5.53 GB | 37.7 |

The totals differ by about 3 s from run to run, more than the outputs cost. The time of each file, measured on its own:

| File | Time | Size |
|---|---|---|
| `_elbow.png` | 0.1 s | 0.06 MB |
| `_detection.png` | 0.7 s | 3.1 MB |
| `_referencespot.tif` | under 0.01 s | 1 kB |
| `_final.png` | 2.0 s | 6.5 MB |
| `_final.html` | 1.6 s | 11.9 MB |
| `.npz` | under 0.01 s | 1.2 MB |
| All QC files of the channel | 2.5 to 2.9 s | – |

- **The peak does not come from the outputs.** It falls about 52 s into the channel, during background subtraction and the LoG filter, as before. The figures are drawn at the end, when the worker holds about 0.25 GB.
- The 0.02 to 0.04 GB above the base line is `matplotlib`, which the worker has loaded from the start when a QC image is on.
- Working out the elbow values for a manual threshold (3.6) takes 1.4 s and raises memory to 1.4 GB for a moment, far below the peak.

**Whole run with Cellpose on the Apple GPU** (three copies of the image, one worker, every output on, keep-awake on)

| | Every output on | Without the outputs (2.7) |
|---|---|---|
| Total time | 15 min 57 s | 16 min 0 s |
| Main process, peak (before the first worker starts) | 4.31 GB | 4.33 GB |
| Main process while the worker runs | 2.6 to 3.2 GB | 2.6 to 3.5 GB |
| Worker, peak | 5.54 GB | 5.52 GB |
| Highest sum at one moment | 8.47 GB | 8.45 GB |
| Lowest memory available | 2.9 GB | 2.4 GB |

- The run folder is 137 MB for three images: `qc/` 37.5 MB (12.5 MB for each image, with the Cellpose QC figure), `labels/` 50 MB, `npz/` 3.6 MB.
- The "while the worker runs" figures of the main process are every sample of the two logs; 2.7 gave the usual range (2.7 to 2.9 GB). Single samples above 3 GB during a segmentation were there in Phase 2 as well.

Checked by the orchestrator against the logs: time and peak of the worker with the outputs off, with all on and with the final QC alone; the time of each QC file; the time and the highest sum of the whole run.

**Result: the `workers: auto` figures stand** (38 bytes per voxel, 2 GB kept free, 3 GB more with Cellpose). The highest worker peak measured is 5.54 GB against the 5.58 GB of the estimate, and the highest sum of 8.47 GB is under the 8.58 GB the estimate allows for one worker beside Cellpose. The margin of the per-worker figure is under 1 %.

**Enlarged pictures.** Seen by the orchestrator on the test kit: with the detection plot at 2,000 px, the 384 px crop was enlarged by a factor that is not a whole number and smoothed, which made the file 2.3 MB and soft. A picture shown larger than its own size now keeps its pixels as they are: the crop's detection plot is 0.7 MB. Images of 1,000 px or more across are drawn as before.

### 3.10 Samples for the user (24 Nov 2026)

Run folders made with the real command and every output on, for the user to look at the QC images, `run.log` and `run_info.yaml`. The four small ones are in `~/bigfish-testdata/phase3/samples/` (made by `make_samples.py` in that folder); each has its `settings.yaml`, an `input/` folder, the text the terminal showed (`terminal.txt`) and the run folder.

| Sample | Folder | Shows |
|---|---|---|
| Test kit with its label file | `samples/kit_label_files_png/` | elbow plot, detection plot, reference spot, final QC as PNG (44 cells, numbered), `.npz` file |
| The same with the final QC as HTML | `samples/kit_label_files_html/` | the interactive page (5.5 MB) |
| Test kit with Cellpose | `samples/kit_cellpose/` | the Cellpose QC figure and the final QC with the cells of the run's own labels (43 cells; masks not judged) |
| Calibrated threshold, four small images | `samples/calibrated_four_images/` | `calibration.csv` and the calibration plot (values 13, 14, 13, 13; median 13) |
| Full-size image with Cellpose, three copies | `~/bigfish-testdata/benchmarks/phase3/runs/2026-11-24_0342_batch_gpu_1w_all/` | the QC images at full size (1,287 cells, no numbers on the cells), `run_info.yaml` of a longer run |
| Full-size image, final QC as HTML | `~/bigfish-testdata/benchmarks/phase3/runs/w_c/qc/` | the interactive page of a full-size image (11.9 MB) |

The three extra images of the calibrated sample are 384 × 384 px regions of the full-size image; they stay on the laptop.

The crop's QC images: [elbow plot](figures/phase3/crop_ch2_elbow.png), [detection plot](figures/phase3/crop_ch2_detection.png), [final QC](figures/phase3/crop_ch2_final.png); and the [calibration plot](figures/phase3/calibration_four_images.png) of the four small images.

Looked at by the orchestrator: every sample finished without a warning; the test kit gives 692 spots and 6 clusters in each, with 44 cells from the label file and 43 from Cellpose; the calibration plot; the full-size final QC.

Seen on the full-size final QC: the picture does not use the full width of the figure, because the figure's height is limited to its width and the title and legend take part of it. Left as it is unless the user wants it changed.

Waiting for the user's review of the samples.

### 3.11 Phase 3 review (24 Nov 2026)

The numbers after the fixes of 3.13 to 3.17 are in entry 3.18.

Checks run in a fresh shell, at commit `bf270e0`. One command is cut off after 10 minutes, so each suite run was made in two parts.

| Check | Result |
|---|---|
| Whole suite, with the full-size image | 1,057 passed (134 and 923), 11 min 44 s in all |
| The same without the full-size image (`-m "not full_image"`) | 1,054 passed, 9 min 36 s; run during 3.8, not in a fresh shell and before the last small change to `qc.py` |
| The same without the tests that need the Cellpose model, as on a computer without the model | 1,048 passed (131 and 917), 8 min 46 s |
| v1 imports in the main env (`image_utils`, `omero_tools` from `src/`, Python 3.9, Cellpose 3.1.1.2) | work as before |
| Main env | `conda env export` identical to the export stored with the reference run |
| v1 files (`environment.yml`, `image_utils.py`, `omero_tools.py`) | unchanged since `v1.0` |
| `msp-environment.yml` and `pyproject.toml` | unchanged in this phase |
| Worker and `caffeinate` processes left after the tests | none |

Phase 3 "done when" (spec section 11, with the plan's addition):

| Condition | Result | Entry |
|---|---|---|
| A full run on the test kit produces every output | yes: every file of spec 8.1 and 8.3, with the final QC as PNG and as HTML | 3.6, 3.8 |
| Repeating the run from `run_config.yaml` gives the same tables | yes, with the outputs on or off; calibration is not made again | 3.8 |
| The user has reviewed sample QC images and the log | the samples are with the user | 3.10 |
| The `workers: auto` estimate is confirmed with the QC outputs on | confirmed: 38 bytes per voxel, 2 GB kept free, 3 GB more with Cellpose | 3.9 |

**What Phase 3 delivered**

- `run_info.yaml` in every run folder, written at the start and completed however the run ends.
- `run.log` complete against spec 8.4.
- The optional `.npz` files with the v1 keys, equal to the v1 reference files on the crop.
- The QC images of spec 8.3: elbow plot, calibration plot, detection plot, reference spot, and the final QC as PNG or as an interactive HTML page; each with its switch, and each also available to the notebook and the app as a function that gives the figure.
- Keep-awake during a run on macOS and Windows.
- Plain messages in place of Python error reports when a run stops unexpectedly, with the OMERO session key hidden.
- 9,400 lines in `src/bigfish_pypeline/`, 1,057 tests.
- On the full-size image the outputs add about 3 s to a channel of about 290 s, do not raise the worker's memory, and take about 12.5 MB of disk for each image and channel.

**Deviations from the spec and the plan**

| # | Deviation | Entry |
|---|---|---|
| 1 | The elbow plot is written in every threshold mode, with the elbow method's value as a second line when it was not the one used. User's decision. | 3.0, 3.3 |
| 2 | The final QC as PNG shows each cell's number and its number of spots, not all the counts, and no text above 300 cells. User's decision. | 3.0, 3.5 |
| 3 | The HTML final QC holds plotly's script inside each page: about 12 MB for a full-size image, where the brief expected a few MB. User's decision. | 3.5 |
| 4 | The final QC and the detection plot are 2,000 px wide. User's decision. | 3.5, 3.6 |
| 5 | The detection plot is not v1's file: its height follows the image, it has a title, and it is named `_detection.png`. | 3.4 |
| 6 | `run_info.yaml` has four keys the spec does not list: `message`, `started_in_folder`, `settings_file` and `omero_server`. | 3.1 |
| 7 | The calibration plot follows the `elbow_plot` switch; it has none of its own. | 3.6 |
| 8 | QC files are drawn in `qc_temporary/<image>/` and moved into `qc/` just before the image's tables are written, not renamed in one step with them. The image still counts as finished only once `_images.csv` is there. | 3.6 |
| 9 | An unexpected problem during a run raises `RunStoppedError`, and the command line prints a plain message in place of Python's report. Not asked for by the spec. | 3.2 |
| 10 | `runtime_s` in `images.csv` includes the time spent on the QC files. | 3.6 |
| 11 | Keep-awake prevents idle sleep only. The Windows request is tested with a stand-in. | 3.7 |
| 12 | The test suite takes 9 min 36 s; the aim of 8 minutes set in 3.8 was missed. | 3.8 |
| 13 | Three small changes were written by the orchestrator, not by an executor: the hiding of session keys in an unexpected problem outside a run, the two defaults decided by the user (2,000 px, script inside the page), and true pixels for enlarged pictures. | 3.2, 3.6, 3.9 |
| 14 | Task 3.6 was started before the user's first look at the final QC, which the plan put before it; the look changed two defaults only. | 3.5 |
| 15 | The margin of the per-worker memory figure is under 1 % (5.54 GB measured against 5.58 GB). | 3.9 |

**Points carried forward**

Phase 4 and Phase 5:

1. Each QC figure has a function that gives the figure (`draw_...`) without saving it; the final QC is built from the per-image tables and the label image, as the Results page needs (spec 10.4).
2. `run_batch` takes the text for `command` in `run_info.yaml`, and raises `RunStoppedError` when a run stops unexpectedly; the app has to show its message.
3. From Phase 2, unchanged: `max_size_fraction` with the other Cellpose settings; PyTorch must not be loaded first while the thread variables are 1; an abandoned segmentation holds the model for a short time; the batch process taking over an OMERO session and keeping it alive.

Phase 6 (documentation):

4. What each QC image shows; the elbow plot's vertical axis is the natural logarithm of the number of spots.
5. Disk use of the QC images, and the switches that turn each off.
6. Keep-awake does not stop a laptop sleeping when its lid is closed.
7. The keys of `run_info.yaml`; "finished" in the summary line counts images in which every channel failed, which the next log line names.

Phase 7 (Windows and Linux):

8. Keep-awake on Windows with the real system call; from Phase 2: Cellpose on an NVIDIA GPU, a whole run with two or more workers beside Cellpose, Ctrl+C on Windows.

Small points left as they are:

9. Ctrl+C at a moment when the run's own handling of it is not in place is recorded as "stopped".
10. On the full-size final QC the picture does not use the full width of the figure.

**For the user to decide**

- Whether the tests may run in parallel, which needs `pytest-xdist` in `msp-environment.yml` and should bring the suite well under 8 minutes.

**Manual checks for the user**

1. The samples of 3.10: the QC images, `run.log` and `run_info.yaml`. Are the pictures, the wording and the file names what you expect?
2. Try it on the test kit, from the repository folder with `bigfish-msp` active: `bigfish-pypeline batch tests/data/sypN_DAPI_Phal_jim-exon_crop_config.yaml --output-folder ~/Desktop/bigfish_test`, then open the `qc/` folder of the run.
3. Open an HTML final QC in your browser (e.g. `~/bigfish-testdata/phase3/samples/kit_label_files_html/`), with the internet connection off if you want to see that it needs none.
4. Read the "choices the spec does not settle" in entries 3.1, 3.2, 3.5 and 3.6, which decide what users see.
5. Still open from Phase 2: the OMERO fix on the real server, and an image for the Cellpose mask review.

**Housekeeping**

- `~/bigfish-testdata/phase3/` (0.15 GB) holds the samples; `~/bigfish-testdata/benchmarks/phase3/` holds the benchmarks: about 0.2 GB of run folders, and hard links to the full-size image, which take no extra space.
- `docs/modularisation-streamlit-project/figures/` holds 3.1 MB, of which 1.6 MB is new.
- `msp` is 25 commits ahead of GitHub: none of the Phase 3 work has been pushed.

### 3.12 Independent review (25 Nov 2026)

Gemini 4 Neon (High), run through Antigravity, reviewed the code, the science and the decisions of Phases 0 to 3 on `msp` at commit `b757802`. It could read the repository, the installed big-fish and Cellpose packages, and `~/bigfish-testdata/` (QC images, logs and tables, not the image files). It could not change files or run commands. The orchestrator checked each finding against the code, and the pixel-type finding with a test script.

**Confirmed**

| # | Phase | Finding | Where |
|---|---|---|---|
| 1 | 1 | Images that are not 8-bit or 16-bit unsigned are accepted when they are opened and fail later in the run, with a message that does not say why (table below). The end-to-end test of a float image passes only because its spots are far apart, so decomposition finds no dense region. | `io.py` (`read_channels`) |
| 2 | 3 | With `segmentation.drop_border_cells: true`, the final QC (PNG and HTML) still draws the border cells that `cells.csv` leaves out, counts them in its title, and shows them with 0 spots and no area. No test covers it. | `batch.py` 565–573; `qc.py` (`_cell_shapes`) |
| 3 | 3 | The elbow plot's axis reads "Number of mRNAs detected (log scale)", big-fish's label. The values are natural logarithms, which a reader may take for log10. | `qc.py` 422 |
| 4 | 1 | `calibration.csv`, and the calibration plot of Phase 3, hold the threshold after the lower limit is applied. An image whose elbow fell below the limit cannot be told from one whose elbow was at the limit. | `batch.py` 933–936 |
| 5 | 1, 2 | The settings check lets through `decomposition.alpha` above 1 (big-fish then stops the channel), infinite numbers (`.inf`), `clusters.min_spots: 1`, `cellpose.min_size` below −1 and an empty `cellpose.model`. | `config.py` |
| 6 | 1 | When a run stops, its message appears twice in the terminal: from the runner, and again at the end from the command line. | `batch.py` 2031; `cli.py` 276–278 |
| 7 | 3 | A label file with very large cell numbers (e.g. 100,000,000) makes the final QC use several GB of memory, because the numbers are not renumbered when the file is read (Phase 2). Rare. | `qc.py` (`_cell_shapes`, `_cell_values`) |
| 8 | 2 | The first panel of the Cellpose QC figure is titled "original image" by Cellpose's own plotting function, but it shows the image after pre-treatment. | `qc.py` 239 |
| 9 | 1 | `run.log` says "1 clusters". | `batch.py` 2234 |
| 10 | 3 | `run_info.yaml` gives the versions listed in spec 8.4, but not those of pandas, scikit-learn (clusters), pydantic and plotly. | `outputs.py` 36–45 |
| 11 | 1 | If a worker stops in the same pass as a stop for another reason (OMERO session ended, results cannot be written), the files of the worker's image are not removed. Rare. | `batch.py` 2002–2032 |

Pixel types, on a generated 3D image with one dense region, through background subtraction, detection at threshold 18 and decomposition:

| Pixel type | Rolling ball | Top-hat |
|---|---|---|
| 16-bit unsigned | works (38 spots, 44 after decomposition) | works (same) |
| 16-bit signed, 32-bit signed or unsigned | fails at decomposition | fails at background subtraction |
| 32-bit float | fails at decomposition | fails at decomposition |

8-bit unsigned images are covered by the end-to-end test.

**Not upheld**

- "Background is subtracted twice, which gives a third more clusters." The Gaussian background step in `decomposition.py` is big-fish's own step for the reference spot, and v1 ran it after top-hat too. The extra clusters come from rolling ball against top-hat, measured in 2.6 and accepted with B5.
- "SNR is inflated." SNR is measured on the image after background subtraction, as the spec says. Rolling ball sets 36–38 % of the pixels to 0 (2.6), so SNR values from rolling-ball and top-hat runs cannot be compared. This is for the documentation.
- "Counts change with the image name." Already recorded: the seed comes from the output name ("Real OMERO batch with Cellpose").
- "The final QC's contrast (1st to 99th percentile) is wrong." On `region_2_ch2_final.png` and the crop's final QC the spots are clear and the markers sit on them; the background looks grainy and the brightest clumps are white. A higher upper limit (e.g. the 99.8th percentile) is a matter of taste, for the user's review of the samples.
- "The cell text '38: 0' is cut off at the edge." It is not, in the crop's final QC.

**Decisions the review questions**

- B5, rolling-ball radius in pixels: the same setting means a different size on a microscope with a different pixel size. A point for the documentation, or a warning when the radius is small next to the spot radius in nm.
- R8, the Cellpose 4 mask review before Phase 8: the notebook (Phase 4) and the app (Phase 5) are built around Cellpose defaults not yet checked on the images they are meant for.
- 3.11 deviation 3, plotly's script inside each HTML page: about 12 MB for each full-size image and channel, several GB for a large run. PNG is the default; the documentation gives the size (point 5 carried forward).

The review found that the other decisions of the brief and the devlog hold up.

**Not checked:** a difference of about 5 s between the durations in `run_info.yaml` and `run.log`; `per_image/` left uncombined after an unexpected problem; the detection plot's cluster markers hiding the spots under them; colours safe for colour-blind readers in the final QC and the elbow plot; whole numbers on the axis of the calibration plot.

**Second review: Phases 0 to 2.** Gemini 4 Neon (High) also reviewed a copy of `main` at the Phase 2 sign-off, so that only the code of Phases 0–2 was in view, with the findings above listed as known. Same access, and same checks by the orchestrator against the code on `msp`.

Confirmed:

| # | Phase | Finding | Where |
|---|---|---|---|
| 12 | 1 | The settings check also lets through `decomposition.beta: 0`, which makes the whole image one dense region, and a background radius below 1 px, with which top-hat removes the whole image. Read in the code, not run. | `config.py` 185, 223 |
| 13 | 1 | Worker numbers are worked out from every image header, including a time-lapse file that will be refused, so one such file in the input folder can lower the number of workers or stop the run for lack of memory. | `batch.py` (`_largest_channel`) |
| 14 | 1 | Checking an image's layout reads the whole image when the file holds it in one block and cannot be mapped (e.g. a compressed file). | `batch.py` 231; `io.py` (`read_channels`) |
| 15 | 1 | Widens finding 11: after a stop is found, the runner still waits for and handles worker results before it stops. | `batch.py` 1965–2032 |
| 16 | 2 | The Cellpose QC figure never shows the channel name: the runner does not pass it. | `batch.py` 1554–1558 |
| 17 | 2 | For an image the runner marks failed (e.g. a worker lost twice), `images.csv` leaves the segmentation status and warnings empty, even when Cellpose ran. | `batch.py` (`write_failed_image`) |
| 18 | 2 | Label files written by the runner carry no pixel size, so Fiji shows them in pixels. | `segmentation.py` 458 |
| 19 | 1 | `log_intensity` is written with decimals (`18.0`); devlog 1.6 says whole numbers. | `outputs.py` 189–193 |
| 20 | 2 | With `drop_border_cells` on, `images.csv` counts the cells kept, while `run.log` and the Cellpose QC figure give every cell Cellpose found. | `batch.py` 437 |

Points of science, confirmed in the code, all as in v1:

- The spot radius on the test image is 0.994 px in y and x (`phase2/results/full_ch3/summary.json`). big-fish rounds it up for the detection window and the reference spot, so a small change in emission wavelength or pixel size that takes it above 1 px makes both larger. The confocal formula of `psf.py` takes the pinhole as very small; a spinning disk is nearer the widefield case. Brief D4 assumed that `ex` and `em` matter little.
- Per-spot SNR takes its background ring at 1.5 to 2.5 times the spot radius. If the true spot is wider than the radius, the ring sits on the spot's own edge and SNR comes out low. Not measured.
- With whole-number pixel sizes and subpixel fitting off, cluster centres are cut to whole pixels (big-fish keeps the data type of the spots); with decimal pixel sizes they are exact (devlog 1.9).
- With decomposition and subpixel fitting both on, each spot of a dense region is fitted on its own, so the spots of one focus are pulled towards the same peak.
- Cellpose pre-treatment: clip comes before background subtraction (D9), so clip at its default of 100 flattens an image whose camera offset is above 100. A mean projection keeps negative values after rolling ball, and a maximum projection does not (devlog 2.1).

Not upheld:

- "A sparse image crashes the automatic threshold." Not reproduced: 18 generated images with 0 to 200 spots, flat or noisy, with rolling ball and with top-hat, all gave a threshold or "no threshold". The third review found a smaller case that does crash (finding 22).
- "A full disk at the end of a run shows a Python report." Since 3.2 an unexpected problem gives `RunStoppedError` and a plain message.
- "Cellpose's GPU memory is freed while an abandoned segmentation still runs, which can crash the program." Not tested. The command line ends straight after, and the app runs batches as a separate program (brief H), so the risk is small; kept for Phase 5.
- "Devlog 2.6 left out the intron channel's fall from 22 to 4 clusters." It is in the table of 2.6. 18 is below that channel's automatic threshold (22–23).
- "The 38 bytes per voxel were set before the QC figures." Measured again with them in 3.9.
- "A one-channel file in a batch of several channels fails." Right as it is: the file does not hold the channels the settings ask for.
- "The check for damaged files is not safe with threads." During a run only the segmentation thread reads TIFF files in the main process. A point for Phase 5 if the app reads images itself.

Decisions the second review questions: B5 and 2.6, the rolling-ball radius of 5 px for FISH, tested at no other radius (it suggests 15–25 px); D6, D9 and 2.1, the place of clip and the negative values of a mean projection; R2 and R8, as in the first review. It found the other decisions of the brief, the devlog and the "choices the spec does not settle" in 1.2, 1.3, 1.8, 1.9, 1.10, 2.1, 2.3 and 2.4 sound.

Not checked: OMERO image names sorted without Unicode normalisation; an empty `resolved.images`; the `atexit` handler in `omero_tools.py` (unchanged until Phase 8); the full-image test comparing sets of spot positions, not counts.

**Third review: Phases 0 to 3.** GPT-6.2 Astra (medium effort), run through Codex in a read-only sandbox, reviewed `msp` at commit `61670ec` with the same brief as the first review. It could read the repository, the installed packages and `~/bigfish-testdata/`, run read-only commands and small Python checks, and compare with `main` to tell the phases apart. It read devlog 3.12 only after writing its own findings. The orchestrator checked each finding against the code, and findings 22 and 25 with test scripts.

Confirmed:

| # | Phase | Finding | Where |
|---|---|---|---|
| 21 | 1 | The confirmed layout is used for every file of the run without comparing it with the file's own axes. A file stored `ZCYX` read with the layout `CZYX` (same number of axes) mixes channels and Z planes without any message. Spec section 13 expects such an image to fail with the reason. Read in the code, not run. | `io.py` (`_plane_sizes`, `read_channels`); `batch.py` 230 |
| 22 | 1, 3 | An elbow curve with a single point (an image with a few maxima, e.g. eight at 3 and one at 150) makes big-fish's `get_breaking_point` fail. In automatic mode the channel fails. With the elbow plot on (Phase 3), a manual or calibrated threshold fails too, while without it the same image gives 9 spots. Run on a generated image. | `detection.py` (`get_elbow_values`) |
| 23 | 1, 2 | When rejoining the OMERO session, the OMERO library answers "not joined" both when the session has ended and when the connection times out. The package then says the session has ended and stops the run. Read in the OMERO library, not tried on the server. | `io.py` (`join_session`) |
| 24 | 1 | If a worker stops between two checks, handing the next image to the workers fails with the same error. This is outside the handler that restarts with fewer workers. The run stops with an unexpected problem, and that image is dropped from the queue. Read in the code, not run. | `batch.py` 1980–1981 |
| 25 | 1 | The threshold value and its lower limit accept `.nan` and `.inf`. A manual threshold of `.nan` finds 0 spots without a warning. Run. Widens findings 5 and 12. | `config.py` (`Number`) |
| 26 | 2 | The Cellpose QC title says "diameter chosen by Cellpose" when no diameter is set. Cellpose 4 does not estimate a diameter: the image is used at its own scale. A test expects the wording. | `qc.py` 43; `tests/test_qc.py` 159 |
| 27 | 3 | The total time in `run.log` (15 min 49 s in the full-size benchmark run of 3.9) and the duration in `run_info.yaml` (15 min 54 s) disagree. Both use the same clock, but the log line is written before the end steps of the run. | `batch.py` 2371, 2474 |
| 28 | 3 | The detection plot draws clusters as filled cyan pentagons, as v1 does, which hide the spots of a bright focus. The final QC fills them at 30 %. | `qc.py` 789, 1186 |

Same as earlier findings, with more:

- Finding 7: two allocations grow with the largest cell number, SciPy's list of objects and the count of spots per cell. A single cell numbered 100,000,000 asks for about 800 MB for the counts alone.
- Finding 3: the elbow plot's values are the smoothed natural log of the number of local maxima above each threshold, counted before spots sharing a peak are merged. They are not a final spot count.
- Finding 4: four weak images whose elbows were all raised to the lower limit look in agreement on the calibration plot.
- The first review's "not checked" points on the 5 s difference in durations and on markers hiding spots are confirmed (findings 27 and 28).
- The final line in the terminal and the message in `run_info.yaml` do not give the number of failed or skipped channels; the summary line of `run.log` does. The command ends with 0 even when images failed, as its help text says.

Points of science, confirmed in the code:

- With a nuclear label image, as in the test kit, the tables and figures still say "cells". A 2D nuclear outline also collects the spots of every Z plane, so spots above and below a nucleus are counted as nuclear.
- The reference-spot picture is built from the image after background subtraction. The Gaussian fit that decomposition uses is made on a copy with big-fish's Gaussian background removed (as in v1), so the picture is not the fitted spot.
- Each QC picture sets its own contrast. This helps to find spots and cells, but brightness cannot be compared between pictures.
- Three hard links to one file, under different names, gave 36,867, 36,929 and 36,525 spots and 265, 272 and 261 clusters (3.9 benchmark run). This is within the run-to-run range of 1.14, and it comes from the seed taken from the name. It matters when renaming files, or when comparing a local copy with the OMERO image.
- On the crop with the v1 settings (top-hat 5 px, threshold 18): 473 spots detected, 692 after decomposition and 6 clusters, in v1 and in the new tables and QC alike. On the full-size image, 24,631 spots detected in both.

Decisions the third review questions:

- D9 and 2.1 (clip before background subtraction; negative values after a mean projection): wrong. Already changed by the user's decisions below (task 3.16).
- F3: `run_config.yaml` names label files and a custom Cellpose model by their path. If those files change, a rerun gives other results without saying so.
- Phase 1: the command ends with 0 when images failed. With little free memory, the run uses one worker with a warning (2.7), although that does not show there is enough memory.
- A2, R2 and R6–R8: one specimen and its crops serve well as a check against v1, but they do not show that the defaults suit other samples (negative controls, cultured cells).
- B5 and D4: as in the first two reviews.

It found the other decisions of the brief and the devlog sound, and agreed with the user's four decisions below. It adds three checks: cluster centres within 1 px on each axis; clusters whose cell changes; and, in 3.17, isolated spots and dense foci as well as totals.

Not upheld: the cause given for finding 27 (a clock started before the Cellpose model is prepared): both durations use the same clock.

Not checked by the third review: the HTML final QC; whether Cellpose masks are right; a worker stopping on real hardware.

**User's decision (25 Nov 2026):** 8-bit, 12-bit and 16-bit images are accepted; any other type (float, signed, 32-bit) is refused when the image is opened. A 12-bit image is read as 16-bit. Checked with 12-bit values saved in a 16-bit file and with a packed 12-bit TIFF: both are read as 16-bit with the right values. Reading a packed 12-bit TIFF needs `imagecodecs`, which is installed with Cellpose but not listed in `msp-environment.yml`.

**User's decisions on the points raised by the reviews (25 Nov 2026):**

1. Rolling-ball radius for FISH channels: the comparison of 2.6 is run again at 10, 15 and 25 px on the full-size image, and the default is chosen from it (task 3.17).
2. Cellpose pre-treatment: clip comes after background subtraction, and values below 0 after background subtraction are set to 0 whatever the projection (task 3.16). This departs from v1, which clipped before background subtraction; clip is off by default.
3. Cluster centres are always exact (decimals), where v1 gives whole pixels when the pixel sizes are whole numbers (task 3.16). The clusters themselves do not change; each centre moves by less than 1 px.
4. Clusters are drawn as outlines only in the detection plot and the final QC, so that the spots of a bright focus stay visible (finding 28, task 3.14). This departs from v1's look.
5. The command still ends with 0 when images failed; the final line in the terminal and the message of `run_info.yaml` give the number of failed and skipped channels (task 3.15).
6. `run_info.yaml` records the size, date and checksum of each label file and custom Cellpose model read, so that a rerun can tell if one has changed (F3, task 3.15).


### 3.14 Fixes in the QC figures (25 Nov 2026)

Done by Sonnet 5.5 (high) in `qc.py`, commit `cc360e9`. The orchestrator read the changes, ran `tests/test_qc.py` (212 pass) and looked at the samples.

- **Final QC, cells left out (finding 2).** When a cells table is given, only the cells found in both the label image and the table are drawn, counted in the title and given text or hover values, in the PNG and the HTML. With `drop_border_cells` on, the crop's final QC shows 26 cells instead of 44. Spots in a cell that is not drawn appear as spots outside the cells, as in the tables. Without a cells table every cell of the label image is drawn, as before; an empty table draws none.
- **Final QC, large cell numbers (finding 7).** The cells drawn are renumbered from 1 inside the figure functions, so the work depends on the number of cells and not on the largest number. A cell numbered 100,000,000 needs the same memory as one numbered 1 (4.1 MB at the peak for a 300 × 400 image, measured in the test). The hover values of the HTML page keep exact cell numbers above 16,777,216.
- **Elbow plot (finding 3).** The axis reads "Natural log of candidate spots above each threshold (smoothed, before spots sharing a peak are merged)", on two lines.
- **Cellpose QC figure (findings 8 and 26).** The first panel is titled "image after pre-treatment". With no diameter set the title says "no diameter set (image used at its own scale)".
- **Clusters as outlines (finding 28, decision 4).** No fill in the detection plot, the final PNG and the final HTML. The detection plot's panel title says "cyan outlines: clusters".
- **Calibration plot (finding 4).** An image whose value was raised to the lower limit is an orange triangle at the value used, joined by a dotted line to an open circle at the elbow method's value. The legend counts these images apart from the others ("Raised to the lower limit (4 images)"). It reads the column `elbow_threshold` (the elbow method's value before the limit) that task 3.15 adds to `calibration.csv`; a table without the column is drawn as before.

**Choices the plan does not settle:** the legend's count of "Automatic value of each image" leaves out the raised images, so the two counts add up to the images in the median; images left out of the median are never marked as raised.

**Samples:** `~/bigfish-testdata/phase3/samples_3.14/` (detection plot, elbow plot, calibration plot with made-up values, final QC with all cells and with the 18 border cells left out, Cellpose QC figure from a stand-in). The two HTML pages were checked by the tests and by their contents, not opened in a browser.

### 3.13 Reading images (25 Nov 2026)

Done by Opus 5.5 (medium) in `io.py`, with two small changes in `batch.py` and one in `cli.py`, commit `f250731`. The orchestrator read the changes and ran the test files of reading, the command line, the batch runner and the end-to-end runs without the full-size image: 511 and 115 pass.

- **Pixel types (finding 1).** 8-bit and 16-bit unsigned images are accepted. A 12-bit image needs nothing of its own: `tifffile` gives 16-bit values for a packed 12-bit file and for 12-bit values in a 16-bit file, and a packed 12-bit image gives the same spot and cluster tables as the 16-bit file. Every other type is refused from the file header, before any pixel is read, for TIFF files and OMERO images. In a run the image is listed as failed and the run goes on. `check` lists such images under "Images that cannot be used"; when the first image is one of them, `check` and `batch` stop with the message.
- **The message:** "`<file>`: the pixel type is 32-bit with decimal values (float32), which cannot be used; only 8-bit, 12-bit and 16-bit images are accepted. Convert the image to 16-bit, for example in Fiji with Image › Type › 16-bit (https://imagej.net/ij/docs/menus/image.html#type), then run it again. In Fiji, first untick "Scale when converting" under Edit › Options › Conversions, so that the pixel values are kept." The last sentence was added by the orchestrator: with that box ticked, Fiji stretches each 32-bit image to the full 16-bit range, so intensities and thresholds could no longer be compared between images.
- **The check for NaN and infinite values is removed.** Only float images can hold them, and those are now refused.
- **Layout check without pixel data (finding 14).** `io.check_image` checks the pixel type, the layout and the channels from the header. A test with a compressed file confirms that nothing is read.
- **Each file's axes (finding 21).** A file's axes count as known when they come from ImageJ or OME metadata, or from the axes `tifffile` writes, and are one of the five layouts. Such a file fails when its axes differ from the layout of the run: "`<file>`: the file's own information says its axes are stored in the order ZCYX, which does not match the layout CZYX of this run (`image.axes` in the settings). Save the image with its axes in the order CZYX, or run it with the layout ZCYX." A plain TIFF is read with the layout, as before. In a batch of a `ZCYX`, a `CZYX` and a `ZCYX` file, the middle one fails and the others finish.
- **OMERO rejoining (finding 23).** The OMERO library answers "not joined" for a refused session and for a timeout alike, and hides the reason. `join_session` now keeps the error the library met: an answer from the server (the session key refused) gives the ended-session message and stops the run; anything else (a timeout, no answer) is a connection problem, so that image fails and the next one tries to rejoin. Tested with the real OMERO library talking to a stand-in for the server's router; no server was contacted. `omero_tools.py` is unchanged.
- **`imagecodecs` 2026.11.11** is listed in `msp-environment.yml` under pip, where the installed copy came from. Nothing was installed.

**Changes in behaviour to know about**

- A Fiji hyperstack is always stored with Z before C. A run with the layout `CZYX` on such files used to mix channels and Z planes without a message; it now fails with the message above.
- Packed 10-bit and 14-bit files are also read as 16-bit and accepted, since their values are read correctly. 1-bit images are refused.
- If a later version of the OMERO library joins a session in another way, the kept error would be missing and an ended session would be reported as a connection problem for each image, instead of stopping the run. The tests with the real library would then fail.
- In a run with Cellpose, a refused image is refused when its segmentation channel is read, so its `warnings` column repeats the message after "no cell results: segmentation failed". Tidied in 3.15.

**For the documentation (Phase 6):** converting to 16-bit in Fiji and the "Scale when converting" box; a 16-bit signed image, which Fiji shows as 16-bit with a calibration, needs another route.

**Tests changed:** the tests that made one channel fail with a NaN in a float image now use a compressed 16-bit file with one damaged plane; the end-to-end test of pixel types expects the float image to fail; the test that the confirmed layout overrides the metadata is replaced by tests of the axes check.

**For the user's OMERO check on the real server:** the rejoin after a dropped connection now goes through the new code, so the check listed in the handoff covers it too.

### 3.17 Rolling-ball radius for FISH channels (25 Nov 2026)

The comparison of 2.6 run again with rolling ball at 10, 15 and 25 px, next to top-hat at 5 px and rolling ball at 5 px, with the settings of 2.6 (decomposition alpha 0.5 and beta 1, clusters of 12 spots within 600 nm, subpixel fitting off, run seed 0). The measurements were made by Opus 5.5 (medium) rather than by the orchestrator, with a copy of the package at commit `25f8270` so that the tasks under way could not change them. Scripts, logs and tables are in `~/bigfish-testdata/phase3/rolling_ball/` (see its `README.md`; every row is in `results/all_results.csv`).

TH is top-hat, RB is rolling ball. Values are in the order TH 5 / RB 5 / RB 10 / RB 15 / RB 25.

| Image, channel | Threshold | Threshold value | Detected | After decomposition | Clusters |
|---|---|---|---|---|---|
| Crop, exon | 18 | 18 | 473 / 440 / 467 / 480 / 478 | 692 / 664 / 696 / 717 / 724 | 6 / 5 / 5 / 6 / 6 |
| | each setting's automatic | 13 / 12 / 12 / 12 / 13 | 610 / 601 / 624 / 636 / 609 | 869 / 868 / 908 / 917 / 888 | 6 / 7 / 8 / 7 / 8 |
| Full size, exon | 18 | 18 | 24,631 / 23,680 / 24,570 / 24,825 / 24,866 | 36,360 / 37,126 / 37,096 / 37,531 / 37,296 | 199 / 273 / 251 / 254 / 251 |
| | each setting's automatic | 15 / 13 / 14 / 14 / 14 | 27,514 / 28,199 / 28,077 / 28,394 / 28,492 | 41,249 / 43,925 / 42,732 / 43,644 / 43,488 | 246 / 308 / 296 / 300 / 287 |
| Full size, intron | 30 | 30 | 1,143 / 1,131 / 1,216 / 1,235 / 1,228 | 1,526 / 1,532 / 1,604 / 1,643 / 1,627 | 0 at every setting |
| | 18 | 18 | 3,143 / 2,612 / 3,193 / 3,428 / 3,494 | 6,365 / 4,725 / 6,154 / 7,119 / 7,250 | 22 / 4 / 24 / 58 / 62 |
| | each setting's automatic | 23 / 22 / 23 / 24 / 24 | 1,643 / 1,654 / 1,703 / 1,629 / 1,644 | 2,404 / 2,462 / 2,440 / 2,328 / 2,366 | 0 at every setting |

**Thresholds.** The automatic threshold moves by at most 1 between the rolling-ball radii. The whole-number threshold whose count is nearest to top-hat's at 18 on the exon channel is 17 at 5 px and 18 at 10, 15 and 25 px (counts within 1 % of top-hat's, not equal). On the intron channel the nearest match for top-hat at 30 is 30 at 5 px and 32 at the larger radii. So a manual threshold does not carry over exactly at any radius (corrected after the fourth review, 3.19).

**Run-to-run range** (run seeds 0 to 5, full-size exon channel at 18):

| | Spots after decomposition | Clusters |
|---|---|---|
| TH 5 | 36,360 to 37,126 | 197 to 212 |
| RB 5 | 36,505 to 37,126 | 258 to 273 |
| RB 10 | 36,470 to 37,130 | 237 to 259 |
| RB 15 | 37,292 to 38,028 | 245 to 271 |
| RB 25 | 37,272 to 37,878 | 244 to 265 |

- Clusters: every rolling-ball radius gives clearly more clusters than top-hat (no overlap). The radii do not differ clearly from each other: the ranges of 10, 15 and 25 px all overlap that of 5 px.
- Spots after decomposition: 15 and 25 px lie 1 to 2 % above top-hat and above rolling ball at 5 px, without overlap. 10 px overlaps both.
- The range was not measured for the intron channel or for the automatic thresholds, so those rows are single runs.

**Same spots** (at most 1 px apart in each of Z, Y and X, each spot paired once; both / first only / second only):

| Comparison | TH 5 with RB 10 | TH 5 with RB 15 | TH 5 with RB 25 | RB 5 with RB 10 | RB 5 with RB 15 | RB 5 with RB 25 |
|---|---|---|---|---|---|---|
| Crop, detected at 18 | 459 / 14 / 8 | 465 / 8 / 15 | 460 / 13 / 18 | 439 / 1 / 28 | 439 / 1 / 41 | 437 / 3 / 41 |
| Full-size exon, detected at 18 | 24,102 / 529 / 468 | 24,203 / 428 / 622 | 24,214 / 417 / 652 | 23,594 / 86 / 976 | 23,590 / 90 / 1,235 | 23,579 / 101 / 1,287 |
| Full-size exon, after decomposition at 18 | 34,594 / 1,766 / 2,502 | 34,800 / 1,560 / 2,731 | 34,694 / 1,666 / 2,602 | 35,106 / 2,020 / 1,990 | 35,174 / 1,952 / 2,357 | 34,978 / 2,148 / 2,318 |
| Full-size intron, detected at 30 | 1,132 / 11 / 84 | 1,137 / 6 / 98 | 1,137 / 6 / 91 | 1,123 / 8 / 93 | 1,124 / 7 / 111 | 1,123 / 8 / 105 |
| Full-size intron, detected at 18 | 2,824 / 319 / 369 | 2,897 / 246 / 531 | 2,930 / 213 / 564 | 2,561 / 51 / 632 | 2,557 / 55 / 871 | 2,563 / 49 / 931 |

For comparison, top-hat with rolling ball at 5 px on the full-size exon channel at 18 gave 23,516 / 1,115 / 164 (2.6). At the same threshold the larger radii share more spots with top-hat than 5 px does.

**Isolated spots** (no other detected spot within 600 nm; full-size exon channel at 18). Of the 14,136 isolated spots found with rolling ball at 5 px, 13, 10 and 12 are lost at 10, 15 and 25 px, and 456, 585 and 613 are gained. The gained spots are dim: their median value in the LoG-filtered image is 19, just above the threshold of 18 (29 for the spots kept), and their median raw intensity is 170 against 193. On the crop none of the 320 isolated spots is lost and 19 to 24 are gained. Against top-hat's 14,542 isolated spots, lost and gained are 627 and 41 at 5 px, 283 and 139 at 10 px, 221 and 223 at 15 px and 217 and 238 at 25 px. So a larger radius keeps nearly every spot of 5 px and adds a few per cent of dim spots at the threshold, and at 15 to 25 px the isolated spots agree with top-hat about as well as two rolling-ball radii agree with each other.

**Dense foci** (full-size exon channel at 18, run seed 0).

- In the 191 clusters found at every setting, the median number of spots is 15 with top-hat, 18 with rolling ball at 5 px and 17 at 10, 15 and 25 px.
- Of the 273 clusters of 5 px, 237, 242 and 237 are found again at 10, 15 and 25 px, with 14, 12 and 14 new ones.
- Of the 199 top-hat clusters, 194 or 195 are found at each larger radius, with 57 to 59 found with rolling ball only; at 10 px, 54 of the 57 are places where top-hat has 8 to 11 spots, just under the limit of 12. This is the picture of 2.6.
- The reference spot returns to top-hat's size from 10 px up, yet the foci keep 1 to 2 more spots than with top-hat. A likely reason, not tested: a larger ball leaves more light in the foci (median intensity after background subtraction at the detected spots 69 at 5 px against 74, 77 and 78), which offsets the larger reference spot.
- On the intron channel at 18, which is below that channel's automatic threshold, the clusters go from 22 with top-hat to 4, 24, 58 and 62. They follow the reference spot's amplitude (54.2 / 64.5 / 57.1 / 52.1 / 52.5), so at that threshold the cluster count is not stable at any radius. At 30 there are no clusters at any setting.

**Other numbers** (full-size exon channel at 18):

| | TH 5 | RB 5 | RB 10 | RB 15 | RB 25 |
|---|---|---|---|---|---|
| Pixels set to 0 (%) | 4.8 | 36.0 | 29.0 | 22.6 | 19.8 |
| Median intensity at the detected spots, after background subtraction | 80 | 69 | 74 | 77 | 78 |
| Reference spot width, Z / YX (nm) | 271 / 100 | 254 / 94 | 269 / 101 | 271 / 102 | 271 / 101 |
| Reference spot amplitude | 62.9 | 61.8 | 63.2 | 62.8 | 63.6 |
| Dense regions | 10,521 | 10,846 | 11,018 | 10,648 | 10,345 |
| Time to subtract the background of one full-size channel (s) | 32 | 42 | 170 | 41 | 75 |

Rolling ball at 10 px is about four times slower than at 5 or 15 px: as in ImageJ, the image is reduced by half before the ball is rolled only above 10 px. The times are for background subtraction alone, measured in one process; those of 2.6 included the LoG filter.

**Per-cell counts on the crop** (44 nuclei, spots after decomposition at 18): totals 413 / 396 / 411 / 425 / 427. Against top-hat, r is 0.990 at 5 px and 0.994 at the larger radii, with a median difference per cell of 0 and a largest difference of 4, 3, 2 and 3 spots.

**Figures** (image panels come from the crop only; full-size panels are in `~/bigfish-testdata/phase3/rolling_ball/figures/`):

- [Spots and clusters at each setting](figures/phase3/rolling_ball/counts-by-setting.png), with the run-to-run range.
- [Sparse regions of the crop](figures/phase3/rolling_ball/crop_sparse-regions.png) and [bright foci of the crop](figures/phase3/rolling_ball/crop_bright-foci.png): the raw image, each background result on one scale, the detected spots, the spots placed by decomposition and the clusters ([where the regions are](figures/phase3/rolling_ball/crop_regions-where.png)). The sparse regions were chosen where the settings differ most.
- Spots per focus: [full-size exon](figures/phase3/rolling_ball/spots-per-focus_full_ch2.png), [crop](figures/phase3/rolling_ball/spots-per-focus_crop_ch2.png).
- [Isolated spots lost and gained](figures/phase3/rolling_ball/isolated-spots_full_ch2.png) on the full-size exon channel.
- Elbow curves: [crop](figures/phase3/rolling_ball/elbow_crop_ch2.png), [full-size exon](figures/phase3/rolling_ball/elbow_full_ch2.png), [full-size intron](figures/phase3/rolling_ball/elbow_full_ch3.png).

**Checked by the orchestrator.** The executor's script at 5 px gives the numbers of 2.6 on the crop and on the full-size image. `bigfish-pypeline batch`, run from the same copy of the package with a separate script, gave on the test kit the counts of the table at 10, 15 and 25 px, with the manual and the automatic threshold (detected, after decomposition, clusters and the per-cell totals 411, 425 and 427), and on the full-size image 24,825 detected spots, 37,531 spots and 254 clusters for the exon channel at 15 px, and 3,494, 7,250 and 62 for the intron channel at 25 px at 18, as in the table. The isolated-spot and dense-focus numbers were not recomputed.

**What the comparison shows, for the user's choice**

- The rise in clusters against top-hat (about a quarter to a third more) stays at every radius. A larger radius does not bring rolling ball back to top-hat's cluster count.
- From 10 px up, a manual threshold chosen with top-hat detects nearly the same number of spots on the exon channel (within 1 %; on the intron channel the nearest match moves from 30 to 32), the shared spots with top-hat rise, and the reference spot has top-hat's size. 5 px is the setting that differs most from top-hat in the spots it detects.
- 15 and 25 px give nearly the same results. 10 px gives results between 5 and 15 px and is the slowest.
- This is one image and its crop. Which count in a bright focus is nearer the truth is not settled, as in 2.6.

**Waiting on the user:** the default radius for FISH channels (5 px now). If it changes, `config.py`, the spec and the test kit's expected tables are updated after 3.15.

### 3.15 Fixes in the settings and the runner (25 Nov 2026)

Done by Opus 5.5 (medium) in `config.py`, `detection.py`, `batch.py`, `cli.py`, `outputs.py` and `segmentation.py`, commit `b36f827`. The orchestrator read the changes and ran the whole suite without the full-size image: 1,147 pass (127 in the batch-run, Cellpose and output files, 1,020 in the rest).

**Settings** (findings 5, 12 and 25). Refused by `check`, each with a message that names the setting and the value found: `decomposition.alpha` outside 0 to 1; `decomposition.beta` of 0 or less; a background radius below 1 px (FISH channels and segmentation); `clusters.min_spots` below 2; `cellpose.min_size` below −1; an empty `cellpose.model`; `.inf` or `.nan` in any number, including the threshold value and its lower limit. Example: "`channels[0].threshold.value` must be a number, not infinite and not `.nan` (found `.nan`)."

**Threshold** (finding 22). An elbow curve of one point, or one for which big-fish cannot give a value (such as a flat curve), gives "no automatic threshold" with the usual warning instead of failing the channel (wording corrected after the fourth review, 3.19). With a manual or calibrated threshold, a problem in the elbow values leaves out the elbow plot only; the spots are the same with the plot on and off (the second part added by the orchestrator, with its test).

**`calibration.csv`** (finding 4). New column `elbow_threshold` after `auto_threshold`: the elbow method's value before the lower limit. On the crop with a lower limit of 15 the row holds 15 and 13. A calibrated run with a lower limit now marks the raised images on the calibration plot.

**The runner**

- A stopped run (finding 6): its message appears once in the terminal and once in `run.log`, at the end, after the summary.
- Once a reason to stop is found (findings 11 and 15), no further result is taken, the workers are stopped at once, and the files of every image not finished are removed, including an image lost with its worker in the same pass. A result that arrives in that pass after the stop is not kept.
- A worker that stops just before the next image is handed out (finding 24) leads to the usual restart with half the workers; the image stays first in the queue.
- Worker numbers (finding 13) leave out images the run will refuse: a pixel type that is not accepted, several time points or positions, axes that do not fit the layout, a missing channel.
- The total time of `run.log` and the duration of `run_info.yaml` (finding 27) are one figure, taken once when the run ends.
- The final message (decision 5), in the terminal, `run.log` and `run_info.yaml`: "The run finished: 2 image(s) processed; 4 channel(s) failed and 1 skipped. See images.csv and run.log in the run folder." Nothing is added when no channel failed or was skipped. The command still ends with 0. The separate line the command printed about failed images is removed, since the message now says it.
- An image the runner marks failed (finding 17) keeps its segmentation status and warnings in `images.csv` in a Cellpose run.
- An image refused when Cellpose reads it (from 3.13) fails with the reason only; the repeated warning is gone.

**`run.log`** (findings 9 and 20): "1 spot", "1 cluster", "1 cell"; for each channel "spot radius 1.12 px in Z, 0.99 px in Y and X"; with `drop_border_cells` on, "44 cells in the label image, 26 kept (18 touching the image border left out, as `segmentation.drop_border_cells` is on)".

**`run_info.yaml`** (finding 10, decision 6): the versions of scikit-learn, pandas, pydantic and plotly, read without loading the packages; and `files_read`, with the kind, path, size in bytes, date last changed and SHA-256 checksum of each label file given by the user and of a Cellpose model file of the user's own. Label files are read once each, in the worker that reads the labels; the model file once, in the main process, in pieces of 1 MB. A built-in model such as `cpsam_v2` gets no entry, and neither do the label files the run writes itself.

**Other outputs:** the Cellpose QC figure shows the channel name when the segmentation channel is also a named FISH channel (finding 16); label files written by the runner carry the pixel size in the way ImageJ stores it (finding 18); `log_intensity` is written as whole numbers when every value is whole (finding 19).

**Tables.** The comparisons with the v1 reference pass unchanged. The test kit's tables differ only in the text of `log_intensity` and the new column of `calibration.csv`.

**Choices the plan does not settle**

- `run.log` holds the message of a stopped run at the end, not at the moment of the stop.
- Finding 20 also named the Cellpose QC figure, which still counts every cell Cellpose found. The plan asked for `run.log` only.
- For a run with label files, `images.csv` leaves the segmentation status empty for an image the runner marks failed, because the runner cannot tell whether the worker had read the file.

**Not tested:** a stop reported by the Cellpose step while a worker's result is ready.

**Manual check for the user:** open a label file written by a Cellpose run in Fiji and see that Image › Properties shows the pixel size in µm. Only `tifffile` was used to read it back here.

### 3.16 Cellpose pre-treatment and cluster centres (26 Nov 2026)

Done by Opus 5.5 (medium) in `segmentation.py` and `clusters.py`, commit `9b7936f`. The orchestrator read the changes and ran the whole suite with the full-size image: 1,160 pass (128 and 1,032).

**Pre-treatment for Cellpose** (decision 2 after 3.12).

- The steps run in the order projection → background subtraction → clip → median → Gaussian. v1 clipped before background subtraction; clip is off by default.
- After background subtraction, values below 0 are set to 0 whatever the projection, so a mean projection gives no negative values to the later steps and to Cellpose.
- Test image with a camera offset of 500, a bright block at 800 and a clip value of 150: the block comes out at 150 on a background of 0. With the old order the whole image was flat.
- The text in the Cellpose QC figure and in `run.log` follows the order, for example "mean projection | rolling ball 200 px | clip 100 | median 3 px".

**Cluster centres** (decision 3 after 3.12).

- big-fish finds the clusters as before. Each centre is then set to the mean position of the cluster's spots, with decimals. The clusters, their numbers, their spots and the spot tables are unchanged.
- With decimal spot positions (subpixel fitting on) nothing changes: the centres equal big-fish's, with a difference of 0.
- With subpixel fitting off, each centre lies at v1's whole-pixel centre or up to 1 px above it on each axis. Largest differences:

| Case | z | y | x |
|---|---|---|---|
| Crop, manual threshold 18 (6 clusters) | 0.94 | 0.94 | 0.76 |
| Crop, automatic threshold (6 clusters) | 0.92 | 0.64 | 0.93 |
| Full-size v1 reference, manual 18 (207 clusters) | 0.96 | 0.95 | 0.94 |
| Full-size v1 reference, automatic (234 clusters) | 0.97 | 0.96 | 0.94 |

- **Clusters whose cell changes.** A cluster is counted in the cell under the nearest pixel of its centre. On the crop with its label file: 0 of 6, with the manual and the automatic threshold, so the per-cell comparison with v1 passes unchanged. On the full-size v1 reference results, with the Cellpose label file of Phase 2: 6 of 207 at 18 (two move out of a cell, three into one, one from cell 1081 to 1095) and 3 of 234 with the automatic threshold. The number of spots in clusters of each cell does not change, because it is counted from the spots' own positions.
- The full-size run folder of 3.9 has subpixel fitting on, so its centres were already exact and none of its 265, 272 and 261 clusters changes.

**Departure from v1.** The `clusters` array of the `.npz` files and the centre columns of `clusters.csv` always hold decimal numbers. In v1 they held whole numbers when subpixel fitting was off, and decimals when it was on. The tests that compared the centres exactly with the v1 reference now ask for the same clusters and spot numbers and for each centre less than 1 px above v1's on each axis.

**Tests changed:** the pre-treatment tests of 2.1 (new order, camera offset above the clip value, no negative values after a mean projection with either method); the five comparisons of cluster centres with v1 (test kit as configured and with the automatic threshold, the `.npz` files, the end-to-end run with label files, and decomposition on the crop).

### 3.18 Phase 3 review brought up to date (26 Nov 2026)

The checks of 3.11 run again after tasks 3.13 to 3.17, at commit `9b7936f`. Each suite run was made in two parts, in the background.

| Check | Result |
|---|---|
| Whole suite, with the full-size image | 1,160 passed (128 and 1,032), none skipped, 13 min 0 s in all |
| The same without the full-size image (`-m "not full_image"`) | 1,157 passed (128 and 1,029); run by the executor of 3.16 after its last change |
| The same on a computer without the Cellpose model (model folder set to an empty folder) | 1,154 passed (125 and 1,029), 6 skipped, 11 min 51 s |
| v1 imports in the main env (`image_utils`, `omero_tools` from `src/`, Python 3.9.23, Cellpose 3.1.1.2) | work as before |
| Main env | `conda env export` identical to the export stored with the reference run |
| v1 files (`environment.yml`, `image_utils.py`, `omero_tools.py`) | unchanged since `v1.0` |
| `msp-environment.yml` | one line added: `imagecodecs==2026.11.11`, already installed (3.13). `pyproject.toml` unchanged |
| Worker and `caffeinate` processes left after the tests | none |

Phase 3 "done when" (plan):

| Condition | Result | Entry |
|---|---|---|
| A full run on the test kit produces every output | yes | 3.6, 3.8 |
| Repeating the run from `run_config.yaml` gives the same tables | yes | 3.8 |
| The user has reviewed sample QC images and the log | the samples, made again, are with the user | below |
| The `workers: auto` estimate is confirmed with the QC outputs on | confirmed (3.9). The fixes change no step that holds a full-size channel in memory; the estimate was not measured again | 3.9 |
| The confirmed findings of 3.12 are fixed | findings 1 to 28, each with a test | 3.13–3.15 |
| The decisions after 3.12 are carried out | pixel types, pre-treatment order, exact cluster centres, cluster outlines, the final message, checksums: done. The rolling-ball radius is compared; the default waits for the user | 3.13–3.17 |

**What tasks 3.13 to 3.17 changed for a user**

- Images that are not 8-bit, 12-bit or 16-bit are refused with how to convert them, and a TIFF file whose own axes differ from the layout of the run fails with a message (3.13).
- The final QC shows only the cells of `cells.csv`; clusters are outlines; the elbow plot, the Cellpose QC figure and the calibration plot say what they show (3.14).
- The settings check refuses values the steps cannot use; `calibration.csv` has the column `elbow_threshold`; the last line of a run counts failed and skipped channels; `run_info.yaml` records the label and model files read (3.15).
- Cellpose pre-treatment clips after background subtraction; cluster centres are exact (3.16).
- 9,979 lines in `src/bigfish_pypeline/`, 1,160 tests.

**Deviations added to those of 3.11**

| # | Deviation | Entry |
|---|---|---|
| 12 | Now: the whole suite takes 13 min with the full-size image, against an aim of 8 minutes. | 3.8, here |
| 16 | 32-bit float images are refused, where the spec had them processed. User's decision; spec 5.3 and 13 changed. | 3.12, 3.13 |
| 17 | Clusters are drawn as outlines, not v1's filled shapes. User's decision. | 3.14 |
| 18 | Cellpose pre-treatment clips after background subtraction, where v1 clipped before, and sets values below 0 to 0 after background subtraction. User's decision; spec 5.7 changed. | 3.16 |
| 19 | Cluster centres always have decimals, in `clusters.csv` and in the `clusters` array of the `.npz` files, where v1 gave whole pixels with subpixel fitting off. User's decision; spec 5.6 and 8.2 changed. | 3.16 |
| 20 | `run_info.yaml` has the key `files_read` and four more package versions; `calibration.csv` has the column `elbow_threshold`. Spec 8.2 and 8.4 changed. | 3.15 |
| 21 | The measurements of 3.17 were made by the Opus executor, not by the orchestrator, who checked them with a separate script. | 3.17 |
| 22 | Three small changes were written by the orchestrator: the sentence on "Scale when converting" in the message for a refused pixel type, the rule that the elbow values cannot fail a channel with a given threshold, and the wording of one docstring. | 3.13, 3.15, 3.16 |
| 23 | A result that arrives in the same pass as a stop is not kept, and `run.log` gives the stop message at the end of the log. | 3.15 |

**Samples, made again** (`~/bigfish-testdata/phase3/samples/`, by `make_samples.py` in that folder; each has its `settings.yaml`, the text the terminal showed and the run folder):

| Sample | Folder | Shows |
|---|---|---|
| Test kit with its label file | `kit_label_files_png/` | elbow plot with the new axis, detection plot and final QC with cluster outlines (44 cells), `.npz` file |
| The same with the final QC as HTML | `kit_label_files_html/` | the interactive page |
| The same with `drop_border_cells` on | `kit_border_cells_dropped/` | the final QC with 26 cells; the log line "44 cells in the label image, 26 kept" |
| Test kit with Cellpose | `kit_cellpose/` | the Cellpose QC figure with "image after pre-treatment" and "no diameter set (image used at its own scale)" (43 cells; masks not judged) |
| Calibrated threshold, four small images | `calibrated_four_images/` | `calibration.csv` with `elbow_threshold`, the calibration plot |
| The same with a lower limit of 14 | `calibrated_lower_limit/` | three of the four images raised from 13 to 14, marked on the plot |
| Full-size image with Cellpose | `full_size_cellpose/` | the QC images at full size: 36,867 spots, 265 clusters and 1,287 cells, as in the run of 3.9 for this image; 6 min 7 s |

The crop's QC images: [elbow plot](figures/phase3/crop_ch2_elbow.png), [detection plot](figures/phase3/crop_ch2_detection.png), [final QC](figures/phase3/crop_ch2_final.png), [final QC with the border cells left out](figures/phase3/crop_ch2_final_border_cells_dropped.png); the calibration plots [without](figures/phase3/calibration_four_images.png) and [with a lower limit](figures/phase3/calibration_lower_limit.png).

Looked at by the orchestrator: every sample finished without a warning; the logs, `run_info.yaml` and `calibration.csv` hold the new items; the figures above and the full-size detection plot. The run folders of 3.9 named in 3.10 keep the old look of the figures.

**Points carried forward, added to those of 3.11**

Phase 4 and Phase 5:

11. `io.check_image` and `io.pixel_type_problem` check an image from its header; the notebook and the app should use them before reading pixels.
12. The final QC functions draw only the cells of the cells table they are given (3.14).
13. From the reviews: freeing Cellpose's GPU memory while an abandoned segmentation still runs; the check for damaged files is not made for use from several threads, which matters if the app reads images itself.

Phase 6 (documentation):

14. Converting an image to 16-bit in Fiji: the "Scale when converting" box, and a 16-bit signed image, which needs another route.
15. A Fiji hyperstack is stored `ZCYX`, so the layout of the run must say so.
16. The rolling-ball radius is in pixels, so the same setting means another size at another pixel size.
17. SNR values depend on the background method and on how far the ring lies from the spot; they cannot be compared between rolling-ball and top-hat runs.
18. The spot-radius formula for a confocal takes a very small pinhole; a spinning disk is nearer the widefield case. On the test image the radius is 0.99 px in Y and X, so a small change in wavelength or pixel size makes the detection window larger.
19. With decomposition and subpixel fitting both on, the spots of one focus are pulled towards the same peak.
20. The size of the HTML final QC (about 12 MB for a full-size image and channel).
21. With a nuclear label image the tables still say "cells", and spots above and below a nucleus count as nuclear.
22. The reference-spot picture is not the spot that decomposition fits; each QC picture sets its own contrast.
23. Counts above 2,000 spots change slightly with the image name (renamed files, a local copy against the OMERO image), because the seed comes from the name.
24. The defaults were checked on one specimen and its crops.
25. A manual threshold and a `min_spots` value chosen with top-hat do not carry over unchanged to rolling ball, at any radius: they should be checked again after a change of background method or radius (2.6, 3.17, 3.19).

Small points left as they are:

26. The calibration plot's axis shows decimals for whole-number thresholds.
27. The Cellpose QC figure counts every cell Cellpose found, also with `drop_border_cells` on.
28. In a run with label files, an image the runner marks failed has no segmentation status in `images.csv`.
29. If a later version of the OMERO library joins a session in another way, an ended session would be reported for each image as a connection problem; the tests with the real library would then fail (3.13).

**For the user to decide**

- The default rolling-ball radius for FISH channels (3.17). If it changes, `config.py`, the spec and the test kit's expected rolling-ball tables are updated before sign-off.
- Whether the tests may run in parallel (`pytest-xdist` in `msp-environment.yml`); the suite now takes 13 minutes.
- The sentence on "Scale when converting" in the message for a refused pixel type (3.13): keep it in the message, or in the documentation only.

**Manual checks for the user**

1. The samples above: the QC images, `run.log` and `run_info.yaml`. Are the pictures, the wording and the file names what you expect?
2. Open a label file written by a Cellpose run in Fiji, e.g. the one in `samples/kit_cellpose/` under `labels/`, and see that Image › Properties gives the pixel size in µm (3.15).
3. Try `bigfish-pypeline check` on a settings file with a value out of range, e.g. `alpha: 1.5`, and on a folder that holds a 32-bit image: are the messages clear?
4. Read the "choices the plan does not settle" and "changes in behaviour" in entries 3.13, 3.14 and 3.15.
5. The manual checks of 3.11 that are still open: the HTML final QC in a browser, and the test kit run from the command line.
6. Still open from Phase 2: the OMERO fix on the real server, which now also covers the new rejoining code of 3.13, and an image for the Cellpose mask review.

**Housekeeping**

- `~/bigfish-testdata/phase3/` holds 1.9 GB: 1.7 GB in `rolling_ball/` (1.6 GB of saved background results in its `cache/`, which can be deleted and made again) and 0.14 GB of samples.
- `docs/modularisation-streamlit-project/figures/` holds 5.6 MB, of which 1.9 MB is the rolling-ball comparison.
- `msp` is 44 commits ahead of GitHub: none of the Phase 3 work has been pushed.

**User's answers (26 Nov 2026):**

1. The default rolling-ball radius for FISH channels stays 5 px. Nothing changes in `config.py`, the spec or the test kit.
2. The samples are fine.
3. The sentence on "Scale when converting" stays in the message for a refused pixel type.
4. The tests may run in parallel: `pytest-xdist` is added to `msp-environment.yml`.
5. A label file written by a Cellpose run shows µm in Fiji.
6. Before sign-off, GPT-6.2 Astra (high effort, through Codex) reviews the work of tasks 3.13 to 3.18.

### 3.19 Fourth review (26 Nov 2026)

GPT-6.2 Astra (high effort), run through Codex in a read-only sandbox, reviewed the 14 commits of tasks 3.13 to 3.18 on `msp` (`25f8270` to `840e08f`) at the user's request. It could read the repository, the installed packages and `~/bigfish-testdata/`, and run small Python checks and single test files (100 tests passed in the files it ran). It changed nothing and contacted no OMERO server. Its advice was to hold the sign-off of Phase 3 until the first three findings are fixed.

It found a test for the original example of each of findings 1 to 28, and found the science of 3.16 (pre-treatment order, exact cluster centres) as the devlog states it. The findings below are cases the fixes of 3.13 to 3.15 do not cover, and claims that say more than the code does.

| # | Severity | Finding | Where | Checked by the reviewer |
|---|---|---|---|---|
| 29 | High | A TIFF file whose metadata gives axes that are not one of the five layouts (e.g. `YXC`) is read with the layout of the run, as if it gave none. A `YXC` file of shape 10 × 12 × 2 read as `CYX` gave a 12 × 2 picture that mixes the two channels, without a message. The check of finding 21 only compares two of the five layouts. | `io.py` (`_suggested_layout`, `_plane_sizes`) | run |
| 30 | High | When a worker is lost, results that came in after the pass was taken are collected only if they succeeded. A result that says the results cannot be written, or that the OMERO session has ended, is counted as one more lost image and tried again, so the run does not stop. | `batch.py` (`restart_pool`) | run |
| 31 | High | Any answer from the OMERO server when the session is rejoined is taken as "the session has ended", also an answer that the session service is not available. Only a refused session key shows that the session has ended. | `io.py` (`join_session`) | run, with a stand-in |
| 32 | Medium | A label file is read, then opened again for its checksum. If the file is replaced in between, `run_info.yaml` describes a file other than the one used. If the second reading fails, the labels already read are thrown away and the image gets no cell results. A custom Cellpose model is recorded after it is loaded. | `batch.py` (`process_image`, `prepare_cellpose`) | read |
| 33 | Medium | The pixel-type check looks at the type of the values after reading, not at the bit depth stored in the file. Packed 4-bit and 10-bit TIFF files are accepted, while the user's decision and the spec name 8, 12 and 16 bits only. | `io.py` (`_check_image`) | run |
| 34 | Medium | A stop reported by the Cellpose step is looked at only after the worker results of the same pass have been kept, which departs from "no further result is taken" (3.15, where the case is listed as not tested). | `batch.py` (`run_tasks`) | run |
| 35 | Medium | When the first image of a batch has a pixel type that is not accepted, the run stops before it starts, although the other images could be processed. Anywhere else in the list the image fails and the run goes on, as the plan and spec section 13 say. | `batch.py` (the check of the first image) | read |
| 36 | Medium | A colour (RGB) TIFF file is refused when it is read, but still counts when the number of workers is worked out. Part of finding 13 left open. | `batch.py` (`_will_be_refused`) | read |
| 37 | Medium | In a Cellpose run, an image that is segmented and then fails when the worker opens it (e.g. a FISH channel missing) has an empty segmentation status in `images.csv`. The fix of finding 17 covers images the runner marks failed, not this case. | `batch.py` (`process_image`) | read |
| 38 | Medium | Devlog 3.17 and point 25 of 3.18 say that from 10 px up a manual threshold chosen with top-hat carries over. On the exon channel 18 is the nearest whole threshold, not an equal count (24,631 against 24,570, 24,825 and 24,866), and on the intron channel the match for 30 is 32. | devlog 3.17, 3.18 | read |
| 39 | Low | "A curve without a bend gives no automatic threshold" (3.15) says too much: a straight falling line still gets a value from big-fish. What is handled is a curve of one point and a curve for which big-fish fails, such as a flat one. | `detection.py` (`_breaking_point`), devlog 3.15 | run |
| 40 | Low | The very last line in the terminal is "Run folder: …"; the line with the failed and skipped channels comes before it. Decision 5 asked for the final line. | `cli.py`, `tests/test_end_to_end.py` | read |

Also raised with finding 32 and left as it is: the label files of an image whose worker was lost are not in `files_read`. That image's results are thrown away, so `files_read` lists the files behind the results that were written.

**How each is fixed** (orchestrator's choices where the finding leaves one; tasks 3.20 and 3.21 in the plan):

- 29: axes given by the file's metadata must equal the layout of the run, whatever they are; only a file whose metadata gives no axes is read with the layout.
- 30 and 34: a reason to stop found in any result of the pass, or reported by the Cellpose step, stops the run before any other result of that pass is kept.
- 31: the session counts as ended only when the server refuses the session key or says that the session was removed or timed out; any other answer is a connection problem.
- 32: the checksum is worked out from the same bytes the labels are read from; the model file is recorded before it is loaded and checked again afterwards.
- 33: a TIFF file must store 8, 12 or 16 bits per pixel; other depths are refused with the usual message.
- 35: the check of the first image uses the first image whose pixel type is accepted; images of another type fail one by one, and the run stops before it starts only when no image can be used.
- 36: the number of workers leaves out every image that the header check of the reader refuses, by asking the reader itself.
- 37: the status is kept, as for finding 17.
- 38 and 39: the wording of 3.15, 3.17 and 3.18 is corrected below, and the docstring in `detection.py`.
- 40: the run folder is shown before the summary, so that the message with the counts is the last line.

**Corrections to earlier entries**

- 3.17 and 3.18, point 25: from 10 px up, 18 is the whole-number threshold whose count is nearest to top-hat's at 18 on the exon channel (within 1 %), where 5 px needs 17. On the intron channel the nearest match for top-hat at 30 is 30 at 5 px and 32 at the larger radii. A manual threshold therefore does not carry over exactly at any radius, and should be checked again after a change of background method or radius.
- 3.15, "Threshold": an elbow curve of one point, or one for which big-fish cannot give a value (such as a flat curve), gives "no automatic threshold". A straight falling line still gets big-fish's value, as in v1.

### Cultured-cell test image and task 3.23 planned (26 Nov 2026)

The user supplied an image of cultured cells for the Cellpose 4 mask review (spec, comparison 2): 31 planes × 4 channels × 2000 × 2000 px, 16-bit, pixel size 65 nm, Z-step 200 nm (given by the user; the file does not record it). Channels, counted from 0: DAPI, cell mask, exon smFISH probes (Quasar 570), intron smFISH probes. The full image, a substack of planes 12–30 and preview figures are in `~/bigfish-testdata/cultured_cells/`, with the scripts that make them.

**What the planes show:** in planes 0–11 the cells spread over the coverslip and the cell-mask stain of neighbouring cells overlaps into one sheet. From plane 12 upwards the cells stand apart with clear outlines, about 60–70 in the field. DAPI is sharpest in planes 9–12, and every nucleus is clear in the projection of planes 12–30. The exon channel holds many spots in planes 0–11, so cutting the stack would lower the counts per cell.

**Decisions by the user:**

- A setting that limits the projection for Cellpose to some planes, while spot detection uses every plane: task 3.23 in the plan, `segmentation.z_planes`, with planes counted from 0 like channel numbers.
- A small crop goes into the test kit, without the gene name in its file names, settings or README.
- The exon channel keeps ex 570 nm and em 610 nm, the values of the lab's other Quasar 570 settings (the v1 config of the tissue image, the brief's example), rather than the dye's peaks (about 548 and 566 nm).

**Test kit crop** (`tests/data/culture_DAPI_cellmask_exon_crop.tif`, settings in `culture_DAPI_cellmask_exon_crop_config.yaml`, described in `tests/data/README.md`):

- Top-left corner at y = 640, x = 1344, 384 × 384 px, every plane (31), channels 0–2, so the exon channel keeps index 2 as in the tissue crop. It holds three to four cells, two of which touch, and the lower planes overlap, so that task 3.23 can be tested on it.
- Saved with lossless (zlib) compression: 14.9 MB, against 27.4 MB without. Every plane is kept because the new setting needs the lower planes; 25 planes would have saved 3 MB. The package's reader gives the layout `ZCYX`, 65 nm pixels, a 200 nm Z-step and pixel values equal to the full image.
- Settings: Cellpose on channel 1 (maximum projection, rolling ball at 200 px before Cellpose, as the defaults), spots in channel 2 with an automatic threshold, rolling ball at 5 px and the default cluster settings. The file loads with `load_config`. No test uses the crop yet; the tests of 3.23 will. The existing tests select the tissue crop by name, so they are unchanged.

### 3.20 Reading images: fixes after the fourth review (26 Nov 2026)

Done by Opus 5.5 (medium) in `io.py` and `detection.py`, commit `dfc2087`. Each finding was first reproduced by a test that failed on the code as it was. The orchestrator read the changes and ran the reading and detection tests (219 pass); the whole suite is in 3.22.

- **Finding 29, axes given by the file.** Axes that a file's metadata gives must equal the layout of the run, whatever they are. The reviewer's `YXC` file read as `CYX` now fails: "`<file>`: the file's own information says its axes are stored in the order YXC, which does not match the layout CYX of this run (`image.axes` in the settings). Save the image with its axes in the order CYX." When the file's axes are one of the five layouts, the message still ends "or run it with the layout ZCYX".
- How `tifffile` 2026.11.16 reports each kind of file, checked with real files:

| File | Axes the file gives | Outcome |
|---|---|---|
| ImageJ hyperstack, T of length 1 | `ZCYX` (length-1 axes left out) | read as `ZCYX`; refused with another layout |
| OME-TIFF, T and C of length 1 | `ZYX` | read as `ZYX`; refused with another layout |
| Written by `tifffile` with axes `ZCYX` | `ZCYX` | read as `ZCYX`; refused with another layout |
| Written by `tifffile` with axes `YXC` | `YXC` | refused with the new message |
| Written by `tifffile` with axes `TCYX`, T of length 1 | `TCYX` (length-1 axis kept) | refused for its number of axes, as before |
| Written by `tifffile` without axes, plain TIFF, or ImageJ with only the number of images | none (`tifffile` gives stand-in letters `Q` or `I`) | read with the layout of the run, as before |
| Colour (RGB) file | – | refused as a colour image, as before |

- **Finding 31, OMERO session ended.** The session counts as ended only when the server refuses the session key (`PermissionDeniedException`), or says the session was removed or has timed out (those errors on their own, or named in the server's "cannot create session" answer). Any other answer, such as "session service unavailable", is a connection problem: "the OMERO server at `<host>:<port>` could not rejoin the session (CannotCreateSessionException: session service unavailable)", so that image fails and the next one tries to rejoin. Messages for an OMERO error now give the server's own reason, not only the error's name.
- What the installed OMERO library shows: a session key that the server no longer knows gives `PermissionDeniedException` (its command-line tool shows that reason for a session that cannot be attached); the server wraps other errors in a "cannot create session" answer with the error's name in it. **Not verified:** what the lab server really sends for an expired key, and whether a removed session arrives with its name in that answer. No server was contacted.
- **Finding 33, stored bit depth.** A TIFF file must store 8, 12 or 16 bits per pixel; packed 4-, 10- and 14-bit files are refused with the usual message ("the pixel type is 10-bit"). This reverses the note in 3.13 that packed 10- and 14-bit files were accepted. 12-bit values in a 16-bit file are a 16-bit file. `check` and the runner see the depth in the image header.
- **Finding 39.** The docstrings in `detection.py` say what gives "no automatic threshold": a curve of fewer than two points, or one for which big-fish cannot give a value. A test records that a straight falling line still gets big-fish's value.
