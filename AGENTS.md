## Environment

- Main env: `bigfish-pypeline`, defined in `environment.yml` (Miniforge conda). Run code with `conda run -n bigfish-pypeline <cmd>`.
- MSP dev env: `bigfish-msp`, defined in `docs/modularisation-streamlit-project/msp-environment.yml`. Do not modify the main env or `environment.yml` during MSP development.
- Cellpose: the main env is pinned to 3.x (v3 `models.Cellpose` API); the MSP dev env uses Cellpose 4.
- MSP planning documents live in `docs/modularisation-streamlit-project/` with an `msp-` prefix.

## MSP project

- Start with `msp-handoff.md` (where the work stands), then `msp-plan.md` (roles and the tasks of the current phase). `msp-spec.md` says what is built, `msp-brief.md` holds the decisions behind it, and `msp-devlog.md` records results, deviations and numbers.
- Development choices, deviations and benchmark numbers go in `msp-devlog.md`, not in this file or in memory files.
- Work is done on the `msp` branch. A phase is merged into `main` only after the user signs it off. Do not push, tag or merge without asking the user.
- The new package is `src/bigfish_pypeline/`, with its tests in `tests/` and the command `bigfish-pypeline`. `image_utils.py` and `omero_tools.py` in the package stay unchanged until Phase 8, because the v1 scripts and notebooks on `main` import them.
- Run the tests with `conda run -n bigfish-msp python -m pytest` (plain `pytest` may pick up another installation). Add `-m "not full_image"` to leave out the tests that need the full-size image.
- OMERO: the user types their password in their own terminal. Never ask for it, never handle it, and never connect to an OMERO server.

## Documentations

- Keep the documentations lean and avoid using softEng jargons. Use British English. 
- Instructions should be well-documented for biologists with little coding experience. Link out to appropriate resources, if helpful.
- Instructions may include cropped screenshots to aid delivery, for this use `playwright-cli` installed in my local computer, do not add `playwrite-cli` to the conda env. The screenshots should be saved to the `www/screenshots` directory. 
- Do not include meta-narrations in any documentations or code comments.
