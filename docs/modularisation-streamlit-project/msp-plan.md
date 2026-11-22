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

Spec section 11, Phase 0. Test image and labels: brief R6–R8.

| # | Task | Done by | Check | User |
|---|---|---|---|---|
| 0.1 | Commit the spec, archive the reviews, tag `main` as `v1.0`, create `msp` | Orchestrator | Done 22 Nov 2026 | Push `main`, `v1.0` and `msp` to GitHub |
| 0.2 | Local test-data folder and v1 copy of the code | Orchestrator | Files in place; v1 scripts start | – |
| 0.3 | Package skeleton, `tests/`, devlog | Sonnet 5.5, high | `pip install -e .` and `pytest` work | – |
| 0.4 | `msp-environment.yml` and the `bigfish-msp` env | Sonnet 5.5, high | Env builds; versions and device recorded | – |
| 0.5 | big-fish fork patches | Opus 5.5, medium | big-fish's own tests pass in `bigfish-msp` | Approve push and tag of the fork |
| 0.6 | v1 reference run on the full-size image | Opus 5.5, medium | Outputs, configs, commands and env export stored | – |
| 0.7 | Choose and save the crop | Opus 5.5, medium | Crop meets the spec's conditions | Pick the crop |
| 0.8 | Nuclear label image for the crop | Opus 5.5, medium, then the user | 2D, same Y × X as the crop, whole numbers ≥ 0 | Correct the labels |
| 0.9 | v1 reference run on the crop, with per-cell counts | Opus 5.5, medium | Reference outputs in `tests/data/` | – |
| 0.10 | Benchmarks on the full-size image | Opus 5.5, medium | Numbers in the devlog | – |
| 0.11 | Phase review | Orchestrator, then the user | Phase 0 done-when met | Sign off; say when to merge |

Task 0.6 uses the main env only, so it can run alongside 0.3–0.5.

### 0.2 Local test-data folder and v1 copy of the code

- Create `~/bigfish-testdata/` and copy into it:
  - the full-size image, from `~/Desktop/20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001.tiff`;
  - the earlier config, from `~/Documents/Laboratory/LCLIP/analysis_data/jim_stability/batch_script/smFISH_analysis_config.yaml`, saved as `jim_stability_smFISH_analysis_config.yaml`.
- `git worktree add ../bigfish-pypeline-v1 v1.0`, so the v1 scripts always run from the tagged code, whatever changes on `msp`.

### 0.3 Package skeleton

- `pyproject.toml` for `src/bigfish_pypeline` (version `2.0.0.dev0`), with `pytest` settings.
- `tests/` with one test that imports the package and reads its version.
- `docs/modularisation-streamlit-project/msp-devlog.md`, started with the Phase 0 heading.
- The existing `image_utils.py` and `omero_tools.py` stay as they are until Phase 1.

### 0.4 Environment

- `docs/modularisation-streamlit-project/msp-environment.yml` as in spec section 4.3, ending with `pip install -e .` for the package. Until the fork's tag exists (0.5), big-fish is installed from the local fork (`/Users/jefflee/Documents/Incubator/big-fish`) in editable mode.
- Build `bigfish-msp`. Record in the devlog the versions actually installed and the device PyTorch uses (Apple GPU expected).
- Set `BIGFISH_TEST_DATA=~/bigfish-testdata` as a variable of the `bigfish-msp` env (`conda env config vars set`), so it is set whenever the env is active.

### 0.5 big-fish fork

- In the fork, a branch `msp-patches` from `master` (0.6.2): guard the `selem` imports, replace `selem=` with `footprint=`, replace `np.int`, then run big-fish's own tests in `bigfish-msp` and fix what fails. Set the version to `0.6.2.post1`.
- After the user approves: push the branch and the tag `v0.6.2.post1` to `JeffLeeLab/big-fish`, switch the env file to `git+https://github.com/JeffLeeLab/big-fish.git@v0.6.2.post1` and rebuild the env once to confirm it installs.
- Every change to big-fish is listed in the devlog.

### 0.6 v1 reference run on the full-size image

