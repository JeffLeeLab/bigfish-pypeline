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

