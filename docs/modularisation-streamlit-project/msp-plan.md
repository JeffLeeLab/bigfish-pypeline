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

Spec section 11, Phase 3. Run folder: section 8.1. `.npz` files: section 8.2. QC images: section 8.3. Run record and log: section 8.4. Run flow: section 7.1. Keep-awake: section 7.3. Tests and edge cases: sections 12 and 13. The points carried forward are in devlog 1.15 and 2.8.

**Ground rules for this phase**

- As in Phase 2: each task adds its tests, run with `conda run -n bigfish-msp python -m pytest`; `image_utils.py`, `omero_tools.py` and the main env stay untouched; executors do not connect to an OMERO server.
- The tables must not change. The test kit's tables with every QC output on are the same as with all of them off, and still agree with the v1 reference.
- Each figure has one function that gives the figure and one that writes the file, so that the notebook (Phase 4) and the app (Phase 5) can show the same figures. Neither needs a screen, and neither changes the matplotlib set-up of a notebook or the app.
- A QC file that cannot be written gives a warning for that channel. It never fails the channel.
- QC files are written under temporary names and renamed with the image's tables. A cancelled or stopped run keeps the QC files of finished images only.
- Workers do not load `cellpose` or `torch` to draw a figure.
- Two executors never work in the same file at once: the tasks in `qc.py` (3.3, 3.4, 3.5) run one after the other, and so do the tasks in `batch.py` (3.1, 3.2, 3.6, 3.7).
- Figures shown in the devlog come from the crop only, because it is already public. Samples from the full-size image stay in `~/bigfish-testdata/phase3/`.

| # | Task | Done by | Check | User |
|---|---|---|---|---|
| 3.0 | Decisions recorded | Orchestrator | – | Answer the decisions below |
| 3.1 | Run record `run_info.yaml` (`outputs.py`, `batch.py`) | Opus 5.5, medium | Every item of spec 8.4 is in the file after a finished, a cancelled and a stopped run | – |
| 3.2 | `run.log` contents, `.npz` files, stray terminal lines | Opus 5.5, medium | Log items of spec 8.4 present; `.npz` arrays equal to the v1 reference files on the crop | – |
| 3.3 | Elbow plot and calibration plot (`qc.py`) | Sonnet 5.5, high | Files written; legend holds the threshold used | – |
| 3.4 | Detection plot and reference spot (`qc.py`) | Sonnet 5.5, high | Reference spot equal to the v1 reference file on the crop | – |
| 3.5 | Final QC as PNG and HTML (`qc.py`) | Sonnet 5.5, high | Both written for the crop, with and without cells | – |
| 3.6 | QC outputs in the batch runner (`batch.py`) | Opus 5.5, medium | Test kit run writes every output of spec 8.1; tables unchanged | – |
| 3.7 | Keep-awake | Sonnet 5.5, high | On macOS the computer is kept awake for the length of a run and released at its end | – |
| 3.8 | End-to-end tests | Sonnet 5.5, high | Cases of spec sections 12 and 13 for this phase pass | – |
| 3.9 | Time and memory with the QC outputs on | Opus 5.5, medium, then the orchestrator | Numbers in the devlog; `workers: auto` estimate confirmed or changed | Agree a change, if there is one |
| 3.10 | Sample QC images and logs | Orchestrator | Samples from the crop and the full-size image ready | Review the samples |
| 3.11 | Phase review | Orchestrator, then the user | Phase 3 done-when met | Sign off; say when to merge |

**Order:** 3.1 and 3.3 start together (different files). Then 3.2 follows 3.1, and 3.4 → 3.5 follow 3.3. Task 3.6 needs 3.2 and 3.5; then 3.7 → 3.8. Task 3.9 follows 3.6 and runs on its own. Task 3.10 follows 3.6.

**Check-ins with the user:** the decisions below; a first look at the final QC from the crop after 3.5, before it goes into the runner; a change to the workers estimate, if 3.9 finds one; the samples (3.10); the phase review (3.11).

**Decisions needed before the tasks start**

