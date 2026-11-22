# MSP plan

How the work in `msp-spec.md` is carried out: who does what, and the tasks for the current phase. Each phase is planned in detail once the previous one has been merged into `main`, because it depends on that phase's results.

## Models and roles

| Role | Model and effort | Does |
|---|---|---|
| Orchestrator | Fable 5.2, high | Runs the main session. Breaks each phase into tasks, writes a short brief for each, reviews every change, runs the tests itself, compares results with v1, writes the devlog, and brings decisions to the user. |
| Main executor | Opus 5.5, medium | Code that changes results or where mistakes are easy to miss: pipeline steps, batch runner, reference runs, crop selection, label drafts, benchmarks. |
| Routine executor | Sonnet 5.5, high | Well-defined work with a clear check: env file, `pyproject.toml`, test set-up, generated test cases, documentation updates. |
| Explorer | Haiku 5.5 | Searching the repo and the web (spec section 3). |

Sonnet at high effort is enough for well-defined tasks; xhigh adds cost without a clear gain there. A task moves from Sonnet to Opus if its result needs correcting more than once.

**Starting a session:** `claude --model claude-fable-5-2 --effort high`, or choose the model and effort with `/model` in an open session. The orchestrator starts each executor as a subagent with the model and effort in the table above.

**Rules**

- Each task brief gives the goal, the spec sections, the files involved and the check that shows it is done. Executors get the brief, not the whole conversation.
- The orchestrator reviews the changes and runs the checks itself before committing to `msp`. An executor reporting that tests pass is not taken as proof.
- Executors never push, tag, edit `msp-brief.md`, `msp-spec.md` or this plan, or change the main `bigfish-pypeline` env.
- Results, version numbers, deviations from the spec and benchmark numbers go into `msp-devlog.md`, written by the orchestrator.
- Anything unclear goes to the user.

## Phase 0: Foundations

Done, signed off and merged into `main` on 22 Nov 2026. Results, deviations and the points carried forward are in `msp-devlog.md` (entries 0.1–0.11).

## Phase 1: Package and unified pipeline

Spec section 11, Phase 1. Pipeline: sections 5–8. Tests and edge cases: sections 12 and 13. Cellpose, QC images, `run_info.yaml`, `.npz` files and keep-awake belong to Phases 2 and 3.

**Ground rules for this phase**

- Each task adds its module and its tests (`tests/test_<module>.py`). Tests run with `conda run -n bigfish-msp python -m pytest`.
- `image_utils.py` and `omero_tools.py` stay exactly as they are until Phase 8, and `__init__.py` holds only the version. The v1 scripts and notebooks on `main` import them in the main env (Python 3.9), so they must keep working after each merge. New code goes into the modules of spec section 4.1.
- Comparisons with v1 use top-hat background and the reference settings (devlog 0.6 and 0.9).
- The LoG filter is run as in v1. `workers: auto` uses the memory measured in Phase 0 (about 5 GB per worker for a 2048 × 2048 × 35 channel); the final figure comes from Phase 2.

