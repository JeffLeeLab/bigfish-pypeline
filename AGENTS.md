## Environment

- Main env: `bigfish-pypeline`, defined in `environment.yml` (Miniforge conda). Run code with `conda run -n bigfish-pypeline <cmd>`.
- MSP dev env: `bigfish-msp`, defined in `docs/modularisation-streamlit-project/msp-environment.yml`. Do not modify the main env during MSP development.
- Cellpose: the main env is pinned to 3.x (v3 `models.Cellpose` API); the MSP dev env uses Cellpose 4.
- MSP planning documents live in `docs/modularisation-streamlit-project/` with an `msp-` prefix.

## Documentations

- Keep the documentations lean and avoid using softEng jargons. Use British English. 
- Instructions should be well-documented for biologists with little coding experience. Link out to appropriate resources, if helpful.
- Instructions may include cropped screenshots to aid delivery, for this use `playwright-cli` installed in my local computer, do not add `playwrite-cli` to the conda env. The screenshots should be saved to the `www/screenshots` directory. 
- Do not include meta-narrations in any documentations or code comments.