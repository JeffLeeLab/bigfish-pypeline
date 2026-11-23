# MSP handoff

Where the work stands, for whoever picks it up next. Updated 23 Nov 2026. Details are in `msp-devlog.md`; tasks are in `msp-plan.md`.

## State

- **Phase 0 and Phase 1:** done, signed off, merged into `main` and pushed.
- **Phase 2 (Cellpose 4 and comparisons):** under way on `msp`. Tasks 2.0, 2.1, 2.2, 2.3, 2.4 and 2.6 are done and committed (devlog 2.0–2.4 and 2.6). Tasks 2.5, 2.7 and 2.8 have not started.
- 730 tests pass in `bigfish-msp` without the full-size image (about 5.5 minutes), three of them with the real Cellpose model.
- The working tree is clean. Nothing of Phase 2 has been pushed.

## Next step

The work is paused at the user's request while they run the OMERO check over the VPN. When they say resume: 2.5 (end-to-end tests, Sonnet 5.5), then 2.7 (benchmarks) on its own with nothing else running, then the phase review 2.8 (plan, Phase 2).

## How the work is run

- The orchestrator briefs each executor (goal, spec sections, files, check), reviews every change, runs the checks itself, commits to `msp` after each task and writes the devlog. Models and effort are in the plan; no other executors are used.
- The user is asked at each check-in in the plan and whenever something is unclear. Phase 2 check-ins: the final `workers: auto` figures (2.7), the rolling ball comparison (2.6), the phase review (2.8).
- Nothing is pushed, tagged or merged without asking.
- Cellpose mask quality on the test image is not brought to the user (brief R8).

## Waiting on the user

- **Mask size limit:** Cellpose removes masks larger than 40% of the image and the config has no setting for it (devlog 2.2). The user was asked whether to add one.
- **Small real OMERO batch** with Cellpose on: the config is `~/bigfish-testdata/phase2/omero/omero_batch.yaml` (image 5806, the full-size test image); the user adds a second image ID and runs `bigfish-pypeline batch` in their own terminal over the VPN. The OMERO check itself passed on 23 Nov 2026 (devlog).
- **An image for the Cellpose 4 mask review** (e.g. cultured cells), needed before Phase 8.
- Optional checks from the Phase 1 review that the user has not reported on: trying `check` and `batch` on the test kit, and reading the "choices the spec does not settle" in devlog 1.2, 1.3, 1.8, 1.9 and 1.10.

## Files outside the repository (this laptop)

| Path | Holds |
|---|---|
| `~/bigfish-testdata/` | The full-size test image; set `BIGFISH_TEST_DATA` to this folder for the `full_image` tests |
| `~/bigfish-testdata/reference_v1/` | v1 reference results for the full-size image |
| `~/bigfish-testdata/benchmarks/phase0/` | Phase 0 benchmark scripts and numbers, the pattern for task 2.7 |
| `~/bigfish-testdata/phase1/` | Full-size runs of Phase 1 and the v1 scripts run in the new env |
| `~/bigfish-testdata/phase2/` | Scripts, tables and logs of the rolling ball comparison (task 2.6) |
| `../bigfish-pypeline-v1` | The v1 code at tag `v1.0`, for comparisons in the main env |
| `~/Documents/Tools/Image-analysis/Segmentation/Cellpose-SAM-AppleM1/cellpose-sam-workbook.ipynb` | The Cellpose-SAM workbook that tasks 2.1–2.3 follow |
| `~/.cellpose/models/cpsam_v2` | The Cellpose model, already downloaded |

## Worth knowing

- The user reviewed the rolling ball comparison and kept rolling ball as the default for FISH channels (devlog 2.6). It gives about a third more clusters than top-hat on the full-size exon channel, because decomposition places more spots in each bright focus on the rolling ball image.

- `conda run` does not pass typed or piped input: put scripts in files and run those.
- The laptop has 17 GB of memory and often only about 4 GB free. One worker needs about 5 GB for a full-size channel, so full-size runs and benchmarks go one at a time.
- PyTorch 2.14.1 in `bigfish-msp` can use the Apple GPU.
- v1 does not give the same result twice above 2,000 spots, because its reference spot is built from a random sample. The new code fixes the seed, so full-size comparisons with v1 after decomposition are counts within v1's own range (devlog 0.6, 1.14).
- Subpixel positions differ slightly from v1 because of the newer packages, not the new code. The user accepted this; the exact comparison is with `tests/data/reference_v1_new_env/` (devlog 1.5).
- During a batch run the main process sets the thread variables to 1 for the workers. Cellpose on CPU in that process must not be limited by this (plan 2.4).
- Two executors must not work in the same file at once: 2.1 and 2.2 both edit `segmentation.py`, so they were run one after the other.
- Cellpose 4.2.1.1 loads `cpsam_v2` without an error when given an unknown model name; the package checks the name itself (devlog 2.2).
- `workers: auto` uses 35 bytes per voxel of one channel, with a 2 GB reserve. With little free memory it runs one worker with a warning. The final figures come from task 2.7.
