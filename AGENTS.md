## Environment

- Main env: `bigfish-pypeline`, defined in `environment.yml` (Miniforge conda). Run code with `conda run -n bigfish-pypeline <cmd>`.
- Streamlit dev env: `bigfish-optimise`, defined in `test/streamlit/bigfish-optimise/environment.yml`.
- Cellpose is pinned to 3.x (code uses the v3 `models.Cellpose` API).

## Documentations

- Keep the documentations lean and avoid using softEng jargons. Use British English. 
- Instructions should be well-documented for biologists with little coding experience. Link out to appropriate resources, if helpful.
- Instructions may include cropped screenshots to aid delivery, for this use `playwright-cli` installed in my local computer, do not add `playwrite-cli` to the conda env. The screenshots should be saved to the `www/screenshots` directory. 
- Do not include meta-narrations in any documentations or code comments.