| # | Task | Done by | Check | User |
|---|---|---|---|---|
| 1.0 | Shared test helpers; decisions recorded | Orchestrator | `pytest` passes | Answer the decisions below |
| 1.1 | `psf.py`, `background.py`, `rolling_ball.py` | Opus 5.5, medium | Rolling ball matches the ImageJ fixture; top-hat and PSF match v1 | – |
| 1.2 | `config.py` | Sonnet 5.5, high | Test kit config loads; wrong settings give plain messages | – |
| 1.3 | `io.py`: local files | Opus 5.5, medium | Every layout reads correctly; file list as specified | – |
| 1.4 | `detection.py` | Opus 5.5, medium | Detected spots on the crop identical to v1 | – |
| 1.5 | `decomposition.py`, `subpixel.py`, `clusters.py` | Opus 5.5, medium | Spots and clusters on the crop identical to v1 | – |
| 1.6 | `measurements.py` | Opus 5.5, medium | SNR matches the posthoc script in 3D | – |
| 1.7 | `cells.py`; label files in `segmentation.py` | Opus 5.5, medium | Per-cell counts on the crop match the reference | – |
| 1.8 | `outputs.py`: tables and basic run folder | Opus 5.5, medium | Columns and `-1` rules as in spec 8.2 | – |
| 1.9 | One image through every step (`batch.py`) | Opus 5.5, medium | Tables for the crop agree with every v1 reference run | – |
| 1.10 | Batch runner (`batch.py`) | Opus 5.5, medium | Cancelled run and stopped worker leave combined tables | – |
| 1.11 | `cli.py`: `batch` and `check` | Sonnet 5.5, high | Both commands run on the test kit | – |
| 1.12 | End-to-end tests | Sonnet 5.5, high | Cases of spec sections 12 and 13 for this phase pass | – |
| 1.13 | OMERO input | Opus 5.5, medium, then the user | Tests without a server pass; session sharing works on the lab server | Run the check on the lab network |
| 1.14 | Full-size image comparison | Orchestrator | Detection identical to v1; other counts within the v1 run-to-run range | – |
| 1.15 | Phase review | Orchestrator, then the user | Phase 1 done-when met | Sign off; say when to merge |

**Order:** 1.1–1.3 together. Then 1.4 followed by 1.5, with 1.6–1.8 alongside. Then 1.9 → 1.10 → 1.11 → 1.12. Task 1.13 starts after 1.3 and finishes after 1.10, because the workers' part needs the runner. Task 1.14 follows 1.11.

**Decisions needed before the tasks start**

1. **OMERO server.** The archived app used host `10.34.168.89`, port 4064. Is this still the lab server, and may it be stored in the package (public repository)?
2. **Label files next to images.** Proposed rule: a file whose name ends in `_seglabels` is never listed as an image.
3. **Memory per worker.** Proposed: keep the LoG filter as in v1 and size `workers: auto` from the measured 5 GB, which allows two workers on a 16 GB laptop.

### 1.0 Test helpers

- `tests/conftest.py`: paths to the test kit and its v1 reference results; tests that need the full-size image are skipped when `BIGFISH_TEST_DATA` is not set.
- The answers to the decisions above go into the devlog.

### 1.1 PSF and background

- `rolling_ball.py`: copy of `imagej_rolling_ball.py` with a header naming the source repository and commit (devlog 0.10), with its ImageJ reference tests and fixture (0.3 MB) copied into `tests/`.
- `background.py`: `subtract_background(image, radius, light_bg=False, method="rolling_ball")`, applied plane by plane to 3D images and directly to 2D images; `tophat` as in v1.
- `psf.py`: `calculate_psf` as in v1.
- Checks: the ImageJ fixture tests pass; top-hat gives the same array as v1 `image_utils.subtract_background` on the crop; PSF values equal v1 for confocal, widefield and nipkow.

### 1.2 Config

- `pydantic` models for the layout in spec 6.2, with its defaults and the principles of 6.1: unknown settings rejected with a suggestion, `image.axes` and `image.voxel_size_nm` required, safe YAML loader, folders relative to the config file.
- Any number of channels; channel indices must not repeat.
- The `resolved` block (image list, calibrated thresholds) and the two ways of reusing a `run_config.yaml` (spec 6.3). Command-line values override the file.
- Checks: the test kit config loads unchanged; a config saved and loaded again is the same; each kind of mistake gives the message the spec describes.

### 1.3 Local image input

