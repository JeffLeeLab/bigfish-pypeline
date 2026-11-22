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
| mrc | 0.3.1 | conda-forge |
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

- `mrc` (conda-forge), which big-fish requires.
- Streamlit and `streamlit-image-coordinates` are left out until Phase 5.

Notes:

- The env file installs the pipeline with `-e ../..`, because conda runs pip from the folder that holds the env file, two levels below the repository root.
- Tests are run with `conda run -n bigfish-msp python -m pytest`. On this laptop `conda run -n bigfish-msp pytest` picks up a separate pytest in `~/.local/bin`, which cannot see the env's packages.
- Check: `python -m pytest` passes in `bigfish-msp` (1 test). The main env is unchanged (numpy 1.21.6, big-fish 0.6.2).
