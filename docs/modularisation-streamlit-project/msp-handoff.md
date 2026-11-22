# MSP handoff

Where the work stands, for whoever picks it up next. Updated 22 Nov 2026. Details are in `msp-devlog.md`; tasks are in `msp-plan.md`.

## State

- **Phase 0 and Phase 1:** done, signed off, merged into `main` and pushed.
- **Phase 2 (Cellpose 4 and comparisons):** planned, and the three decisions are agreed (devlog 2.0). No task has started.
- `msp` holds the Phase 2 plan and decisions on top of `main`. The working tree is clean.
- 604 tests pass in `bigfish-msp` (about 5 minutes with the full-size image).

## Next step

Wait for the user to say start. Then begin tasks 2.1, 2.2 and 2.6 together, followed by 2.3 → 2.4 → 2.5, and 2.7 on its own (plan, Phase 2).

## How the work is run

- The orchestrator briefs each executor (goal, spec sections, files, check), reviews every change, runs the checks itself, commits to `msp` after each task and writes the devlog. Models and effort are in the plan; no other executors are used.
- The user is asked at each check-in in the plan and whenever something is unclear. Phase 2 check-ins: the final `workers: auto` figures (2.7), the rolling ball comparison (2.6), the phase review (2.8).
- Nothing is pushed, tagged or merged without asking.
- Cellpose mask quality on the test image is not brought to the user (brief R8).

## Waiting on the user

- **OMERO check on the lab server** (left over from Phase 1): `python tests/manual/omero_session_check.py --image-id <ID>` in `bigfish-msp`, on the lab network; the user pastes the printed lines. Then a small real OMERO batch of two images.
- **An image for the Cellpose 4 mask review** (e.g. cultured cells), needed before Phase 8.
- Optional checks from the Phase 1 review that the user has not reported on: trying `check` and `batch` on the test kit, and reading the "choices the spec does not settle" in devlog 1.2, 1.3, 1.8, 1.9 and 1.10.

## Files outside the repository (this laptop)

| Path | Holds |
|---|---|
| `~/bigfish-testdata/` | The full-size test image; set `BIGFISH_TEST_DATA` to this folder for the `full_image` tests |
| `~/bigfish-testdata/reference_v1/` | v1 reference results for the full-size image |
| `~/bigfish-testdata/benchmarks/phase0/` | Phase 0 benchmark scripts and numbers, the pattern for task 2.7 |
| `~/bigfish-testdata/phase1/` | Full-size runs of Phase 1 and the v1 scripts run in the new env |
| `../bigfish-pypeline-v1` | The v1 code at tag `v1.0`, for comparisons in the main env |
| `~/Documents/Tools/Image-analysis/Segmentation/Cellpose-SAM-AppleM1/cellpose-sam-workbook.ipynb` | The Cellpose-SAM workbook that tasks 2.1–2.3 follow |
| `~/.cellpose/models/cpsam_v2` | The Cellpose model, already downloaded |

## Worth knowing

- `conda run` does not pass typed or piped input: put scripts in files and run those.
- The laptop has 17 GB of memory and often only about 4 GB free. One worker needs about 5 GB for a full-size channel, so full-size runs and benchmarks go one at a time.
- PyTorch 2.14.1 in `bigfish-msp` can use the Apple GPU.
- v1 does not give the same result twice above 2,000 spots, because its reference spot is built from a random sample. The new code fixes the seed, so full-size comparisons with v1 after decomposition are counts within v1's own range (devlog 0.6, 1.14).
- Subpixel positions differ slightly from v1 because of the newer packages, not the new code. The user accepted this; the exact comparison is with `tests/data/reference_v1_new_env/` (devlog 1.5).
- During a batch run the main process sets the thread variables to 1 for the workers. Cellpose on CPU in that process must not be limited by this (plan 2.4).
- `workers: auto` uses 35 bytes per voxel of one channel, with a 2 GB reserve. With little free memory it runs one worker with a warning. The final figures come from task 2.7.
