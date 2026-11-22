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

Spec section 11, Phase 2. Segmentation: section 5.7. Run flow and workers: sections 7.1 and 7.2. Tests and edge cases: sections 12 and 13. The other QC images, `run_info.yaml`, `.npz` files and keep-awake belong to Phase 3.

**Ground rules for this phase**

- As in Phase 1: each task adds its tests, run with `conda run -n bigfish-msp python -m pytest`; `image_utils.py`, `omero_tools.py` and the main env stay untouched.
- Cellpose-SAM masks are not judged on the test image (brief R8). Tests check that the labels have the right form (2D, whole numbers, the image's size), not how good they are.
- Tests that need the Cellpose model are marked `cellpose` and are skipped when the model file is not on the computer. Tests never download it. Everything else is tested with a stand-in model, so the main test run stays fast.
- `cellpose` and `torch` are loaded only by the process that segments. Worker processes never load them.
- Benchmarks run one at a time, with no other task running.
- Executors do not connect to an OMERO server.

| # | Task | Done by | Check | User |
|---|---|---|---|---|
| 2.0 | Decisions recorded; test marker for Cellpose | Orchestrator | `pytest` passes | Answer the decisions below |
| 2.1 | Pre-treatment of the segmentation channel (`segmentation.py`) | Opus 5.5, medium | Each step gives the expected image on generated data | – |
| 2.2 | Device, model and segmentation (`segmentation.py`) | Opus 5.5, medium | Valid labels for the crop; no cells and errors handled | – |
| 2.3 | Cellpose QC figure (`qc.py`) | Sonnet 5.5, high | Four panels and the title written as a PNG | – |
| 2.4 | Segmentation in the batch runner (`batch.py`) | Opus 5.5, medium | Test kit run with Cellpose finishes; its `labels/` folder gives the same cell tables when reused | – |
| 2.5 | End-to-end tests with Cellpose | Sonnet 5.5, high | Cases of spec sections 12 and 13 for this phase pass | – |
| 2.6 | Rolling ball against top-hat | Opus 5.5, medium, then the orchestrator | Numbers and figures in the devlog | Review the comparison |
| 2.7 | Benchmarks and the final `workers: auto` estimate | Opus 5.5, medium, then the orchestrator | Numbers in the devlog; estimate updated and tested | Agree the final figures |
| 2.8 | Phase review | Orchestrator, then the user | Phase 2 done-when met | Sign off; say when to merge |

**Order:** 2.1, 2.2 and 2.6 start together (2.6 needs only the Phase 1 code). Then 2.3 → 2.4 → 2.5. Task 2.7 follows 2.4 and runs on its own.

**Check-ins with the user:** the decisions below; the final `workers: auto` figures (2.7); the rolling ball comparison (2.6); the phase review (2.8).

**Decisions needed before the tasks start**

1. **Label files given by the user.** Proposed: they are not copied into the run folder. `outputs.label_images` then applies to Cellpose labels only, and `run_config.yaml` and `run.log` name the label folder that was used.
2. **When the chosen device does not work.** Proposed: with `device: auto`, if the test calculation fails on the GPU, the next device is tried (CUDA, then Apple GPU, then CPU) and a warning is logged. With a device named in the config (`cuda`, `mps`), the run stops before processing with a plain message.
3. **Images for the rolling ball comparison.** Proposed: the full-size test image (exon channel 2 and intron channel 3) and the crop. Other kinds of image (e.g. HCR, cultured cells) can be added if you put them in `~/bigfish-testdata/`.

### 2.0 Decisions and test marker

- The answers to the decisions above go into the devlog.
- `pyproject.toml`: marker `cellpose`. `tests/conftest.py`: tests with this marker are skipped when `~/.cellpose/models/cpsam_v2` is missing.

### 2.1 Pre-treatment

- One function that turns the segmentation channel into the 2D image given to Cellpose, in the order of spec 5.7: Z projection (max or mean; a 2D image is used as it is) → clip (values above the clip value are set to it, as in the v1 tissue-culture script) → background subtraction (`background.subtract_background`; rolling ball at 200 px by default, or top-hat) → median filter → Gaussian filter.
- Checks: each step alone and all steps in order on generated images; 2D and 3D input; with every step off the projection is returned unchanged; rolling ball at 200 px on the crop's DAPI projection equals a direct call of `subtract_background`.

### 2.2 Device, model and segmentation

- Device: `auto` tries CUDA, then the Apple GPU, then CPU, with the workbook's test calculation on the chosen device before the model loads (decision 2). The device used is reported, with a warning when it is the CPU.
- Model: `CellposeModel(pretrained_model="cpsam_v2", use_bfloat16=False)` on that device, loaded once. An unknown model name, or a model that cannot be downloaded, gives a plain message.
- Segmentation: `eval` with the config's settings and `do_3D=False`. Returns `masks` (2D, uint32), what the QC figure needs, and the time taken. No cells gives an all-zero label image and a warning.
- Label files: written as `<image>_seglabels.tif` under a temporary name and then renamed, so that `read_label_file` accepts them.
- The call details are taken from the installed Cellpose 4.2.1.1, not from Cellpose 3 habits.
- Checks: with a stand-in model, the settings reach `eval`, and no cells and an error are handled; with the real model (marked `cellpose`), the crop's DAPI channel gives valid labels, and two runs on the same device give the same labels (recorded in the devlog if they do not); a process that only reads label files has not loaded `cellpose` or `torch`.

### 2.3 Cellpose QC figure

- `qc.py`: the workbook's `qc_figure`, taking its settings as arguments. Four panels (input, outlines, masks, flows); the title shows the image, projection, channel, pre-treatment, diameter, cell count and time.
- Written as `qc/<image>_cellpose_qc.png` without needing a screen, and switched by `outputs.qc.cellpose`.
- Checks: the file is written for a generated image with cells and with none; the title holds each item.

### 2.4 Segmentation in the batch runner

- Before the run: the segmentation channel is checked against the first image, the device is chosen and tested, and the model is loaded, so that a problem with any of them stops the run before processing. `bigfish-pypeline check` does not load the model.
- Run flow of spec 7.1, step 5: for each image in order, the main process reads only the segmentation channel (local file or OMERO), pre-treats it, segments it, saves the labels and the QC figure, and hands the image to a worker when one is free.
- A long segmentation (e.g. on CPU) does not hold up cancel, `progress.json` or the collection of finished images.
- Labels go to `labels/`, or to a temporary folder in the run folder when `outputs.label_images` is off; a temporary label file is deleted as its image finishes, and the folder is removed at the end, also after a cancel.
- If segmentation fails for one image, its spots are still written, cell-level results are skipped, and `segmentation_status` is `failed` with the reason. No cells: status `done`, `n_cells` 0, a warning.
- `run.log` names the model and the device, gives the CPU warning, and gives the segmentation time of each image. `progress.json` shows which image is being segmented.
- The thread settings made for the workers must not limit Cellpose on CPU to one thread. The number of threads it uses is set in the code; the final value comes from 2.7.
- `workers: auto` takes a larger reserve when Cellpose is on. The figure is a first estimate until 2.7.
- Checks, mostly with a stand-in model: the test kit run with one and two workers gives the same tables; cancel during a segmentation; a stopped worker with segmentation on; the temporary folder is gone afterwards; a second run with the first run's `labels/` as its label folder gives the same cell tables. With the real model: one test kit run from start to finish.

### 2.5 End-to-end tests

- `bigfish-pypeline batch` on the test kit with `source: cellpose` (marked `cellpose`).
- Through the runner with a stand-in model, on generated images: no cells, a failing segmentation, different sizes in one batch, a 2D image, `outputs.label_images` off, a cancelled run, a repeated run.
- No GPU: with `device: cpu` the run goes on with the warning about time (spec section 13).

### 2.6 Rolling ball against top-hat

- Images of decision 3, with the v1 reference settings and a fixed seed; only the background method differs.
- Numbers for each channel: the automatic threshold with each method; spots at the manual threshold and at each method's own automatic threshold; spots after decomposition and clusters; per-cell counts on the crop; how many spots both methods find (same position within 1 px) and how many only one finds; and, for a manual threshold used with top-hat, the rolling ball threshold that gives the same number of spots.
- Differences after decomposition are read against the run-to-run range of the random reference spot (devlog 1.14).
- Figures: the elbow curves of both methods on one plot; the spread of spot intensities; examples from the crop (a sparse region, a dense region, the edge of a nucleus) showing the raw image, each background result and the spots found with each. Image examples come from the crop only, because it is already public.
- Figures are kept in `docs/modularisation-streamlit-project/figures/phase2/` and linked from the devlog. Scripts and raw numbers go to `~/bigfish-testdata/phase2/`.
- The orchestrator checks the numbers on a sample and writes the devlog entry. The user reviews the comparison.

### 2.7 Benchmarks and the final workers estimate

- Conditions and memory measure as in Phase 0 (devlog 0.10), on the full-size image.
- Rolling ball through the package: each FISH channel at 5 px; the DAPI projection at 200 px.
- Cellpose-SAM on the 2048 × 2048 DAPI projection: time and memory to load the model; time and peak memory per image on the Apple GPU and on CPU (one thread and several); memory over five images in a row. Masks are not judged.
- One worker with every step switched on (decomposition, subpixel fitting, clusters, SNR, intensity, cell assignment), for one channel and for two channels in a row.
- One whole run of `bigfish-pypeline batch` with Cellpose on: time, and peak memory of the main process and of the workers.
- Result: the final memory per worker, the reserve with and without Cellpose, and the number of threads for Cellpose on CPU, proposed to the user. Once agreed, `choose_workers` and its tests are updated, and the difference from the 3–4 GB expected in spec 7.2 is recorded as a deviation.
- The QC figures of Phase 3 are not part of these measurements; the estimate is checked again there.

### 2.8 Phase review

- The orchestrator runs the whole test suite in a fresh shell, with and without the `cellpose` tests, checks in the main env that the v1 imports still work, and writes the Phase 2 devlog entry with deviations and the manual checks for the user.
- The user reviews the devlog, signs off, and says when to merge.

**Done when** (spec): the package tests pass and the rolling ball comparison is reviewed by the user. In addition, the benchmarks are in the devlog and the final `workers: auto` figures are agreed.

### Waiting on the user

Neither of these holds up Phase 2.

- **Cellpose 4 mask review** (spec, comparison 2): needs an image that suits Cellpose-SAM (e.g. cultured cells). When it arrives, the masks and QC figures are made with the code of 2.2 and 2.3 and shown to the user. Must be done before Phase 8.
- **OMERO check on the lab server** (left over from Phase 1): `python tests/manual/omero_session_check.py --image-id <ID>` in the `bigfish-msp` env, on the lab network. After it, a small real OMERO batch of two images, with Cellpose on once 2.4 is done.

## Later phases

Planned in detail when the previous phase is merged. Usual split:

| Phase | Mostly done by |
|---|---|
| 3 Outputs, logs and QC | Opus 5.5, medium for the run record; Sonnet 5.5, high for QC figures |
| 4 Optimise notebook | Sonnet 5.5, high |
| 5 Streamlit app | Opus 5.5, medium |
| 6 Documentation | Sonnet 5.5, high; screenshots with `playwright-cli` |
| 7 Windows and Linux testing | Orchestrator, with the user on the lab machines |
| 8 Main env and release | Orchestrator, on the user's instruction |