1. **Elbow plot in every threshold mode.** v1 wrote it in automatic mode only. Proposed: it is written whenever `outputs.qc.elbow_plot` is on, also with a manual or calibrated threshold, where it shows the threshold used and, as a second line, the value the elbow method would have chosen. This costs about 1.5 s for a full-size channel.
2. **Text on the cells in the final QC.** The spec asks for each cell's index and counts; on an image with many cells this cannot be read (the full-size image has about 1,300 Cellpose cells). Proposed: the PNG shows spots, clusters, cell outlines and, on each cell, its index and number of spots; the other counts are in `cells.csv` and appear on hover in the HTML version. Above 300 cells the PNG leaves the text out and says so in its title.
3. **Size of the HTML final QC.** Proposed: the image inside the file is the maximum projection in 8-bit with automatic contrast, at full size up to 2048 × 2048 px and reduced above that. The file size on the full-size image is measured in 3.5 and brought to the user if it is over 5 MB.

### 3.0 Decisions

- The answers to the decisions above go into the devlog.

### 3.1 Run record

- `run_info.yaml` with every item of spec 8.4: start and end time, pipeline version and git commit (when the package runs from a git folder), Python and package versions (big-fish, cellpose, torch, numpy, scipy, scikit-image, tifffile, omero-py), operating system, number of cores, memory, Cellpose device, workers and the reason, the command used, the random seed, worker restarts, final status, calibrated thresholds.
- The first part is written when the run folder is made and the rest at the end, also after a cancel or a stop (spec 7.1, steps 2 and 7). The file is written under a temporary name and renamed.
- Package versions are read without loading the packages, so that a run with label files still loads neither `cellpose` nor `torch`.
- The command: the command line as typed for `bigfish-pypeline batch`; a caller such as the app passes its own text.
- No session key, password or user name of OMERO in the file.
- Checks: each item present with the right kind of value; the file after a finished, cancelled and stopped run and after a worker restart; a fresh process that runs with label files has loaded neither `cellpose` nor `torch`.

### 3.2 Log, `.npz` files and terminal

- `run.log` is compared with the list of spec 8.4, item by item, and what is missing is added. Each warning names its image and channel.
- `.npz` files with `outputs.npz` on: `npz/<image>_ch<index>.npz` with the v1 keys of spec 8.2 (`spots_post_clustering` and `clusters`, or `spots` for a channel with clusters off). Written under a temporary name with the image's other files.
- big-fish's `FutureWarning` about `mean_intensity` no longer reaches the terminal (only that warning).
- Checks: on the crop with the v1 reference settings, the arrays equal those of `tests/data/reference_v1/` for the general and the HCR case; no `npz/` folder when the setting is off; a cancelled run leaves `.npz` files of finished images only.

### 3.3 Elbow plot and calibration plot

- `qc/<image>_ch<index>_elbow.png` from the elbow values `detect_spots` already returns: the curve, the threshold used with the legend "Selected threshold = 11.0", the lower limit when set, and what decision 1 adds. A channel for which big-fish gives no elbow values gets no plot and a warning.
- `qc/calibration.png` for a run with calibrated thresholds: for each calibrated channel, the automatic value of each image of the subset and the median used; images left out of the median are marked.
- Checks: files written for generated data in each threshold mode; the legend text; no candidate spots; one and several calibrated channels.

### 3.4 Detection plot and reference spot

