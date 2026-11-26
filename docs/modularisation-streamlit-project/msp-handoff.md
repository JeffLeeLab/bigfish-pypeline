# MSP handoff

Where the work stands, for whoever picks it up next. Updated 26 Nov 2026. Details are in `msp-devlog.md`; tasks are in `msp-plan.md`.

## State

- **Phases 0, 1 and 2:** done, signed off, merged into `main` and pushed. Phase 2 was signed off and merged on 24 Nov 2026 (devlog 2.8).
- **Phase 3 (outputs, logs and QC):** every task is done and committed on `msp`. Tasks 3.1 to 3.11 are in devlog 3.1–3.11. Three independent reviews (devlog 3.12, findings 1–28) led to tasks 3.13 to 3.17 (devlog 3.13–3.17) and the review of 3.18. The user answered the open points on 26 Nov 2026 (devlog 3.18, at its end): the rolling-ball radius stays 5 px, the samples are fine, the tests may run in parallel. A fourth review, by GPT-6.2 Astra through Codex (devlog 3.19, findings 29–40), was asked for before sign-off; all its findings are fixed (devlog 3.20, 3.21) and the state after the fixes is in devlog 3.22. Task 3.23 (planes for the Cellpose projection), planned on 26 Nov 2026 with the cultured-cell crop, is not started.
- **OMERO:** the fix for a dropped connection and for the session key in the terminal is committed and tested with stand-ins for the server only (devlog, "OMERO fix: second try and a clean terminal"). The check on the real server is still to be run by the user.
- 1,197 tests pass in `bigfish-msp` with the full-size image (devlog 3.22). Run the suite in parallel, in two commands, about 5 and a half minutes in all: `conda run -n bigfish-msp python -m pytest -n 6 -m "not full_image"`, then `conda run -n bigfish-msp python -m pytest -m full_image` (the full-size tests need about 5 GB each and must not run side by side). One test at a time the suite takes 13 minutes, and a foreground command is cut off after 10 minutes, so run it in the background.
- Everything of Phase 3 is committed on `msp` and not pushed.

## Next step

1. Task 3.23 (plan): a setting that limits the projection for Cellpose to some planes, tested on the cultured-cell crop in `tests/data/` (devlog, "Cultured-cell test image and task 3.23 planned"). It is planned and not started. Its plan speaks of "the check of the first image", which task 3.21 replaced by a check of every image when a run is planned; the plane numbers are checked there.
2. The user reads devlog 3.19 to 3.22 (the fourth review, its fixes and the changes in behaviour they bring), signs off Phase 3 and says when to merge `msp` into `main` and push. Nothing is merged or pushed before that.
3. After the merge, Phase 4 (Optimise notebook) is planned in detail in `msp-plan.md`, starting from the points carried forward in devlog 3.11, 3.18 and 3.22.

## How the work is run

- The orchestrator briefs each executor (goal, spec sections, files, check), reviews every change, runs the checks itself, commits to `msp` after each task and writes the devlog. Models and effort are in the plan; no other executors are used.
- The user is asked at each check-in in the plan and whenever something is unclear. Phase 3 check-ins: the decisions (3.0), a first look at the final QC (after 3.5), a change to the workers estimate if there is one (3.9), the samples (3.10), the phase review (3.11).
- Nothing is pushed, tagged or merged without asking.
- Cellpose mask quality on the test image is not brought to the user (brief R8).

## Waiting on the user

- **OMERO on the real server, on a day with a stable VPN:** rerun `bigfish-pypeline batch ~/bigfish-testdata/phase2/omero/omero_batch.yaml` (images 5806 and 5795, username already set) to see both images finish, the "rejoining" line if the connection drops, and no session key or `WARNING:` lines in the terminal. The rejoining code changed in 3.13 and 3.20; what the server sends for an expired session key could not be checked without it.
- **The Cellpose 4 mask review** on the cultured-cell image in `~/bigfish-testdata/cultured_cells/` (planes 12–30), after task 3.23 and before Phase 8.
- **The sign-off of Phase 3** (devlog 3.18 and 3.22).
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
