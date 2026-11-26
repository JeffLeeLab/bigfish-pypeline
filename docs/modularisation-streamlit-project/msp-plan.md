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
| 3.12 | Independent reviews | Gemini 4 Neon (High) and GPT-6.2 Astra (medium), then the orchestrator | Findings checked and in the devlog | Answered: the decisions of 3.12 |
| 3.13 | Reading images: pixel types, layout of each file, OMERO rejoining (`io.py`) | Opus 5.5, medium | Only 8-, 12- and 16-bit accepted; a file whose axes contradict the layout fails; a dropped connection is not reported as an ended session | – |
| 3.14 | Fixes in the QC figures (`qc.py`) | Sonnet 5.5, high | Final QC with border cells dropped; large cell numbers; axis and panel labels; calibration plot | – |
| 3.15 | Fixes in the settings, the threshold and the runner (`config.py`, `detection.py`, `batch.py`, `cli.py`, `outputs.py`, `segmentation.py`) | Opus 5.5, medium | Each fix has a test; tables of the test kit unchanged | – |
| 3.16 | Cellpose pre-treatment and cluster centres (`segmentation.py`, `clusters.py`) | Opus 5.5, medium | Clip after background; no negative values after a mean projection; exact cluster centres, compared with v1 | – |
| 3.17 | Rolling-ball radius for FISH channels | Orchestrator, then the user | Comparison of 2.6 at 10, 15 and 25 px in the devlog | Choose the default radius |
| 3.18 | Phase review brought up to date | Orchestrator, then the user | Suite passes; numbers of 3.11 updated | Answered: radius stays 5 px, samples fine |
| 3.19 | Fourth review | GPT-6.2 Astra (high), then the orchestrator | Findings 29–40 in the devlog | – |
| 3.20 | Reading images: fixes after the fourth review (`io.py`, `detection.py`) | Opus 5.5, medium | Each fix has a test that fails without it | – |
| 3.21 | The runner: fixes after the fourth review (`batch.py`, `cli.py`, `segmentation.py`) | Opus 5.5, medium | Each fix has a test that fails without it; tables unchanged | – |
| 3.22 | Tests in parallel; review brought up to date | Orchestrator, then the user | Suite passes, also in parallel | Sign off; say when to merge |

**Order:** 3.1 and 3.3 start together (different files). Then 3.2 follows 3.1, and 3.4 → 3.5 follow 3.3. Task 3.6 needs 3.2 and 3.5; then 3.7 → 3.8. Task 3.9 follows 3.6 and runs on its own. Task 3.10 follows 3.6. After 3.12: 3.13 and 3.14 start together (different files); 3.15 follows 3.14, because the calibration plot shows the new column of `calibration.csv`; 3.16 follows 3.15 (both change `segmentation.py`). Task 3.17 changes no code and can run at any point, but not at the same time as a full-size test run or benchmark (memory). If the user chooses a new default radius, it is changed in `config.py` after 3.15. Task 3.18 comes last.

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

### 3.12 Independent review

- Gemini 4 Neon (High) reviews Phases 0–3 read-only, then Phases 0–2 on their own; GPT-6.2 Astra (medium, through Codex) reviews Phases 0–3 again. The orchestrator checks each finding against the code and records the result (devlog 3.12, findings 1–28).

**Decisions after 3.12** (answered by the user on 25 Nov 2026, devlog 3.12)

1. **Rolling-ball radius for FISH.** Only 5 px was compared with top-hat (2.6). The comparison of 2.6 is run again at 10, 15 and 25 px on the full-size image (both channels), and the default is chosen from it (task 3.17).
2. **Cellpose pre-treatment.** Clip after background subtraction instead of before, so that its value does not depend on the camera offset; and set the negative values of a mean projection to 0 after background subtraction, as already happens after a maximum projection (task 3.16).
3. **Cluster centres.** Always exact centres, instead of v1's whole-pixel centres when pixel sizes are whole numbers; the difference is recorded against the v1 reference (task 3.16).

**Decisions after the third review** (answered by the user on 25 Nov 2026, devlog 3.12)

4. **Cluster marks.** The detection plot draws clusters as filled cyan pentagons, as v1 does, which hide the spots of a bright focus (finding 28). Outlines only, in the detection plot and the final QC (task 3.14).
5. **Runs with failed images.** The command ends with 0 even when images failed, as its help says. It stays 0, and the number of failed and skipped channels is given in the final line in the terminal and in the message of `run_info.yaml` (task 3.15).
6. **Label files and custom models in the run record.** `run_config.yaml` names them by path only (F3). `run_info.yaml` also records each file's size, date and a checksum, so that a rerun can tell if one has changed (task 3.15).

### 3.13 Reading images

