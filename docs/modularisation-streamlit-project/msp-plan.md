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

Done, signed off and merged into `main` on 26 Nov 2026, except task 3.23 below, which the user asked to have done after the merge. Results, deviations and the points carried forward are in `msp-devlog.md` (entries 3.0–3.22). Four independent reviews were made during the phase (entries 3.12 and 3.19, findings 1–40); all confirmed findings are fixed. The checks left to the user are listed in `msp-handoff.md`.

### 3.23 Planes for the segmentation projection

- Done by Opus 5.5, medium, in `config.py`, `segmentation.py` and `batch.py`, on `msp` after the Phase 3 merge (user's decision, 26 Nov 2026).
- Reason: in cultured cells the lower planes hold the cells spread over the coverslip, where the cell-mask stain of neighbouring cells overlaps into one sheet. Cellpose separates the cells better on a projection of the upper planes only, but the spots in the lower planes still belong in the counts.
- A new setting, `segmentation.z_planes`: the first and last plane of the projection made for Cellpose, counted from 0 like channel numbers, both included. Left empty, every plane is used, as now. Spot detection always uses every plane.
- The settings check refuses a first plane after the last. A plane number beyond an image's planes is found when the run is planned, in the check of every image (devlog 3.21): that image fails with a clear message, and the run stops before it starts when no image can be used. `run.log` and `run_config.yaml` record the planes used; the Cellpose QC figure shows the projection Cellpose received.
- The spec's list of settings gains `z_planes`.
- Checks: a test that the projection uses only the chosen planes; a run of the cultured-cell test kit (`tests/data/culture_DAPI_cellmask_exon_crop.tif`, planes 12–30) whose spot table is the same with and without the setting.
- The user looks at the Cellpose QC figure of the cultured-cell kit, and says when the task is merged into `main`.

## Later phases

Planned in detail when the previous phase is merged. Usual split:

| Phase | Mostly done by |
|---|---|
| 4 Optimise notebook | Sonnet 5.5, high |
| 5 Streamlit app | Opus 5.5, medium |
| 6 Documentation | Sonnet 5.5, high; screenshots with `playwright-cli` |
| 7 Windows and Linux testing | Orchestrator, with the user on the lab machines |
| 8 Main env and release | Orchestrator, on the user's instruction |
