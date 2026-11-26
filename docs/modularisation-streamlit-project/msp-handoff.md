# MSP handoff

Where the work stands, for whoever picks it up next. Updated 26 Nov 2026. Details are in `msp-devlog.md`; tasks are in `msp-plan.md`.

## State

- **Phases 0, 1, 2 and 3:** done, signed off, merged into `main` and pushed. Phase 3 (outputs, logs and QC) was signed off and merged on 26 Nov 2026 (devlog 3.22, at its end). Its record: tasks in devlog 3.1–3.11, three independent reviews in 3.12 (findings 1–28) with their fixes in 3.13–3.17, the review of the phase in 3.18, a fourth review in 3.19 (findings 29–40) with its fixes in 3.20 and 3.21, and the state at sign-off in 3.22.
- **Task 3.23** (the setting `segmentation.z_planes`, planes for the Cellpose projection): done and committed on `msp` (devlog 3.23), not merged. The user looks at the two Cellpose QC figures of the cultured-cell crop (`figures/phase3/z_planes/`) and says when it is merged into `main`.
- **Phase 4 (Optimise notebook):** planned in `msp-plan.md`; the user agreed its five decisions (devlog 4.0). Tasks 4.1 (steps shared with the batch, `steps.py`), 4.2 (starting and changing a config) and 4.3 (views for choosing a threshold) are done (devlog 4.1 to 4.3). Tasks 4.4 to 4.8 are open.
- **OMERO:** the fix for a dropped connection and for the session key in the terminal is committed and tested with stand-ins for the server only (devlog, "OMERO fix: second try and a clean terminal"). The check on the real server is still to be run by the user.
- 1,488 tests pass in `bigfish-msp` with the full-size image (devlog 4.1). Run the suite in parallel, in two commands, about 5 and a half minutes in all: `conda run -n bigfish-msp python -m pytest -n 6 -m "not full_image"`, then `conda run -n bigfish-msp python -m pytest -m full_image` (the full-size tests need about 5 GB each and must not run side by side). One test at a time the suite takes 13 minutes, and a foreground command is cut off after 10 minutes, so run it in the background.
- `msp` is ahead of `main` and of GitHub by the commits of task 3.23 and Phase 4; nothing after the Phase 3 sign-off is merged or pushed.

## Next step