- Only 8-bit, 12-bit and 16-bit images are accepted (devlog 3.12, finding 1 and the user's decision). A 12-bit image is read as 16-bit, whether its values are saved in a 16-bit file or packed as 12-bit. Any other type (float, signed, 32-bit) is refused by `bigfish-pypeline check` and when an image is opened, for TIFF files and OMERO images, with a message naming the type found and saying how to convert the image (e.g. to 16-bit in Fiji, with a link).
- The image is refused before any work on it; in a batch run it is listed as failed with that message, and the run goes on.
- Checking an image's layout without asking for channels reads no pixel data (finding 14).
- Each TIFF file's own axes, when its metadata gives them, are compared with the confirmed layout. A file that does not match fails with a message naming both, and the run goes on (finding 21; spec section 13). A file whose metadata does not give its axes is read with the confirmed layout, as now.
- OMERO: the session is reported as ended only when the server says so. A connection that fails while the session is being rejoined is reported as a connection problem, and handled like a dropped connection (finding 23). `omero_tools.py` stays unchanged.
- `imagecodecs`, needed for packed 12-bit TIFFs, is added to `msp-environment.yml` so that reading them does not depend on Cellpose bringing it in.
- Spec sections on reading images and `check` updated by the orchestrator.
- Checks: float32, int16, int32 and uint32 TIFFs refused with the message, by `check` and in a run; an OMERO image of another type refused (stand-in, no server); a packed 12-bit TIFF and 12-bit values in a 16-bit file read with the right values and run to the end; the end-to-end test of pixel types changed to expect the refusal; 8-bit and 16-bit runs unchanged. A batch of a `ZCYX` and a `CZYX` file whose planes can be told apart: the second fails with the message. A stand-in for the OMERO library that answers "not joined" after a timeout: the run is not stopped with the ended-session message.

### 3.14 Fixes in the QC figures

- Final QC (PNG and HTML): when a cells table is given, only its cells are drawn, counted and labelled, so cells left out by `drop_border_cells` are not shown (finding 2). The app's Results page gets the same behaviour from the run folder.
- Final QC: cell numbers are worked with in a way that does not grow with the largest number, both for the outlines and for the spot counts, so a label file with numbers such as 100,000,000 draws normally (finding 7).
- Elbow plot: the axis says what is plotted: the natural log of the number of candidate spots above each threshold, smoothed, before spots sharing a peak are merged (finding 3).
- Cellpose QC figure: the first panel says it shows the image after pre-treatment (finding 8). With no diameter set, the title says the image was used at its own scale, not "diameter chosen by Cellpose" (finding 26); the test of that wording changes with it.
- Clusters drawn as outlines only, in the detection plot and the final QC (finding 28, decision 4).
- Calibration plot: images whose value was raised to the lower limit are marked, using the column added in 3.15 (finding 4).
- Checks: a final QC test with `drop_border_cells` on, for PNG and HTML; a label image with very large cell numbers; the labels; tables unchanged.

### 3.15 Fixes in the settings and the runner

- Settings: `decomposition.alpha` from 0 to 1; `decomposition.beta` above 0; background radius at least 1 px; no infinite or missing numbers; `clusters.min_spots` at least 2; `cellpose.min_size` −1 or more; `cellpose.model` not empty (findings 5 and 12). Each refused by `check` with a plain message.
- `calibration.csv`: a column with the elbow method's value before the lower limit, next to the value used (finding 4).
- A stopped run's message appears once in the terminal, at the end, and once in `run.log` (finding 6).
- `run.log`: "1 cluster" (finding 9); the spot radius in pixels for each channel; with `drop_border_cells` on, the number of cells found and the number kept (finding 20).
- `run_info.yaml`: the versions of pandas, scikit-learn, pydantic and plotly as well (finding 10). Spec 8.4 updated by the orchestrator.
- Once a stop is found, the runner stops without waiting for further results, and the files of every image not finished are removed, including a worker's image lost in the same pass (findings 11 and 15).
- Worker numbers leave out images that will be refused, such as time-lapse files (finding 13).
- Threshold (`detection.py`): an elbow curve too short to have a bend gives "no automatic threshold" with the usual warning, instead of failing. With a manual or calibrated threshold, the elbow plot cannot make the channel fail; the plot is drawn without an automatic value (finding 22).
- No setting accepts an infinite or missing number (`.inf`, `.nan`), including the threshold value and its lower limit (finding 25).
- A worker that stops just before the next image is handed out leads to the same restart with fewer workers, and that image stays in the queue (finding 24).
- The total time in `run.log` and the duration in `run_info.yaml` are the same figure (finding 27).
- The final line in the terminal and the message of `run_info.yaml` give the number of failed and skipped channels (decision 5). `run_info.yaml` records the size, date and checksum of each label file and custom Cellpose model read (decision 6); spec 8.4 updated by the orchestrator.
- Cellpose QC figure: the channel name, when there is one (finding 16).
- An image marked failed keeps its segmentation status and warnings in `images.csv` (finding 17).
- Label files written by the runner carry the pixel size, so that Fiji shows µm (finding 18).
- `log_intensity` written as whole numbers when the values are whole numbers; values unchanged (finding 19).
- Checks: a test for each, including a generated image whose elbow curve has one point, in automatic mode and in manual mode with the elbow plot on and off, and a worker that stops before an image is handed out; the test kit's tables unchanged apart from the text of `log_intensity`; the v1 comparison tests still pass.

### 3.16 Cellpose pre-treatment and cluster centres

- Cellpose pre-treatment runs in the order projection → background → clip → median → Gaussian. The clip value then applies to the image after background subtraction, so it no longer depends on the camera offset. The text that describes the pre-treatment (Cellpose QC figure, `run.log`) follows the new order.
- After background subtraction, values below 0 are set to 0 whatever the projection, so a mean projection gives no negative values to the filters and to Cellpose.
- Cluster centres are always exact (decimals), as big-fish gives them for decimal positions; spot positions in the spots table stay as they are (whole numbers when subpixel fitting is off).
- The spec sections on Cellpose pre-treatment and on clusters are updated by the orchestrator; the change from v1 goes in the devlog.
- Checks: the tests of 2.1 on pre-treatment changed to the new order, with an image whose camera offset is above the clip value; a mean projection with rolling ball gives no value below 0; on the v1 reference images the clusters and their spot numbers are the same as v1 and each centre is less than 1 px from v1's on each axis; the number of clusters whose cell changes is recorded in the devlog; the test kit's spot tables unchanged.

### 3.17 Rolling-ball radius for FISH channels

- The comparison of 2.6 is run again with rolling ball at 10, 15 and 25 px on the full-size image (exon channel 2, intron channel 3), with the same settings, thresholds, seeds and tables as 2.6, next to the results at 5 px and top-hat. Scripts and tables go in `~/bigfish-testdata/phase3/rolling_ball/`.
- The devlog records, for each radius: the automatic threshold, spots detected, spots after decomposition and clusters, and the run-to-run range where it decides a difference. The detection plots are compared at isolated spots and at dense foci, not only by totals.
- The user chooses the default radius for FISH channels. If it changes, `config.py`, the spec and the test kit's expected tables are updated, and the change is recorded in the devlog.
- Full-size runs go one at a time (memory), and not during a full-size test run.

### 3.18 Phase review brought up to date

- The orchestrator reruns the suite (in two parts, as in 3.11), updates the numbers and the deviations of 3.11, and records the fixes in the devlog.
- The points of 3.12 for later phases join the points carried forward: for Phase 5, freeing Cellpose's GPU memory while an abandoned segmentation runs, and the check for damaged files if the app reads images itself; for Phase 6, the rolling-ball radius in pixels, SNR depending on the background method and on the ring's distance from the spot, the confocal formula and a spinning disk, the spot radius near 1 px, subpixel fitting in dense regions, and the size of HTML final QC files; from the third review, a nuclear label image ("cells" are nuclei, and spots above and below a nucleus count as nuclear), the reference-spot picture against the fitted spot, contrast set for each picture, counts that change with the image name (renamed files, local against OMERO copies), and defaults checked on one specimen only.
- The user reviews the samples of 3.10 (redrawn where 3.14 changed a figure), signs off and says when to merge.

### 3.19 Fourth review

- GPT-6.2 Astra (high effort, through Codex) reviews tasks 3.13 to 3.18 read-only, at the user's request before sign-off. The orchestrator records the findings (devlog 3.19, findings 29–40) and how each is fixed.

### 3.20 Reading images: fixes after the fourth review

- Done by Opus 5.5, medium, in `io.py` and `detection.py`. Findings 29, 31, 33 and 39.
- Axes given by a file's metadata must equal the layout of the run, whatever they are (29). The OMERO session counts as ended only when the server refuses the key or says the session was removed or timed out (31). A TIFF file must store 8, 12 or 16 bits per pixel (33). The docstring on elbow curves says what is handled (39).
- Checks: a test for each that fails without the fix, starting from the reviewer's examples; 8-, 12- and 16-bit runs unchanged.

### 3.21 The runner: fixes after the fourth review

- Done by Opus 5.5, medium, in `batch.py`, `cli.py` and `segmentation.py`. Findings 30, 32, 34, 35, 36, 37 and 40. Runs at the same time as 3.20 (different files).
- A reason to stop found in any result of a pass, or reported by the Cellpose step, stops the run before another result is kept (30, 34). Checksums come from the bytes the labels are read from (32). The check of the first image uses the first image of an accepted pixel type (35). Worker numbers leave out every image the reader's header check refuses (36). An image that fails after its segmentation keeps its segmentation status (37). The message with the counts is the last line in the terminal (40).
- Checks: a test for each that fails without the fix; the test kit's tables unchanged.

### 3.22 Tests in parallel and the review brought up to date

- `pytest-xdist` is added to `msp-environment.yml` and to the env (user's answer, devlog 3.18). The orchestrator checks that the suite passes when run in parallel, with the full-size tests one at a time, and records the time.
- The orchestrator reruns the suite after 3.20 and 3.21, makes the samples again where a message or a figure changed, and updates devlog 3.18.

**Done when** (spec): a full run on the test kit produces every output; repeating the run from `run_config.yaml` gives the same tables; the user has reviewed sample QC images and the log. In addition, the `workers: auto` estimate is confirmed with the QC outputs on, the confirmed findings of 3.12 are fixed, and the decisions after 3.12 are carried out.

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