- `qc/<image>_ch<index>_detection.png`: spots, and clusters when they are on, over the maximum projection, with the v1 look (big-fish's `plot_detection` with the v1 settings: orange circles for spots, cyan for clusters, automatic contrast). A 2D image is used as it is.
- `qc/<image>_ch<index>_referencespot.tif`: the reference spot `decompose_dense_regions` returns, saved as v1 did. Not written when decomposition is off or skipped.
- Checks: on the crop, the reference spot equals the v1 reference file; the plot is written with and without clusters, with no spots, and for a 2D image.

### 3.5 Final QC

- `qc/<image>_ch<index>_final.png`: spots, clusters and cell outlines over the maximum projection, with the text of decision 2. Without segmentation, or without usable labels, the figure is still written, without outlines.
- `qc/<image>_ch<index>_final.html` when `outputs.qc.final` is `html`: the same view made with plotly, which can be zoomed, with each cell's index and counts and each spot's values on hover (decision 3). The file opens without an internet connection.
- The functions take the tables and the label image, not the pipeline's own arrays, so that the app's Results page can build the view from a run folder (spec 10.4).
- Checks: both forms on the crop and on generated images with no cells, no spots and more than 300 cells; the HTML file holds the counts of `cells.csv`; file sizes for the crop and the full-size image recorded.
- The orchestrator shows the user the crop's final QC before 3.6.

### 3.6 QC outputs in the batch runner

- Each worker writes the QC files of its image and channel according to the switches of `outputs.qc`, and the main process writes `calibration.png` after the calibration pass.
- The elbow values are worked out during a run when the elbow plot is on (devlog 1.15, deviation 13).
- Temporary names, cancel, stop and a retried image as in the ground rules; a failed QC file gives a warning in `images.csv` and `run.log`.
- `run_config.yaml` of a repeated run gives the same tables, with the QC outputs on or off.
- Checks: the test kit run writes every file of spec 8.1; tables equal with all QC outputs on and off; each switch alone; a cancelled run; a stopped worker; a figure that fails; workers have loaded neither `cellpose` nor `torch`.

### 3.7 Keep-awake

- With `run.keep_awake` on: `caffeinate` on macOS for the length of the run, the system's keep-awake request on Windows, and a line in the log on Linux saying that it is not available (spec 7.3). It ends with the run, also after a cancel, a stop or an error, and when the main process is killed.
- `run.log` says whether the computer is being kept awake.
- Checks: on macOS a `caffeinate` process tied to the run exists during a run and is gone afterwards; the Windows and Linux paths with stand-ins. The real check on Windows is left to Phase 7.

### 3.8 End-to-end tests

- `bigfish-pypeline batch` on the test kit with every output on: every file of spec 8.1 is there, with `final` as `png` and as `html`.
- Repeat from `run_config.yaml`: same tables (spec 6.3).
- Calibrated thresholds: `calibration.csv` and `calibration.png` written, and not made again in the repeated run.
- Every QC switch off: no `qc/` files, same tables.
- A cancelled run and a run with a killed worker: no QC or `.npz` files of unfinished images, `run_info.yaml` complete with the right status.
- A run with Cellpose (stand-in model) and the final QC.

### 3.9 Time and memory with the QC outputs on

- Conditions and memory measure as in devlog 2.7, on the full-size image: one worker with every step and every QC output on, with `final` as `png` and as `html`, for one channel; the time each QC file adds.
- One whole run with Cellpose and every output on, for the peak of the main process and the worker.
- Result: the `workers: auto` estimate (38 bytes per voxel) confirmed, or a new figure proposed to the user. If a figure raises the worker's peak, the first answer is to draw it with less memory, not to raise the estimate.

### 3.10 Samples for the user

- Run folders from the test kit and the full-size image with every output on, in `~/bigfish-testdata/phase3/`, with label files and with Cellpose.
- The crop's QC images are copied to `docs/modularisation-streamlit-project/figures/phase3/` and linked from the devlog.
- The user looks at the QC images, `run.log` and `run_info.yaml`; changes asked for are made before the phase review.

### 3.11 Phase review

- The orchestrator runs the whole test suite in a fresh shell, with the full-size image and without the `cellpose` tests, checks in the main env that the v1 imports still work, and writes the Phase 3 devlog entry with deviations and the manual checks for the user.
- The user reviews the devlog, signs off, and says when to merge.

**Done when** (spec): a full run on the test kit produces every output; repeating the run from `run_config.yaml` gives the same tables; the user has reviewed sample QC images and the log. In addition, the `workers: auto` estimate is confirmed with the QC outputs on.

### Waiting on the user

None of these holds up Phase 3.

- **OMERO fix on the real server** (devlog 2.8, manual check 1): `bigfish-pypeline batch ~/bigfish-testdata/phase2/omero/omero_batch.yaml` on a day with a stable VPN.
- **Cellpose 4 mask review** (spec, comparison 2): needs an image that suits Cellpose-SAM (e.g. cultured cells). Must be done before Phase 8.
- The other manual checks of devlog 2.8.

## Later phases

Planned in detail when the previous phase is merged. Usual split:

| Phase | Mostly done by |
|---|---|
| 4 Optimise notebook | Sonnet 5.5, high |
| 5 Streamlit app | Opus 5.5, medium |
| 6 Documentation | Sonnet 5.5, high; screenshots with `playwright-cli` |
| 7 Windows and Linux testing | Orchestrator, with the user on the lab machines |
| 8 Main env and release | Orchestrator, on the user's instruction |
