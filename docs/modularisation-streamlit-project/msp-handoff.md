# MSP handoff

Where the work stands, for whoever picks it up next. Updated 23 Nov 2026. Details are in `msp-devlog.md`; tasks are in `msp-plan.md`.

## State

- **Phase 0 and Phase 1:** done, signed off, merged into `main` and pushed.
- **Phase 2 (Cellpose 4 and comparisons):** under way on `msp`. Tasks 2.0 to 2.7 are done and committed (devlog 2.0–2.7). The user agreed the final `workers: auto` figures. Task 2.8 is left.
- **OMERO on the lab server (23 Nov 2026):** the login-sharing check passed, and a real batch of two images with Cellpose ran over the VPN (devlog, "OMERO check on the lab server" and "Real OMERO batch with Cellpose"). Image 5806 agrees with the local runs. Image 5795 failed when the connection dropped, which showed three defects: no retry when the image information is read, the session key printed in the terminal by omero-py, and stray lines in the terminal.
- **OMERO fix:** reviewed and committed (devlog, "OMERO fix: second try and a clean terminal"). Tested with stand-ins for the server only; the check on the real server is still to be run by the user.
- 775 tests pass in `bigfish-msp` without the full-size image (about 5 min 40 s), six of them with the real Cellpose model.
- Nothing of Phase 2 has been pushed.

## Next step

1. Task 2.8 (phase review): whole suite in a fresh shell with the full-size image and without the `cellpose` tests, the v1 imports in the main env, the Phase 2 review entry in the devlog, then the user's sign-off.

**No OMERO testing on 23 Nov 2026:** the user's VPN was unstable and stays off. Trying the OMERO fix on the real server (a batch that survives a dropped connection, and a terminal free of the session key) is left for a later day and goes into the manual checks of the phase review.

## How the work is run

- The orchestrator briefs each executor (goal, spec sections, files, check), reviews every change, runs the checks itself, commits to `msp` after each task and writes the devlog. Models and effort are in the plan; no other executors are used.
- The user is asked at each check-in in the plan and whenever something is unclear. Phase 2 check-in left: the phase review (2.8).
- Nothing is pushed, tagged or merged without asking.
- Cellpose mask quality on the test image is not brought to the user (brief R8).

## Waiting on the user

- **OMERO on the real server, on a later day:** rerun `bigfish-pypeline batch ~/bigfish-testdata/phase2/omero/omero_batch.yaml` (images 5806 and 5795, username already set) to see both images finish, the "rejoining" line if the connection drops, and no session key or `WARNING:` lines in the terminal. Not on 23 Nov 2026: the VPN stays off.
- **An image for the Cellpose 4 mask review** (e.g. cultured cells), needed before Phase 8.
- Optional checks from the Phase 1 review that the user has not reported on: trying `check` and `batch` on the test kit, and reading the "choices the spec does not settle" in devlog 1.2, 1.3, 1.8, 1.9 and 1.10.

## Files outside the repository (this laptop)

| Path | Holds |
|---|---|
| `~/bigfish-testdata/` | The full-size test image; set `BIGFISH_TEST_DATA` to this folder for the `full_image` tests |
| `~/bigfish-testdata/reference_v1/` | v1 reference results for the full-size image |
| `~/bigfish-testdata/benchmarks/phase0/` | Phase 0 benchmark scripts and numbers, the pattern for task 2.7 |
| `~/bigfish-testdata/benchmarks/phase2/` | Benchmark scripts, logs and numbers of task 2.7 |
| `~/bigfish-testdata/phase1/` | Full-size runs of Phase 1 and the v1 scripts run in the new env |
| `~/bigfish-testdata/phase2/` | Scripts, tables and logs of the rolling ball comparison (task 2.6) |
| `~/bigfish-testdata/phase2/omero/` | Config and run folder of the real OMERO batch |
| `../bigfish-pypeline-v1` | The v1 code at tag `v1.0`, for comparisons in the main env |
| `~/Documents/Tools/Image-analysis/Segmentation/Cellpose-SAM-AppleM1/cellpose-sam-workbook.ipynb` | The Cellpose-SAM workbook that tasks 2.1–2.3 follow |
| `~/.cellpose/models/cpsam_v2` | The Cellpose model, already downloaded |

## Worth knowing

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