- File list: folder, filter, extension, top level only, sorted by name, label files left out (decision 2), stop when two inputs give the same output name.
- Reading with `tifffile`: layouts `ZCYX`, `CZYX`, `ZYX`, `CYX`, `YX`; only the chosen channels are read, numbered by their position in the file; a time axis of length 1 is dropped; several time points or positions are rejected.
- Voxel sizes from ImageJ or OME metadata, in nm; different X and Y sizes are reported; image size read from the file header without loading the pixels (used for the worker estimate).
- Checks: generated files in every layout and in 8-bit, 16-bit and 32-bit float read correctly; names with spaces and accents work; the crop reads as `ZCYX`, 11 × 3 × 384 × 384, 200 nm and 65 nm.

### 1.4 Spot detection

- Spot radius from the PSF, LoG filter, local maxima and thresholding as in v1, for 2D and 3D images.
- Threshold modes `manual` and `auto` with the lower limit; the elbow values are kept for the Phase 3 plot. No candidate spots gives zero spots, an empty threshold and a warning.
- The median used by `calibrated` mode, with unusable images left out and listed. Bailout.
- A generator of synthetic images with Gaussian spots at known positions, in `tests/`, shared by later tasks.
- Checks: on the crop, manual threshold 18 gives the 473 spots of v1 and auto gives threshold 13.0 and the 610 spots of v1, position for position; synthetic spots are all found within 1 px; a blank image gives none.

### 1.5 Decomposition, subpixel fitting and clusters

- As in spec 5.6, including the cases where decomposition is skipped and the two reference spots.
- The random seed is set before each reference spot from `run.seed`, the image name and the channel number, in a way that gives the same number in every process.
- Checks: on the crop, the four v1 general runs (manual and auto, subpixel on and off) are reproduced exactly (692 spots and 6 clusters; 869 and 6); two runs with the same seed give the same reference spot on a synthetic image with more than 2,000 spots; images with no spots and with very few are handled.

### 1.6 Spot measurements

- SNR from the posthoc script's `compute_snr_spots_individual`, extended to 2D; `log_intensity` from `rna_log` at the spot's own position.
- Checks: SNR values equal the posthoc function on the crop; synthetic 2D and 3D spots give the expected values; an empty or flat ring gives an empty value.

### 1.7 Cell assignment and label files

- Label files: read `<image>_seglabels.tif` from the label folder and accept only 2D whole-number labels of the image's Y × X size (spec 5.7). Cellpose is added to `segmentation.py` in Phase 2.
- Assignment by looking up each spot's pixel position, and each cluster's centre, in the label image, including positions on the image edge; `touches_border`; `drop_border_cells`; the cell table of spec 8.2.
- Checks: per-cell counts on the crop equal `per_cell_counts.csv` of the four subpixel-off reference runs; synthetic labels with adjacent cells, border cells and a cluster lying across a boundary; invalid label files are rejected.

### 1.8 Tables and run folder

- `spots`, `clusters`, `cells`, `images` and `calibration` tables with the columns and conventions of spec 8.2 (pixels and nm, Z columns only in 3D, `-1` for no cluster and no cell).
- Run folder of spec 8.1 without QC images, `.npz` and `run_info.yaml`: folder name with a number added when it exists, `run_config.yaml` with every default filled in, per-image files written under temporary names and then renamed, combined tables.
- Checks: column names and order; a 2D image has no Z columns; combining three per-image sets gives the expected rows; two runs with the same name get different folders.

### 1.9 One image through every step

- The function a worker runs for one image: read the FISH channels needed, run steps 1–8 and 10 for each channel, write that image's tables, return a summary row for each channel.
- Error handling for each channel and for the whole image (spec 7.3), bailout, warnings, and the warning when metadata disagree with the config.
- Checks: on the crop, the tables agree with all v1 reference runs and with the per-cell reference; in a generated three-channel image with one bad channel the other channels are kept; a 2D image runs.

### 1.10 Batch runner

