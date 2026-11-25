# MSP handoff

Where the work stands, for whoever picks it up next. Updated 25 Nov 2026. Details are in `msp-devlog.md`; tasks are in `msp-plan.md`.

## State

- **Phases 0, 1 and 2:** done, signed off, merged into `main` and pushed. Phase 2 was signed off and merged on 24 Nov 2026 (devlog 2.8).
- **Phase 3 (outputs, logs and QC):** planned in `msp-plan.md` on 24 Nov 2026; the user answered the three decisions (devlog 3.0) and two more on the QC files (devlog 3.5, at its end). Tasks 3.1 to 3.9 are done and committed (devlog 3.1–3.9); the `workers: auto` figures stand. The samples of 3.10 are made (devlog 3.10) and wait for the user's review. The phase review (devlog 3.11) is written, with its checks run at commit `bf270e0`. Independent reviews by Gemini 4 Neon and GPT-6.2 Astra (devlog 3.12, findings 1–28) found problems from Phases 1–3 to fix before sign-off; tasks 3.13–3.18 are in the plan. The user decided that only 8-bit, 12-bit and 16-bit images are accepted, and answered the six decisions after the reviews (rolling-ball radius, Cellpose pre-treatment, cluster centres, cluster marks, the final message of a run with failed images, checksums in `run_info.yaml`).
- **OMERO:** the fix for a dropped connection and for the session key in the terminal is committed and tested with stand-ins for the server only (devlog, "OMERO fix: second try and a clean terminal"). The check on the real server is still to be run by the user.
- 1,057 tests pass in `bigfish-msp` with the full-size image, 1,054 without it (9 min 36 s) and 1,048 without the Cellpose model. A foreground command is cut off after 10 minutes: run the suite in the background and in two parts (the split is in devlog 3.8).
- The Phase 3 plan and devlog 3.0 are committed on `msp` and not pushed.

## Next step

1. Tasks 3.13 and 3.14 (they can start together), then 3.15 and 3.16, as briefed in the plan. Task 3.17 (rolling-ball radius comparison) can run at any point, but not during a full-size test run.
2. The user reviews the samples listed in devlog 3.10 (QC images, `run.log`, `run_info.yaml`), redrawn where 3.14 changed a figure.
3. Task 3.18: rerun the suite (in two parts: one command is cut off after 10 minutes) and bring devlog 3.11 up to date. The user decides whether the tests may run in parallel (`pytest-xdist` in `msp-environment.yml`), signs off Phase 3 and says when to merge `msp` into `main` and push. Nothing is merged or pushed before that.
4. After the merge, Phase 4 (Optimise notebook) is planned in detail in `msp-plan.md`, starting from the points carried forward in devlog 3.11.

## How the work is run

- The orchestrator briefs each executor (goal, spec sections, files, check), reviews every change, runs the checks itself, commits to `msp` after each task and writes the devlog. Models and effort are in the plan; no other executors are used.
- The user is asked at each check-in in the plan and whenever something is unclear. Phase 3 check-ins: the decisions (3.0), a first look at the final QC (after 3.5), a change to the workers estimate if there is one (3.9), the samples (3.10), the phase review (3.11).
- Nothing is pushed, tagged or merged without asking.
- Cellpose mask quality on the test image is not brought to the user (brief R8).

## Waiting on the user

- **OMERO on the real server, on a day with a stable VPN:** rerun `bigfish-pypeline batch ~/bigfish-testdata/phase2/omero/omero_batch.yaml` (images 5806 and 5795, username already set) to see both images finish, the "rejoining" line if the connection drops, and no session key or `WARNING:` lines in the terminal.
- **An image for the Cellpose 4 mask review** (e.g. cultured cells), needed before Phase 8.
- **The default rolling-ball radius for FISH channels**, once the comparison of task 3.17 is in the devlog.
- **Review of the Phase 3 samples** (devlog 3.10), the decision on running the tests in parallel, and the sign-off of Phase 3 (devlog 3.11).
- **Manual checks of the Phase 2 review** (devlog 2.8): Cellpose on the test kit, a look at a full-size run folder, and the "choices the spec does not settle" in 2.1, 2.3 and 2.4.
- Optional checks from the Phase 1 review that the user has not reported on: trying `check` and `batch` on the test kit, and reading the "choices the spec does not settle" in devlog 1.2, 1.3, 1.8, 1.9 and 1.10.

## Files outside the repository (this laptop)

| Path | Holds |
|---|---|
| `~/bigfish-testdata/` | The full-size test image; set `BIGFISH_TEST_DATA` to this folder for the `full_image` tests |
| `~/bigfish-testdata/reference_v1/` | v1 reference results for the full-size image |
| `~/bigfish-testdata/benchmarks/phase0/` | Phase 0 benchmark scripts and numbers, the pattern for task 2.7 |
| `~/bigfish-testdata/benchmarks/phase2/` | Benchmark scripts, logs and numbers of task 2.7 |
| `~/bigfish-testdata/benchmarks/phase3/` | Benchmark scripts, logs and numbers of task 3.9, and a full-size run folder with every output |
| `~/bigfish-testdata/phase3/samples/` | Sample run folders for the user's review (task 3.10), with the script that makes them |
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
