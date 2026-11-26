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

Done, signed off and merged into `main` on 22 Nov 2026. Results, deviations and the points carried forward are in `msp-devlog.md` (entries 1.0–1.15). The OMERO check on the lab server was left as a follow-up (see "Waiting on the user" below).

## Phase 2: Cellpose 4 and comparisons

Done, signed off and merged into `main` on 24 Nov 2026. Results, deviations and the points carried forward are in `msp-devlog.md` (entries 2.0–2.8).

## Phase 3: Outputs, logs and QC

Done, signed off and merged into `main` on 26 Nov 2026, except task 3.23 below, which the user asked to have done after the merge. Results, deviations and the points carried forward are in `msp-devlog.md` (entries 3.0–3.22). Four independent reviews were made during the phase (entries 3.12 and 3.19, findings 1–40); all confirmed findings are fixed. The checks left to the user are listed in `msp-handoff.md`.

### 3.23 Planes for the segmentation projection

- Done by Opus 5.5, medium, in `config.py`, `segmentation.py` and `batch.py`, on `msp` after the Phase 3 merge (user's decision, 26 Nov 2026).
- Reason: in cultured cells the lower planes hold the cells spread over the coverslip, where the cell-mask stain of neighbouring cells overlaps into one sheet. Cellpose separates the cells better on a projection of the upper planes only, but the spots in the lower planes still belong in the counts.
- A new setting, `segmentation.z_planes`: the first and last plane of the projection made for Cellpose, counted from 0 like channel numbers, both included. Left empty, every plane is used, as now. Spot detection always uses every plane.
- The settings check refuses a first plane after the last. A plane number beyond an image's planes is found when the run is planned, in the check of every image (devlog 3.21): that image fails with a clear message, and the run stops before it starts when no image can be used. `run.log` and `run_config.yaml` record the planes used; the Cellpose QC figure shows the projection Cellpose received.
- The spec's list of settings gains `z_planes`.
- Checks: a test that the projection uses only the chosen planes; a run of the cultured-cell test kit (`tests/data/culture_DAPI_cellmask_exon_crop.tif`, planes 12–30) whose spot table is the same with and without the setting.
- The user looks at the Cellpose QC figure of the cultured-cell kit, and says when the task is merged into `main`.

## Phase 4: Optimise notebook

Planned on 26 Nov 2026. The user agreed the five proposals below the same day (devlog 4.0).

Spec section 9 (the notebook's steps) and section 11, Phase 4. Presets: section 5.2. Settings file: section 6. Run folder: section 8.1. Notebook test: section 12. The points carried forward are in devlog 2.8 (point 4), 3.11 (points 1 to 3), 3.18 (points 11 and 12) and in the entry for task 3.23.

**Ground rules for this phase**

- As in Phase 3: each task adds its tests; `image_utils.py`, `omero_tools.py` and the main env stay untouched; executors do not connect to an OMERO server.
- The notebook holds no pipeline code of its own. Each cell sets a few values, calls a function of the package and shows the result. What a setting means for a step is worked out in one place, used by the notebook, the batch and later the app.
- The tables of the batch must not change: the test kit's tables and the comparisons with v1 pass unchanged after every task.
- The notebook is committed without outputs, and a test checks this.
- The v1 notebooks stay where they are until Phase 8.
- Two executors never work in the same file at once.

| # | Task | Done by | Check | User |
|---|---|---|---|---|
| 4.0 | Decisions recorded | Orchestrator | – | Answered: the five proposals agreed |
| 4.1 | Steps of one channel as functions shared with the batch (`steps.py`, `batch.py`) | Opus 5.5, medium | Batch tables and v1 comparisons unchanged; each step can be run alone from a config | – |
| 4.2 | Starting a config: presets, and values suggested from the image (`config.py`) | Sonnet 5.5, high | Each preset gives the switches of spec 5.2; the result saves and loads | – |
| 4.3 | Views for choosing a threshold (`qc.py`) | Sonnet 5.5, high | Channel previews, LoG view with pixel values, line profile, histogram, LoG image saved as TIFF | – |
| 4.4 | Saving one image's results from a config (`batch.py`) | Opus 5.5, medium | The run folder of one image equals that image's part of a batch run | – |
| 4.5 | The notebook, steps 1 to 9 (`notebooks/bigfish-optimise.ipynb`) | Sonnet 5.5, high | Runs top to bottom on the tissue crop for one and for two channels | First look in JupyterLab |
| 4.6 | The notebook, steps 10 to 13 | Sonnet 5.5, high | Runs with Cellpose, with label files and without cells; saves the settings file | – |
| 4.7 | Notebook tests in the suite | Sonnet 5.5, high | Phase 4 done-when (spec section 11) on both test kits | – |
| 4.8 | Phase review | Orchestrator, then the user | Suite passes; notebook tried by the user on their own image | Sign off; say when to merge |

**Order:** 4.3 can start at once (`qc.py` only). Tasks 4.1 and 4.2 wait for task 3.23, which changes the same files; 4.1 then runs on its own in `batch.py`, because it changes the code that makes the results, and 4.4 follows it. Task 4.5 needs 4.1 to 4.3; 4.6 needs 4.4 and 4.5; then 4.7 and 4.8.

**Check-ins with the user:** the decisions below; a first look at the notebook after 4.5, before the segmentation and saving steps are added; the phase review (4.8).

**Decisions, agreed by the user as proposed**

1. **A new module, `steps.py`.** The batch works through a channel in one function. The notebook needs the same steps one at a time, with the same reading of the settings (which threshold, which seed for the reference spot, which positions the clusters are built on). Proposed: these steps move into a module `steps.py`, which the batch, the notebook and later the app's Optimise page all call. The spec's list of modules (4.1) gains one line. The other route, the notebook calling the lower-level functions itself, would repeat that reading of the settings in the notebook, where it could drift from the batch.
2. **Saving from the notebook (step 12).** Proposed: the notebook saves an image's results by running that one image through the same function as the batch, with the settings chosen in the notebook, into a run folder of the usual layout. The saved results are then those a batch gives, and the notebook test also checks that they equal what the notebook showed step by step.
3. **Calibrated threshold in the notebook (step 7).** A calibrated threshold comes from several images. Proposed: the notebook shows the automatic threshold of the open image, and a separate, optional cell runs the calibration over the images whose names contain the filter and shows the calibration plot. On full-size images that cell takes about as long as a batch run's calibration.
4. **OMERO in the notebook.** Proposed: one cell asks for the password in the notebook's own password box (it is neither shown nor saved), and the session is closed by the last cell. The tests use stand-ins for the server; the check on the real server is the user's, with the batch check still open.
5. **Memory.** One full-size channel with its filtered copies needs about 5 GB. Proposed: the notebook keeps one channel's images in memory at a time and frees them when the channel is changed; settings and tables of earlier channels are kept.

### 4.1 Steps shared with the batch

- `steps.py`: one function for each of steps 2 to 8 and 10 of spec 5.1, taking the config, the channel's settings and the images or positions of the step before, and returning what the next step and the QC figures need. The batch's own function for a channel becomes a sequence of these calls.
- Nothing else changes in the batch: the order of the steps, when images are freed, the warnings, the bailout and the QC material stay as they are.
- Checks: the whole suite, with the v1 comparisons and the full-size tests; for each step, a test that calls it alone on the tissue crop; time and peak memory of a full-size channel within the spread of devlog 3.9.

### 4.2 Starting a config

- A function that gives a complete config from the two preset choices of spec 5.2 (assay type for each channel; per-cell results), the layout and voxel sizes confirmed by the user, and the channels. Presets set switches only.
- A function that suggests the layout and voxel sizes from an image's header, for the user to confirm or edit. Images are checked from their header with `io.check_image` before any pixel is read (devlog 3.18, point 11).
- A numbered list of the images in a folder that match a filter, for local input, and of the images of a dataset, for OMERO.
- Checks: each preset; the result passes the settings check, saves and loads; a suggestion for a file with and without metadata.

### 4.3 Views for choosing a threshold

- In `qc.py`, each as a function that gives a figure: maximum-projection previews of every channel with automatic contrast; the LoG image as an interactive view with the pixel value under the pointer; `plot_line_profile(rna_log_mip, start=(y, x), end=(y, x))`; a histogram of the LoG values with the threshold marked. A function that saves the LoG projection as a TIFF file for ImageJ.
- The interactive view is reduced for large images in the way the HTML final QC is, so that the notebook stays usable with a full-size image.
- Checks: each figure is made from generated data and from the crop without a screen; the line profile holds the pixel values along the line; the saved TIFF opens with the right pixel size.

### 4.4 Saving one image's results

- A function that runs one image through the batch's own steps with a given config and writes a run folder of the usual layout (spec 8.1), with the tables, label image, QC files, `run_config.yaml`, `run_info.yaml` and `run.log`. It runs in the notebook's own process, without workers.
- Cellpose masks made in the notebook are used as they are; they are not made a second time.
- Checks: for the tissue crop and the cultured-cell crop, the tables equal those of `bigfish-pypeline batch` with the same settings file.

### 4.5 The notebook, steps 1 to 9

- `notebooks/bigfish-optimise.ipynb`, steps 1 to 9 of spec section 9: introduction, imports and versions, preset and image source, image information, channel choice, background and LoG, threshold, and the later steps of a channel, each left out when switched off. Each step has one short cell of values that are written into `config`.
- Text between the cells says what to look for and which value to change, in plain words for biologists.
- Checks: the notebook runs top to bottom on the tissue crop; with a second channel chosen, both channels' settings are in `config`.

### 4.6 The notebook, steps 10 to 13

- Segmentation with Cellpose or a label file, with the 4-panel figure; every Cellpose setting of the config, with `max_size_fraction` and `z_planes` (devlog 2.8, point 4; task 3.23).
- Cell assignment and the final QC; saving this image's results (4.4); batch settings with their defaults (input folder = folder of the open image, workers = auto); saving the settings file, and the command that runs it.
- Checks: top to bottom with Cellpose (skipped without the model, as the other Cellpose tests), with label files and without cells.

### 4.7 Notebook tests

- The suite runs the notebook on the tissue crop and on the cultured-cell crop, with the values of its cells replaced by the test's.
- The settings file it saves runs unchanged through `bigfish-pypeline batch`, and the tables equal those the notebook saved for that image (Phase 4 done-when).
- A test that the committed notebook holds no outputs and no personal paths.

### 4.8 Phase review

- The orchestrator runs the suite, reads the notebook as a new user would, and writes the review in the devlog.
- The user tries the notebook in JupyterLab on an image of their own, local and, if the VPN allows, from OMERO.

## Later phases

Planned in detail when the previous phase is merged. Usual split:

| Phase | Mostly done by |
|---|---|
| 5 Streamlit app | Opus 5.5, medium |
| 6 Documentation | Sonnet 5.5, high; screenshots with `playwright-cli` |
| 7 Windows and Linux testing | Orchestrator, with the user on the lab machines |
| 8 Main env and release | Orchestrator, on the user's instruction |