- Run flow of spec 7.1 without Cellpose: checks before the run, run folder, pool of worker processes started with "spawn", an image handed over only when a worker is free, `run.log`, `progress.json`, combining at the end.
- Calibrated thresholds: the first pass over the subset, `calibration.csv`, values added to `run_config.yaml`.
- `workers: auto` (spec 7.2) from the Phase 0 measurement, with the number used and the reason logged.
- Cancel by Ctrl+C and by a `cancel` file; restart with half the workers after a worker stops, with one retry (spec 7.3).
- Repeating a run from its `run_config.yaml`.
- Checks: test kit run with one and two workers gives the same tables; a cancelled run and a run with a deliberately stopped worker leave combined tables for the finished images; a repeated run gives the same tables.

### 1.11 Command line

- `bigfish-pypeline batch` with its options and `bigfish-pypeline check` (spec 4.2), declared in `pyproject.toml`. Mistakes in a config are shown as plain messages. The `app` command is added in Phase 5.
- Checks: both commands run on the test kit from another folder; options override the file.

### 1.12 End-to-end tests

- `bigfish-pypeline batch` on the test kit, with and without label files, and on generated images: different sizes in one batch, a layout that differs from the config, a corrupt file, a blank image, a 2D image, three channels with manual thresholds, awkward file names, a missing label file, an output folder that cannot be written.
- A cancelled run, a deliberately stopped worker, and a repeated run.

### 1.13 OMERO input

- In `io.py`: images listed from a dataset ID or a list of image IDs; output names `<image ID>_<image name>` with characters Windows does not allow replaced; voxel sizes from the server in nm (from the archived app); default host and port (decision 1).
- `connect_to_omero` and `get_omero_image` are used as they are. A second helper lets workers join the session by its key and detach without closing it. One retry when the connection drops; a clean stop when the session has ended (spec 7.3).
- Checks without a server: tests with a stand-in connection.
- Check on the lab server, run by the user on the lab network with their own password, which is typed into the terminal and never passed to the orchestrator: the main process logs in, two workers join, each reads an image and detaches, and the main session still works afterwards. The user supplies an image or dataset ID to test with.

### 1.14 Full-size image comparison

- Local tests against `~/bigfish-testdata/reference_v1/full/`: detected spots identical to v1 (24,631 at threshold 18; 27,514 at the automatic threshold of 15.0); decomposed spots and clusters compared as counts, with the difference from v1 recorded next to v1's own run-to-run difference.
- One full batch run through `bigfish-pypeline batch`, with its time and peak memory noted.
- If a difference appears that v1's random reference spot does not explain, the v1 script is run in `bigfish-msp` to show whether it comes from the package versions or from the new code.

### 1.15 Phase review

- The orchestrator runs the whole test suite in a fresh shell, checks in the main env that the v1 imports still work, and writes the Phase 1 devlog entry with deviations and the manual checks for the user.
- The user reviews the devlog, signs off, and says when to merge.

**Done when** (spec): on the crop and the full-size image, detected spots are identical to v1; decomposed spots and clusters are identical on images with up to 2,000 spots, and compared as counts above that; per-cell counts on the crop match `extract_cell` for cells not touching the border; a cancelled run and a run with a stopped worker leave combined tables; and any difference from v1 is explained in the devlog.

## Open points

- **OMERO host and port** stored in the package: decision 1 of Phase 1.
- **An image for the Cellpose 4 mask review** (e.g. cultured cells), needed before Phase 8.

## Later phases

Planned in detail when the previous phase is merged. Usual split:

| Phase | Mostly done by |
|---|---|
| 2 Cellpose 4 and comparisons | Opus 5.5, medium |
| 3 Outputs, logs and QC | Opus 5.5, medium for the run record; Sonnet 5.5, high for QC figures |
| 4 Optimise notebook | Sonnet 5.5, high |
| 5 Streamlit app | Opus 5.5, medium |
| 6 Documentation | Sonnet 5.5, high; screenshots with `playwright-cli` |
| 7 Windows and Linux testing | Orchestrator, with the user on the lab machines |
| 8 Main env and release | Orchestrator, on the user's instruction |