1. Phase 4, as planned in `msp-plan.md`: task 4.4 (saving one image's results, `batch.py`) and task 4.5 (the notebook, steps 1 to 9) can run side by side; then the user's first look at the notebook in JupyterLab, before 4.6.
2. When the user has looked at the Cellpose QC figures of task 3.23 and says so: merge `msp` into `main` and push (ask first, as always).

## How the work is run

- The orchestrator briefs each executor (goal, spec sections, files, check), reviews every change, runs the checks itself, commits to `msp` after each task and writes the devlog. Models and effort are in the plan; no other executors are used.
- The user is asked at each check-in in the plan and whenever something is unclear. Phase 3 check-ins: the decisions (3.0), a first look at the final QC (after 3.5), a change to the workers estimate if there is one (3.9), the samples (3.10), the phase review (3.11).
- Nothing is pushed, tagged or merged without asking.
- Cellpose mask quality on the test image is not brought to the user (brief R8).

## Waiting on the user

- **OMERO on the real server, on a day with a stable VPN:** rerun `bigfish-pypeline batch ~/bigfish-testdata/phase2/omero/omero_batch.yaml` (images 5806 and 5795, username already set) to see both images finish, the "rejoining" line if the connection drops, and no session key or `WARNING:` lines in the terminal. The rejoining code changed in 3.13 and 3.20; what the server sends for an expired session key could not be checked without it.
- **The Cellpose 4 mask review** on the cultured-cell image in `~/bigfish-testdata/cultured_cells/` (planes 12–30), after task 3.23 and before Phase 8.
- **Manual checks of the Phase 3 review** that the user has not reported on (devlog 3.18 and 3.22): the HTML final QC in a browser, `check` on a settings file with a value out of range and on a folder with a 32-bit image, and the "choices the plan does not settle" in 3.13 to 3.15, 3.20 and 3.21.
- **Manual checks of the Phase 2 review** (devlog 2.8): Cellpose on the test kit, a look at a full-size run folder, and the "choices the spec does not settle" in 2.1, 2.3 and 2.4.
- Optional checks from the Phase 1 review that the user has not reported on: trying `check` and `batch` on the test kit, and reading the "choices the spec does not settle" in devlog 1.2, 1.3, 1.8, 1.9 and 1.10.

## Files outside the repository (this laptop)

| Path | Holds |
|---|---|
| `~/bigfish-testdata/` | The full-size test image; set `BIGFISH_TEST_DATA` to this folder for the `full_image` tests |
| `~/bigfish-testdata/cultured_cells/` | The cultured-cell image for the Cellpose 4 mask review, a substack of planes 12–30, previews, and the scripts that make the substack and the test kit crop |
| `~/bigfish-testdata/reference_v1/` | v1 reference results for the full-size image |
| `~/bigfish-testdata/benchmarks/phase0/` | Phase 0 benchmark scripts and numbers, the pattern for task 2.7 |
| `~/bigfish-testdata/benchmarks/phase2/` | Benchmark scripts, logs and numbers of task 2.7 |
| `~/bigfish-testdata/benchmarks/phase3/` | Benchmark scripts, logs and numbers of task 3.9, and a full-size run folder with every output |
| `~/bigfish-testdata/phase3/samples/` | Sample run folders for the user's review, made again on 26 Nov 2026 (devlog 3.18), with the script that makes them |
| `~/bigfish-testdata/phase3/samples_3.14/` | The QC figures changed by task 3.14, drawn from the crop, with the script that makes them |
| `~/bigfish-testdata/phase3/rolling_ball/` | Scripts, logs and tables of the rolling-ball radius comparison (task 3.17), with a copy of the package at commit `25f8270` |
| `~/bigfish-testdata/phase1/` | Full-size runs of Phase 1 and the v1 scripts run in the new env |
| `~/bigfish-testdata/phase2/` | Scripts, tables and logs of the rolling ball comparison (task 2.6) |
| `~/bigfish-testdata/phase2/omero/` | Config and run folder of the real OMERO batch |
| `../bigfish-pypeline-v1` | The v1 code at tag `v1.0`, for comparisons in the main env |
| `~/Documents/Tools/Image-analysis/Segmentation/Cellpose-SAM-AppleM1/cellpose-sam-workbook.ipynb` | The Cellpose-SAM workbook that tasks 2.1–2.3 follow |
| `~/.cellpose/models/cpsam_v2` | The Cellpose model, already downloaded |

## Worth knowing

- Only 8-bit, 12-bit and 16-bit images are read (for a TIFF file, 8, 12 or 16 bits stored per pixel); other pixel types are refused with how to convert them. A TIFF file whose own axes differ from the layout of the run fails (a Fiji hyperstack is always `ZCYX`) (devlog 3.13, 3.20).
- Every image is checked from its header when a run is planned. A run stops before it starts only when no image can be used; an image that cannot be used fails on its own, and `check` lists it (devlog 3.21).
- The final QC shows only the cells of `cells.csv`, and clusters are drawn as outlines (devlog 3.14).
- Cellpose pre-treatment clips after background subtraction, and cluster centres always have decimals (devlog 3.16). Both depart from v1 by the user's decision.
- An executor cut off by a lost connection can be resumed with its context by sending it a message; its edits stay in the working tree.
- Another session may commit to `msp` while executors work (the cultured-cell crop and task 3.23 arrived that way). Read `git log` before rewriting a section of this file or of the plan, and change only the lines that are yours.

- The user reviewed the rolling ball comparison and kept rolling ball as the default for FISH channels (devlog 2.6). It gives about a third more clusters than top-hat on the full-size exon channel, because decomposition places more spots in each bright focus on the rolling ball image.
- OMERO output names leave out a `.tif` or `.tiff` ending (user's decision, devlog): image 5806 gives `5806_20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001`.
- `bigfish-pypeline batch` does not ask for the OMERO username; it must be in the settings file (`run.input.omero.username`). Only the password is asked for.
- Over the VPN, reading one full-size channel from OMERO took 23 to 50 s, and Cellpose-SAM took about 49 s per full-size image on the Apple GPU.
- The full test suite takes over 5 minutes: run it in the background, so that the user can ask for progress without stopping it.
- `conda run` does not pass typed or piped input: put scripts in files and run those.
- The laptop has 17 GB of memory and often only about 4 GB free. One worker needs about 5 GB for a full-size channel, so full-size runs and benchmarks go one at a time.
- PyTorch 2.14.1 in `bigfish-msp` can use the Apple GPU.
- v1 does not give the same result twice above 2,000 spots, because its reference spot is built from a random sample. The new code fixes the seed, so full-size comparisons with v1 after decomposition are counts within v1's own range (devlog 0.6, 1.14).
- Subpixel positions differ slightly from v1 because of the newer packages, not the new code. The user accepted this; the exact comparison is with `tests/data/reference_v1_new_env/` (devlog 1.5).
- During a batch run the main process sets the thread variables to 1 for the workers. Cellpose on CPU in that process must not be limited by this (plan 2.4).
- Two executors must not work in the same file at once: 2.1 and 2.2 both edit `segmentation.py`, so they were run one after the other.
- Cellpose removes masks larger than a fraction of the image. The user asked for a setting: `segmentation.cellpose.max_size_fraction`, default 0.4 (devlog, "Mask size limit for Cellpose"). It is not in the spec; the notebook (Phase 4) and the app (Phase 5) should offer it with the other Cellpose settings.
- Cellpose 4.2.1.1 loads `cpsam_v2` without an error when given an unknown model name; the package checks the name itself (devlog 2.2).
- Once the main process has rejoined an OMERO session after a drop, nothing keeps the session alive except the reads of the run (devlog, OMERO fix). Keep-alive in the batch process is a Phase 5 point.
- `workers: auto` uses 38 bytes per voxel of one channel for each worker (5.6 GB for a full-size channel), with 2 GB kept free and 3 GB more with Cellpose. With Cellpose on the CPU it leaves 4 cores to Cellpose. With little free memory it runs one worker with a warning. Final figures, agreed by the user (devlog 2.7); checked again in Phase 3 with the QC figures.
