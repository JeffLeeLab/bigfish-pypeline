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
| big-fish | 0.6.2, local fork in editable mode until the fork is tagged (0.5) | pip |
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

Fork: `/Users/jefflee/Documents/Incubator/big-fish`, branch `msp-patches` from `master` (0.6.2, commit `e951ea8`). Three local commits; not yet pushed or tagged.

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

Change 7 alters behaviour, not only a removed call: in the main env, png images with whole numbers of more than 8 bits keep their values, and with the patch they are rescaled to 8-bit. It sits in its own commit so it can be dropped.

Env change that followed: `mrc` 0.4.0 from pip replaces 0.3.1 from conda-forge (conda-forge has no 0.4.0). It fixes the 4 `.dv` failures.

pandas 3.1.1 stays: no failure is linked to pandas.

Smoke check of the functions the pipeline uses, which big-fish's tests do not cover, on a 35 × 512 × 512 crop of channel 2 with top-hat at 5 px: `log_filter`, `local_maximum_detection`, `automated_threshold_setting`, `spots_thresholding`, `remove_background_gaussian`, `build_reference_spot`, `modelize_spot`, `get_dense_region`, `precompute_erf`, `simulate_gaussian_mixture`, `fit_subpixel`, `detect_clusters`, `maximum_projection`, `save_image` (TIFF), `plot_elbow`, `plot_detection` and `extract_cell` all run without error in `bigfish-msp`. The check led to change 6. It does not compare numbers with v1; that is Phase 1.

Calls that still work but are due to be removed, left unchanged:

- `square`, `rectangle` (`stack/filter.py`): removed in scikit-image 0.27. Not used by the pipeline. The env keeps scikit-image below 0.27.
- `binary_dilation`, `binary_erosion`, `binary_opening` (`stack/filter.py`, `classification/features.py`): removed in scikit-image 0.28. `plot_cell` and `plot_segmentation_boundary` use `binary_dilation`.
- `region.mean_intensity` (`detection/dense_decomposition.py`), used by `simulate_gaussian_mixture`, which the pipeline calls; `convex_area`, `equivalent_diameter` and `remove_small_objects(min_size=)` in `segmentation/`: removed in scikit-image 2.0.
- `sklearn.utils.fixes.parse_version`: an internal scikit-learn helper that big-fish uses for its version checks.
- `deep_learning/` needs an old TensorFlow, which is not installed; the pipeline does not use it.

Found along the way, for task 0.9 and Phase 1: `multistack.extract_cell` stops with an `IndexError` when a subpixel coordinate rounds up to the image size (for example 511.5 on a 512 px image). This is in big-fish 0.6.2 itself and does not depend on package versions. The per-cell reference counts in 0.9 therefore use whole-pixel coordinates.