- Run from the v1 copy (0.2) in the main env: the general and HCRv3 batch scripts on channel 2 only.
- Settings from the earlier config: voxel sizes 200 nm (Z) and 65 nm (YX), ex 570, em 610, NA 1.45, RI 1.45, confocal, top-hat background at 5 px, alpha 0.5, beta 1, cluster radius 600 nm, minimum spots 12.
- Runs: manual threshold 18 and auto threshold; subpixel fitting on and off; no segmentation.
- Store outputs, the config and command of each run and `conda env export` in `~/bigfish-testdata/reference_v1/full/`. If a v1 script cannot switch a setting without a code change, the devlog records exactly what was changed.

### 0.7 Crop

- Using the full-size reference spots, list candidate crops (256–384 px square, with a Z range) that hold several whole nuclei, well over 30 isolated spots away from the edges and a dense region, and whose nuclei stay separate in the DAPI projection.
- Show the user the two or three best candidates as projections (DAPI; exon with spots marked). The user picks one.
- Save channels 0–2 of the chosen crop to `tests/data/` (about 10 MB) with axes and voxel sizes in the ImageJ metadata, and write its config with the same settings as 0.6 (`confocal`, RI 1.45; the spinning-disk microscope counts as confocal).

### 0.8 Nuclear label image

- Draft a 2D nuclear label image from the crop's DAPI channel (maximum projection), with a threshold and watershed split or Cellpose 3's `nuclei` model in the main env, whichever looks better. Show the user an overlay.
- The user corrects it in Fiji, napari or the Cellpose GUI and saves it as `<crop>_seglabels.tif` in `tests/data/`.
- Check the saved file: 2D, same Y × X as the crop, whole numbers of 0 or more, 0 as background.

### 0.9 v1 reference run on the crop

- Same runs as 0.6, on the crop itself.
- Per-cell reference counts from big-fish `extract_cell` with the nuclear label image.
- Store in `tests/data/reference_v1/`: tables and `.npz` files the regression tests need, plus configs, commands and `conda env export`. Large QC images stay in `~/bigfish-testdata/reference_v1/crop/`.

### 0.10 Benchmarks

- In `bigfish-msp`, on channel 2 of the full-size image: time and peak memory of top-hat and rolling ball at 5 px, and of each v1 step (LoG, detection, decomposition, subpixel fitting, clusters).
- Rolling ball is taken for now from `misc/python-rolling-ball/imagej_rolling_ball.py` in JeffLeeLab/Image-analysis (the commit is noted). It is copied into the package in Phase 1.
- First estimate of memory per worker for a 2048 × 2048 × 35 channel.

### 0.11 Phase review

- The orchestrator runs `pytest` and big-fish's tests in a fresh shell and writes the Phase 0 devlog entry: installed versions, device, big-fish changes, reference runs, crop and labels, benchmark numbers, deviations, and the manual checks for the user.
- The user reviews the devlog, signs off, and says when to merge `msp` into `main`.

**Done when** (spec): big-fish's tests pass in `bigfish-msp`; the reference outputs, test kit and benchmark numbers are recorded; and `pytest` runs in `bigfish-msp`.

## Open points

- **OMERO host and port** stored in the package (Phase 1).
- **An image for the Cellpose 4 mask review** (e.g. cultured cells), needed before Phase 8.

## Later phases

Planned in detail when the previous phase is merged. Usual split:

| Phase | Mostly done by |
|---|---|
| 1 Package and unified pipeline | Opus 5.5, medium; Sonnet 5.5, high for config and file-discovery tests |
| 2 Cellpose 4 and comparisons | Opus 5.5, medium |
| 3 Outputs, logs and QC | Opus 5.5, medium for the run record; Sonnet 5.5, high for QC figures |
| 4 Optimise notebook | Sonnet 5.5, high |
| 5 Streamlit app | Opus 5.5, medium |
| 6 Documentation | Sonnet 5.5, high; screenshots with `playwright-cli` |
| 7 Windows and Linux testing | Orchestrator, with the user on the lab machines |
| 8 Main env and release | Orchestrator, on the user's instruction |
