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
