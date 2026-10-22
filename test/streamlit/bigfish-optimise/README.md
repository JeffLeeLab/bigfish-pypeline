# BigFISH Optimise

This directory contains the laptop pre-deployment build of the Streamlit app for BigFISH parameter optimisation.

## Scope

- The app is intended for local validation on a laptop before VM deployment.
- OMERO is the only implemented image source.
- The app loads image metadata first and then fetches a single selected channel to avoid pulling full ZCYX datasets into memory.
- YAML export follows the existing general smFISH batch schema in `general/batch_script/smFISH_analysis_config.yaml`.
- Manual-threshold export is currently limited to two channels because the batch schema exposes `smFISH_ch1` and `smFISH_ch2` only.

## Local setup

This is a temporary development environment for the Streamlit app.

Create the environment from the repository root:

```bash
conda env create -f test/streamlit/bigfish-optimise/environment.yml
```

Update it later with:

```bash
conda env update -f test/streamlit/bigfish-optimise/environment.yml --prune
```

## Run locally

From the repository root:

```bash
conda activate bigfish-optimise
streamlit run test/streamlit/bigfish-optimise/app.py
```

The local Streamlit config binds to `127.0.0.1:8502` and does not set a reverse-proxy base path.

## Local validation

Run the smoke test and unit tests:

```bash
bash test/streamlit/bigfish-optimise/test_environment.sh
```

Then confirm the following manually:

1. The Streamlit UI starts without import errors.
2. Sidebar controls rerun cleanly.
3. If OMERO is reachable from the laptop, the app connects and loads a known image ID.
4. A full single-channel run renders the MIP, LoG, detection, decomposition, optional subpixel, clustering, and export sections.
5. YAML download produces a parseable config file.

## Notes

- Voxel sizes are left blank if OMERO metadata is missing. The analysis button should not be used until both voxel fields are filled.
- Saved YAML export channels must share the same global analysis settings.
- VM-specific nginx and systemd deployment steps are intentionally deferred until after laptop validation.