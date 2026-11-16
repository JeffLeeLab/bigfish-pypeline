# MSP specification

Modularisation-streamlit-project (MSP) for bigfish-pypeline. Decisions referenced as (brief: X1) are recorded with their rationale in `msp-brief.md`.

## 1. Purpose and scope

Replace the four near-identical pipeline variants (general, HCRv3, tissue-culture, OMERO) with one installable package that the optimise notebook, a local Streamlit app and a command-line batch all share. Update the software stack, make optimise → batch a single continuous workflow, give outputs that are easy to read and to match back to images, and document everything for biologists with little coding experience.

**Core functionality** means the big-fish algorithms (spot detection, dense-region decomposition, subpixel fitting, cluster detection). Results may change because of bug fixes, the rolling-ball background option and Cellpose 4; every such change is measured and documented (brief: A1).

**In scope**

- Python 3.12 stack, patched big-fish fork, Cellpose 4 (Cellpose-SAM), ImageJ-faithful rolling ball.
- One pipeline with switchable steps, any number of FISH channels, 2D and 3D images, local TIFF and OMERO input.
- Cellpose segmentation or pre-segmented label images, with per-cell results.
- One configuration file format shared by notebook, app and command line.
- Linked CSV outputs, QC images, run log and run record.
- Streamlit app (Optimise, Batch, Results, Help pages) with double-click launchers.
- Quarto user guide (HTML) and README.

**Out of scope** (see section 16 for the later to-do list)

- Nucleus segmentation, 3D segmentation, multi-channel Cellpose input.
- Image formats other than TIFF; multi-position and time-lapse files.
- Resuming interrupted runs; uploading results to OMERO; keeping local copies of OMERO images.
- Rewriting git history.

## 2. Users, platforms and scale

- Lab laptops (macOS Apple silicon; Windows) and lab workstations (Windows with an NVIDIA GPU, used natively and through Ubuntu in WSL2) (brief: A4, Native Windows).
- Typical batch: 100–200 images of 2048 × 2048 × 30 (x, y, z), several channels.
- Users install a conda environment with Miniforge; no other installation steps are expected of them.
- Development and testing on macOS until Phase 7, which tests native Windows, WSL2 and Linux before the v2.0 release (brief: J1).

## 3. Working rules

- Development happens in the `bigfish-msp` conda env (`docs/modularisation-streamlit-project/msp-environment.yml`). The main `bigfish-pypeline` env and `environment.yml` stay unchanged until the user says otherwise (Phase 8).
- Repo exploration and web research use Haiku subagents; simple documentation updates use Sonnet subagents.
- Development choices, deviations, benchmark numbers and comparison results go in `docs/modularisation-streamlit-project/msp-devlog.md`, not in memory files or `AGENTS.md`.
- Anything unclear is asked, not assumed.
- Existing object names (`rna`, `rna_log`, `rna_mip`, `spots`, `spots_post_decomposition`, `spots_post_clustering`, `clusters`, `reference_spot`, `masks`, `threshold`, `spot_radius_px`, `voxel_size_z`, `voxel_size_yx`, `calculate_psf`, `subtract_background`, `connect_to_omero`, `get_omero_image`) and the current coding style are kept so the code stays readable to its maintainer.
- `AGENTS.md` documentation rules apply: British English, plain language, no meta-narration in documents or code comments, screenshots with `playwright-cli` saved to `www/screenshots/`.
- Work happens on the `msp` branch; each phase is merged into `main` after the user has reviewed it (brief: C3).
- Code is written to run on macOS, Windows and Linux from the start: `pathlib` paths, the "spawn" process start method, argument lists instead of shell strings, no POSIX-only calls.

## 4. Target architecture

### 4.1 Repository layout (brief: C1)

```
src/bigfish_pypeline/       installable package
    __init__.py             version
    io.py                   local TIFF reading, axes and voxel-size metadata, OMERO access
    config.py               configuration schema, defaults, validation, YAML load/save
    psf.py                  calculate_psf
    background.py           subtract_background (rolling ball, top-hat)
    rolling_ball.py         copy of imagej_rolling_ball.py from JeffLeeLab/Image-analysis
    detection.py            LoG, spot detection, threshold modes, elbow values, bailout
    decomposition.py        reference spot, dense-region decomposition
    subpixel.py             subpixel fitting
    clusters.py             cluster detection
    measurements.py         per-spot SNR and intensity
    segmentation.py         pre-treatment, Cellpose 4, label-file loading, device selection
    cells.py                assignment of spots and clusters to cells, cell table
    outputs.py              tables, run folder, run record, combining per-image files
    qc.py                   QC figures
    batch.py                batch runner (process pool, logging, progress, cancel)
    cli.py                  command-line entry point
app/                        Streamlit app (section 10)
launchers/                  double-click launchers (.command, .bat)
notebooks/                  bigfish-optimise.ipynb
tests/                      unit, regression and end-to-end tests; tests/data/ test kits
docs/guide/                 Quarto user guide source
www/screenshots/            screenshots used by the guide
pyproject.toml
_quarto.yml                 Quarto website project (renders docs/guide/ only)
```

### 4.2 Commands

- `bigfish-pypeline batch <config.yaml> [--input-folder …] [--filter …] [--output-folder …] [--workers …]`: values given on the command line override the file (brief: F2).
- `bigfish-pypeline check <config.yaml>`: validates a config and lists the images it would process, without running anything.
- `bigfish-pypeline app`: starts the Streamlit app.
- Installed through `pip install -e .` inside the conda env (entry point declared in `pyproject.toml`).

### 4.3 Software environment

Phases 0–1: `msp-environment.yml` is a copy of the current `environment.yml` stack (Python 3.9, Cellpose 3.1.1.2) plus `pytest`, a `pydantic` 2 release that supports Python 3.9, and the editable package. This keeps Phase 1 results directly comparable with v1.

From Phase 2 (exact versions fixed at the start of the phase and recorded in the devlog) (brief: B1–B4):

| Package | Source | Version |
|---|---|---|
| python | conda-forge | 3.12 |
| numpy, scipy, scikit-image, scikit-learn, matplotlib, pandas, tifffile, pyyaml, tqdm | conda-forge | current; scikit-image < 0.27; pandas 3 only if big-fish tests pass, otherwise < 3 |
| pytorch | conda-forge | 2.14.1 (selects CUDA, Apple GPU or CPU build per machine) |
| zeroc-ice, omero-py | conda-forge | 3.6.5, 5.22.x |
| pydantic, plotly, streamlit, tk, jupyterlab, ipykernel, pytest | conda-forge | current (Streamlit and plotly added in Phase 5) |
| cellpose | pip | 4.2.1.1 |
| big-fish | pip from git | `git+https://github.com/JeffLeeLab/big-fish.git@v0.6.2.post1` |
| streamlit-image-coordinates | pip | current, pinned (Phase 5) |

`playwright-cli` is used from the user's machine and is never added to an env file.

## 5. Pipeline

### 5.1 Steps and switches

| # | Step | Runs | Per | Main settings (default) | Objects produced |
|---|---|---|---|---|---|
| 1 | Load image | always | image | source, axes, voxel sizes | image array |
| 2 | Prepare | always | channel | ex, em, NA, RI, microscope type → PSF | `spot_radius_px` |
| 3 | Background + LoG | always | channel | method rolling ball, radius 5 px | `rna`, `rna_log`, `rna_mip` |
| 4 | Detect spots | always | channel | threshold mode; lower limit; bailout (off) | `spots` |
| 5 | Decompose dense regions | switch | channel | alpha 0.5, beta 1 | `reference_spot`, `spots_post_decomposition` |
| 6 | Subpixel fitting | switch | channel | none | subpixel coordinates |
| 7 | Clusters | switch | channel | radius 500 nm, minimum spots 4 | `spots_post_clustering`, `clusters` |
| 8 | Spot measurements | switch | channel | SNR off, intensity off | extra spot columns |
| 9 | Segmentation | switch | image | Cellpose or label files | `masks` |
| 10 | Cell assignment | on when 9 is on | image × channel | drop border cells (off) | `cell_id` columns, cell table |

Steps 5–8 run in this order and each takes whatever spots exist at that point, so clustering works with or without decomposition (brief: D6).

### 5.2 Presets (brief: D6)

A preset is two independent choices:

- **Assay type, per channel:** smFISH → steps 5 and 7 on; amplified FISH (HCR, RNAscope) → steps 5 and 7 off. Steps 6 and 8 are off in both.
- **Per-cell results, per image:** steps 9 and 10 on or off.

Presets only set step switches. Every preset uses the same default values; any switch can be changed afterwards. Presets are not written to the config file; only the resulting switches are.

### 5.3 Image input (brief: B6, D1, D2, D3)

**Local files**

- The user chooses a folder, a file-name text filter and an extension (`.tif` or `.tiff`). Only the top level of the folder is searched; matching files are sorted by name and listed before anything runs.
- Optimise works on one file picked from that list; batch uses the whole list.
- Images are read with `tifffile`. Accepted layouts: `ZCYX`, `CZYX`, `ZYX`, `CYX`, `YX` (2D and 3D, one or several channels). The detected layout and image dimensions are shown and must be confirmed by the user; the confirmed layout is stored in the config.
- Voxel sizes are read from ImageJ or OME metadata when present and shown for confirmation. Missing values must be entered; no silent defaults. In batch, an image whose metadata disagrees with the config is processed with the config values and a warning is logged.
- Other formats: the guide explains conversion to TIFF in Fiji.

**OMERO**

- Optimise by image ID; batch by dataset ID or a list of image IDs.
- Default host and port of the lab server are stored in the package (public repo is acceptable).
- Passwords are asked each time and never written to disk. Batch workers join the session opened by the main process (session key passed in memory) instead of logging in again.
- Images are streamed into memory and not saved locally. Outputs go to a local folder chosen by the user.
- Output names use `<image ID>_<image name>` so that images with the same name in one dataset do not collide.
- `omero_tools.connect_to_omero` and `get_omero_image` are reused; the archived app's OMERO metadata reader (voxel sizes converted to nm) is brought in.

### 5.4 Background subtraction (brief: B5)

- `subtract_background(image, radius, light_bg=False, method="rolling_ball")`, applied to each Z-plane.
- `rolling_ball`: the single file `misc/python-rolling-ball/imagej_rolling_ball.py` from JeffLeeLab/Image-analysis, copied into the package with a header naming the source repo and commit. Default.
- `tophat`: the current white top-hat with a disk, kept to reproduce v1 results.
- Defaults: radius 5 px for FISH channels; radius 200 px for the segmentation channel (section 5.7).

### 5.5 Spot detection and thresholds (brief: D4, D5)

- PSF per channel from `calculate_psf` with that channel's ex/em; LoG filter, local maxima and thresholding as in v1.
- Threshold modes, set per channel:
  - `manual`: one value per channel. Works for any number of channels (fixes the v1 two-channel limit).
  - `auto`: big-fish elbow method on each image, with an optional lower limit that the value cannot go below.
  - `calibrated`: before the main run, `auto` (with the lower limit, if set) runs on the images whose names contain a chosen text; the median of those values is then used as a fixed threshold for every image. The per-image values are saved as a table and a plot.
- Bailout (optional, any mode): if an image has more spots than a set limit for a channel, the remaining steps for that channel are skipped, and the image is marked "skipped" with the reason in the log and in `images.csv`.

### 5.6 Decomposition, subpixel fitting, clusters, measurements (brief: D7, D8)

- Decomposition as in v1: Gaussian-denoised copy (sigma = 5 × spot radius) for `build_reference_spot`, `modelize_spot`, `get_dense_region` and `simulate_gaussian_mixture`; alpha 0.5, beta 1. A reference spot is built for every image and channel and saved as TIFF.
- Subpixel fitting: `detection.fit_subpixel` on the current spots.
- Clusters: `detection.detect_clusters` on the current spots, radius 500 nm, minimum spots 4 (big-fish default).
- Measurements: per-spot SNR from the posthoc function `compute_snr_spots_individual` (unused variables removed); per-spot intensity (definition to confirm, section 17).

### 5.7 Segmentation (brief: B4, D9, D10, E4)

**Cellpose**

- One input channel, 2D. Pre-treatment, in order: Z projection (max or mean) → clip (off; value 100) → background subtraction (on; rolling ball, radius 200 px; or top-hat) → median filter (off) → Gaussian filter (off).
- Cellpose 4 `CellposeModel(pretrained_model="cpsam_v2", use_bfloat16=False)`.
- Default `eval` settings follow the Cellpose-SAM workbook: `normalize=True`, `diameter=None`, `flow_threshold=0.4`, `cellprob_threshold=0`, `min_size=15`, `batch_size=1`, `niter=None`, `do_3D=False`.
- Device chosen automatically: CUDA, then Apple GPU (MPS), then CPU. A quick test calculation on the chosen device runs before the model loads, the device used is logged, and running on CPU triggers a warning that segmentation will be slow.
- The model is loaded once per batch run (main process) and cached in the app.
- The 4-panel QC figure from the workbook's `qc_figure` is rewritten to take its settings as arguments instead of reading notebook-wide variables. Its title shows the projection, channel, pre-treatment, diameter, cell count and time.
- Label images are saved as `<image>_seglabels.tif` (uint32, 2D) when switched on.

**Label files**

- The user chooses a folder; each image's labels are read from `<image>_seglabels.tif`. Only 2D labels whose shape matches the image's Y × X are accepted.
- A missing or mismatched label file skips cell-level results for that image with a warning; spot results are still written.

### 5.8 Cell assignment (brief: D11, E1)

- Each spot is looked up in the 2D label image at (floor(y), floor(x)); each cluster at its centre. The label value is the `cell_id` (matching the Cellpose label); positions outside any cell get `cell_id = -1`. This replaces big-fish `extract_cell` and avoids the v1 notebook bug.
- `touches_border` is recorded for every cell; `drop_border_cells` (off by default) removes those cells and sets their spots and clusters to `cell_id = -1`.
- No minimum cell area filter.

## 6. Configuration file (brief: F1–F3)

### 6.1 Principles

- One YAML layout written by the notebook and the app and read by the batch; the same names are used everywhere.
- Validated by a `pydantic` model before any image is processed. Messages are in plain English and name the setting, e.g. "`nb_min_spot` is not a known setting – did you mean `min_spots`?" or "`voxel_size_nm.z` must be a positive number". Unknown settings are errors, not silently ignored.
- `config_version` identifies the layout so later versions can convert older files.
- Loaded with the safe YAML loader.
- Switches are written `enabled: true` or `enabled: false`. The words `on`, `off`, `yes` and `no` are not used as setting names or choices, because YAML reads them as true or false.
- Old v1 configs are not read; the guide has a page mapping old names to new ones.

### 6.2 Layout and defaults (version 1)

```yaml
config_version: 1
run:
  name: my_run
  input:
    source: local                  # local | omero
    folder: ""                     # local
    filter: ""                     # text the file name must contain
    extension: .tif                # .tif | .tiff
    omero:
      host: <lab server address>
      port: 4064
      username: ""
      dataset_id:                  # batch: a dataset ID, or
      image_ids: []                # a list of image IDs
  output_folder: ""                # empty = <input folder>/bigfish_results/
  workers: auto                    # auto = from CPU cores and memory
  keep_awake: true
image:
  axes: ZCYX                       # confirmed by the user
  voxel_size_nm: {z: 200, yx: 65}  # confirmed by the user; z ignored for 2D
microscope:
  type: confocal                   # confocal | widefield | nipkow
  NA: 1.45
  RI: 1.45
channels:
  - index: 2
    name: ""                       # free text, e.g. Ago1-Q570
    ex: 570
    em: 610
    background: {method: rolling_ball, radius_px: 5}
    threshold:
      mode: auto                   # manual | auto | calibrated
      value:                       # manual
      lower_limit:                 # auto and calibrated, optional
      calibration_filter: ""       # calibrated: text the subset file names must contain
    bailout: {enabled: false, max_spots: }
    decomposition: {enabled: true, alpha: 0.5, beta: 1}
    subpixel: {enabled: false}
    clusters: {enabled: true, radius_nm: 500, min_spots: 4}
    measurements: {snr: false, intensity: false}
segmentation:
  enabled: false
  source: cellpose                 # cellpose | label_files
  label_folder: ""                 # label_files: folder with <image>_seglabels.tif
  channel: 0
  projection: max                  # max | mean
  clip: {enabled: false, value: 100}
  background: {enabled: true, method: rolling_ball, radius_px: 200}
  median_px:                       # empty = off
  gaussian_sigma_px:               # empty = off
  cellpose:
    model: cpsam_v2
    diameter:
    flow_threshold: 0.4
    cellprob_threshold: 0
    min_size: 15
    normalize: true
    batch_size: 1
    niter:
  device: auto                     # auto | cuda | mps | cpu
  drop_border_cells: false
outputs:
  label_images: true
  npz: false
  qc:
    elbow_plot: true
    detection: true
    reference_spot: true
    cellpose: true
    final: png                     # png | html | none
```

Settings that apply only to batch runs (`run.input` folder and filter, `workers`, `output_folder`) get defaults in the notebook (input folder = folder of the optimised image; workers = auto), have their own fields on the app's Batch page, and can be overridden on the command line.

## 7. Batch runs (brief: F5, G1)

### 7.1 Run flow

1. Validate the config; list the images; check that the output folder can be written; check channel indices against the first image. Any problem stops the run before processing with a plain message.
2. Create the run folder and write `run_config.yaml` (all defaults filled in) and the first part of `run_info.yaml`.
3. If any channel uses `calibrated` thresholds, run `auto` on the subset in the worker pool, write `calibration.csv` and its plot, and fix the threshold values.
4. Start a pool of worker processes (`concurrent.futures.ProcessPoolExecutor`, "spawn" start method). Before the pool starts, `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` are set to 1 so workers do not compete for cores.
5. Streamed processing:
   - With Cellpose: the main process loads the model once, then for each image in order reads only the segmentation channel, segments it, saves the labels, and submits that image to the pool. Segmentation of the next image overlaps with spot detection of earlier ones.
   - With label files or no segmentation: all images are submitted to the pool straight away.
   - Each worker reads only the FISH channels it needs, runs steps 1–8 and 10 for each channel, writes that image's tables and QC files, and returns a summary row.
6. The main process writes each result to `run.log`, updates `progress.json`, and records failures.
7. At the end, per-image tables are combined into one table per type, `run_info.yaml` is completed, and the summary is logged.

Each image is complete as soon as its detection finishes, so a stopped run keeps every finished image. Interrupted runs are not resumed; the user re-runs into a new run folder.

### 7.2 Workers and memory

- `workers: auto` = the smaller of (CPU cores − 1) and (available memory ÷ estimated memory per worker). The per-worker estimate is based on image size and the Phase 0/2 measurements (expected 3–4 GB for a 2048 × 2048 × 30 channel).
- The number of workers used and the reason are logged.

### 7.3 Errors, cancel and keep-awake

- Each image is processed inside its own error handling: a failure marks that image "failed" with a one-line reason in `run.log` and `images.csv` (full traceback in the log), and the run continues.
- If a worker process dies (e.g. out of memory), the images it held are marked failed, a new pool is started and the run continues.
- If the OMERO connection drops, the image is retried once after reconnecting, then marked failed.
- Cancel (Ctrl+C on the command line, or Cancel in the app): no new images start, running workers are stopped, finished images are combined into the run tables, and the run is marked "cancelled".
- With `keep_awake: true`, the computer is kept awake for the length of the run (`caffeinate` on macOS, the system keep-awake request on Windows; Linux logs that this is not available).

## 8. Outputs (brief: E1–E4, F3, F4)

### 8.1 Run folder

Default location: `<input folder>/bigfish_results/<YYYY-MM-DD_HHMM>_<run name>/`. OMERO runs and read-only input folders must name an output folder. Saving results from the notebook or the Optimise page uses the same layout.

```
<run folder>/
    run_config.yaml        fully filled-in config; passing it back repeats the run
    run_info.yaml          dates, versions, OS, device, workers, command
    run.log                plain-language log
    progress.json          live progress (read by the app)
    images.csv  spots.csv  clusters.csv  cells.csv      combined at the end
    calibration.csv        calibrated thresholds only
    per_image/             <image>_spots.csv, _clusters.csv, _cells.csv, _images.csv
    labels/                <image>_seglabels.tif
    qc/                    QC images (section 8.3)
    npz/                   <image>_ch<index>.npz (only if switched on)
```

`labels/` can be given directly as the label folder of a later run. File names use the channel index (`_ch2`); channel names appear in the tables.

### 8.2 Tables

Coordinates are given in pixels and in nm (pixel × voxel size). Z columns are present only for 3D images. `cluster_id = -1` for spots not in a cluster (or clustering off); `cell_id = -1` outside cells (or segmentation off). The `cell_id` column is always present.

| Table | One row per | Columns |
|---|---|---|
| `spots.csv` | spot | image, channel, channel_name, spot_id, z_px, y_px, x_px, z_nm, y_nm, x_nm, [z_sub_px, y_sub_px, x_sub_px, z_sub_nm, y_sub_nm, x_sub_nm when subpixel fitting is on], cluster_id, cell_id, [snr], [intensity] |
| `clusters.csv` | cluster | image, channel, channel_name, cluster_id, z_px, y_px, x_px, z_nm, y_nm, x_nm, n_spots, cell_id |
| `cells.csv` | cell × channel (every label, including cells with no spots) | image, channel, channel_name, cell_id, area_px, area_um2, centroid_y_px, centroid_x_px, touches_border, n_spots, n_spots_in_clusters, n_spots_outside_clusters, n_clusters, mean_spots_per_cluster |
| `images.csv` | image × channel | image, channel, channel_name, status (done / failed / skipped), reason, threshold_mode, threshold, n_spots_detected, n_spots, n_clusters, n_cells, segmentation_source, runtime_s |
| `calibration.csv` | subset image × channel | image, channel, auto_threshold, used |

The optional `.npz` files keep the v1 keys (`spots_post_clustering`, `clusters`) for old downstream scripts.

### 8.3 QC images

Each has its own switch (brief: E3). Names start with `<image>_ch<index>_`.

- `elbow.png`: elbow plot with the legend "Selected threshold = 11.0", plus the lower limit when set. In calibrated mode, `calibration.png` shows the per-image auto values and the median used.
- `detection.png`: spots (and clusters) over the MIP.
- `referencespot.tif`: reference spot (always TIFF).
- `<image>_cellpose_qc.png`: 4-panel Cellpose QC (one per image).
- `final.png` or `final.html`: spots, clusters, cell outlines, and for each cell its index and counts. PNG by default; HTML (interactive, with hover) as an option.

### 8.4 Run record and log

- `run_info.yaml`: start and end time, pipeline version and git commit (when available), Python and key package versions (big-fish, cellpose, torch, numpy, scipy, scikit-image, tifffile, omero-py), OS, CPU count, memory, Cellpose device, workers, the command used, final status, and calibrated threshold values.
- `run.log`: config file used, image list, each image started / finished / skipped / failed with the reason, threshold used per image and channel, warnings (metadata mismatch, missing labels, CPU segmentation), and a summary (counts per status, total time).

## 9. Optimise notebook (brief: I1)

`notebooks/bigfish-optimise.ipynb`, committed without outputs, importing everything from the package (no copied helper functions).

1. Introduction (markdown): purpose, link to the guide.
2. Imports, pipeline version, device check.
3. Preset choice and image source: local folder + filter → numbered file list → pick one; or OMERO image ID with login.
4. Image information: dimensions, detected layout, voxel sizes from metadata → user confirms or edits; per-channel MIP previews with automatic contrast.
5. FISH channel to optimise (one at a time).
6. Background and LoG: interactive LoG MIP (plotly, pixel values on hover); `plot_line_profile(rna_log_mip, start=(y, x), end=(y, x))`; histogram; optional export of the LoG MIP as TIFF for ImageJ.
7. Threshold: manual, auto (with elbow plot) or a calibrated preview; detection plot.
8. Decomposition, subpixel fitting, clusters, measurements (each skipped if switched off).
9. Steps 5–8 are repeated for each FISH channel by changing the channel cell; each channel's settings are kept in `config`.
10. Segmentation (Cellpose or label file) with the 4-panel QC.
11. Cell assignment and final QC.
12. Optional: save this image's results (run folder layout).
13. Batch settings and saving the config YAML.

Each step has one short parameter cell whose values are written into `config`. Users edit Python values; no widgets.

## 10. Streamlit app (brief: H1–H7)

### 10.1 Structure and look

- `app/app.py`: page config (wide layout), `st.navigation` with hidden menu and a top button bar (as in smFISHProbeDesign); pages `optimise.py`, `batch.py`, `results.py`, `help.py`.
- `app/.streamlit/config.toml`: smFISHProbeDesign palette and settings with an open font in place of Styrene B (section 17).
- Reused from the archived app: per-session step cache (`hash_payload`, `get_cached_stage_result`), `stretch_for_display`, `show_matplotlib_figure` (closes figures), the plotly LoG hover view with threshold histogram.
- Large images are downsampled for display only (about 1024 px), shown as MIPs with percentile contrast. Loaded images and the Cellpose model are cached with `st.cache_resource`, keyed on path and modification time.

### 10.2 Optimise page

- Top: input (folder picker + filter + matching file list, or OMERO login + image ID), image information to confirm, channel MIP previews, preset choice, FISH channel picker.
- One long page with collapsible steps in pipeline order (expanders). Each step has its settings, a Run button, and its result figures; results are cached until a setting changes.
- Threshold helper: LoG MIP with pixel values on hover; intensity profile along a line between two clicked points (`streamlit-image-coordinates`) or typed end points; histogram with the threshold marked; detected spots redrawn as the threshold slider moves.
- Sidebar: editable settings of the current step and channel, plus a short summary of the whole config.
- End of page: save config (download or to a folder), "Send to Batch", and optionally save this image's results.

### 10.3 Batch page

- Config from the Optimise page, from a YAML file, or from a previous run's `run_config.yaml`.
- Batch settings: input folder (folder picker) and filter with the matching file list, output folder, workers (suggested value shown), keep awake.
- Validation before starting, with plain messages.
- Start launches `bigfish-pypeline batch` as a separate process; the user never opens a terminal. Credentials for OMERO runs are passed as a session key in the child process environment, never as a password.
- Live view, refreshed every ~2 s from `progress.json` and `run.log`: progress (n of N, current image), log tail, failures table, Cancel button.
- Recent runs are listed in a small file in the user's home folder (`~/.bigfish-pypeline/runs.json`), so the page reconnects to a running batch after a browser refresh.

### 10.4 Results page

- Choose a run folder (picker or recent runs).
- Summary from `images.csv` (filter by status), run details, link to the log.
- Per image: QC images; interactive final view built on demand from the tables and labels when the original image is reachable; downloads.

### 10.5 Help page

Link to the guide, quick-start steps, pipeline version and device information.

### 10.6 Folder picker and launchers

- Folder picker: a native folder dialog opened by a small helper process (`tkinter`); if unavailable, a text box. Typed paths are cleaned (quotes and surrounding spaces removed, `~` expanded) and checked.
- Launchers: `launchers/bigfish-pypeline.command` (macOS) and `launchers/bigfish-pypeline.bat` (Windows) activate the conda env from its default Miniforge location and run `bigfish-pypeline app`; a clear message is shown if conda is not found. WSL2 users start the app from the Ubuntu terminal (documented).

## 11. Development phases (brief: A3)

Each phase ends with its tests passing, a devlog entry, and user review before merging into `main`.

### Phase 0: Foundations

- Tag the current `main` as `v1.0`; create the `msp` branch.
- Create `msp-environment.yml` and the `bigfish-msp` env (section 4.3), `pyproject.toml` skeleton, `tests/` with `pytest`, and `msp-devlog.md`.
- Test data:
  - The user curates full-size test images (suggested set: smFISH in cultured cells with segmentation, smFISH in tissue, HCR, a negative control, an image with ≥ 3 FISH channels, a file name with spaces). They stay on the laptop, outside git; tests find them through the `BIGFISH_TEST_DATA` environment variable and are skipped when it is not set.
  - Test kits: small crops of those images (target total < 20 MB) committed to `tests/data/`, each with its config.
- Reference run: the current v1 batch scripts (general, HCRv3, tissue-culture) run in the unchanged main env on the full images and on the test kits, with manual and auto thresholds, subpixel on and off, and Cellpose 3 + `extract_cell` for the tissue script. Configs, commands and `conda env export` are stored with the outputs. Existing outputs from earlier lab runs can be added as a further reference.
- Benchmarks on one full-size image: time and memory of top-hat vs rolling ball at 5 px per channel, and of the v1 steps.

Done when: reference outputs, test kits and benchmark numbers are recorded, and `pytest` runs in `bigfish-msp`.

### Phase 1: Package and unified pipeline (v1 algorithms)

- Package modules (section 4.1) with the v1 algorithms: top-hat background, Cellpose 3 (`models.Cellpose`, invalid `mask_threshold` argument removed, model loaded once).
- Image input (local and OMERO), 2D and 3D, any number of channels, layout and voxel-size confirmation.
- Config schema version 1 with validation; `bigfish-pypeline batch` and `check`.
- Threshold modes (manual, auto with lower limit, calibrated), bailout as a general option, measurements (SNR, intensity), label-file input, new cell assignment.
- Batch runner (section 7) with per-image error handling, sorted image order, streamed segmentation, cancel.
- Per-image and combined CSV tables (section 8.2) so results can be compared with the reference.
- v1 bugs fixed here: manual thresholds limited to two channels, workers stopping silently on errors, model reloaded per image, config read from the current folder with the unsafe loader, unsorted image order, bailout without a log entry.

Done when: on the test kits and full images, with the reference settings, spot and cluster coordinates are identical to v1; per-cell counts match `extract_cell` for cells not touching the border; any difference is explained in the devlog.

### Phase 2: Package upgrades

- big-fish fork (`/Users/jefflee/Documents/Incubator/big-fish`, based on `master` = 0.6.2): guard the `selem` imports, replace `selem=` with `footprint=`, replace `np.int`, fix whatever big-fish's own tests flag under the new stack, set version `0.6.2.post1`, tag and push. Optionally offer the fixes to fish-quant as a pull request.
- Update `msp-environment.yml` to the Phase 2 stack (section 4.3) and rebuild the env.
- Rolling ball: copy the file, add its ImageJ reference tests (and fixture, if small), add the `method` option.
- Cellpose 4: model, device selection, pre-treatment, eval settings, 4-panel QC, label saving (section 5.7).
- Comparisons, recorded in the devlog with figures:
  1. New stack with top-hat vs Phase 1 (expected identical or explained).
  2. Rolling ball vs top-hat (spot counts, threshold values, examples).
  3. Cellpose 4 (`cpsam_v2`) vs Cellpose 3 `cyto` masks (cell counts, overlap); accepted or adjusted by the user.
- Benchmarks: rolling ball on full stacks, Cellpose-SAM on Apple GPU and CPU, memory per worker; set the `workers: auto` estimate.

Done when: big-fish tests pass in the new env, the package tests pass, and the three comparisons are reviewed by the user.

### Phase 3: Outputs, logs and QC

- Run folder layout, `run_config.yaml`, `run_info.yaml`, `run.log`, `progress.json`, combined tables, optional `.npz`.
- QC images with their switches (section 8.3), including the elbow plot with the threshold value, the calibration plot and the final QC (PNG and HTML).
- Keep-awake during runs.

Done when: a full run on the test kits produces every output; re-running from `run_config.yaml` gives identical tables; a cancelled run leaves combined tables for finished images; the user has reviewed sample QC images and the log.

### Phase 4: Optimise notebook

- `notebooks/bigfish-optimise.ipynb` (section 9), committed without outputs.

Done when: the notebook runs top to bottom on a test kit inside the test suite, and the config it saves runs unchanged through `bigfish-pypeline batch` with results identical to the notebook's own saved results for that image.

### Phase 5: Streamlit app

- Pages, look, folder picker, threshold helper, batch launching and monitoring, results browsing, launchers (section 10).
- Add Streamlit, plotly and `streamlit-image-coordinates` to the env.

Done when: smoke tests pass for every page; a config sent from Optimise to Batch gives results identical to the command line; cancel and reconnect after refresh work; the user has walked through the app on a Mac.

### Phase 6: Documentation

- README and Quarto guide (section 14); screenshots with `playwright-cli` into `www/screenshots/`; site published on GitHub Pages.

Done when: every config setting is documented, the guide builds without errors, and the user has reviewed it.

### Phase 7: Windows and Linux testing

- Native Windows (app through the `.bat` launcher, command line, CUDA, OMERO), WSL2 Ubuntu with an NVIDIA GPU (including Windows paths under `/mnt/c/` and pasted `C:\…` paths), and Linux, all in the `bigfish-msp` env.
- Full test suite on each, plus one full-size batch on the lab workstation.
- Fixes made on the `msp` branch and re-tested on the affected systems.

Done when: the test suite passes on native Windows, WSL2 and Linux, and the user has reviewed the workstation batch.

### Phase 8: Main env, old folders and release

Only on the user's instruction, after Phase 7:

- Replace `environment.yml` with the new stack; update `AGENTS.md` (Cellpose 4 in the main env).
- Move `general/`, `HCRv3_spot-count/`, `tissue-culture_cells/`, `omero/` and `posthoc_analysis/` to `docs/archive/`; archive `general/further_analysis/*.qmd`.
- Merge `msp` into `main`; tag `v2.0`.

## 12. Testing

- **Unit tests (synthetic data):**
  - PSF values.
  - Top-hat against scikit-image; rolling ball against the ImageJ fixture.
  - Detection of Gaussian spots at known positions (all found within 1 px; none on a blank image).
  - Each threshold mode, lower limit and bailout.
  - Clusters on synthetic clusters.
  - Cell assignment on synthetic labels with adjacent cells and border cells (guards against the v1 notebook bug).
  - Config validation messages and YAML round trip.
  - File discovery (filter, extension, top level only, sorting, spaces and accents in names).
  - Image layouts (2D/3D, single or several channels).
  - Table columns and the `-1` conventions.
- **Regression tests:** test kits against their v1 reference outputs (in the repo); full images against the reference run (local, `BIGFISH_TEST_DATA`).
- **End-to-end tests:** `bigfish-pypeline batch` on 2–3 test kits, with and without segmentation, including a failing image and a cancelled run. Tests that need the Cellpose weights are marked so they can be skipped.
- **Notebook test:** the optimise notebook executed on a test kit.
- **App tests:** Streamlit `AppTest` smoke tests per page; config round trip Optimise → Batch.
- **Manual checks:** listed at the end of each phase in the devlog and signed off by the user.
- macOS only until Phase 7.

## 13. Edge cases

| Case | Expected behaviour | Tested in |
|---|---|---|
| Spaces, accents or other non-ASCII characters in paths and file names | Processed normally | unit, end-to-end |
| Windows paths pasted into the app (`C:\…`) or used in WSL2 (`/mnt/c/…`) | Accepted; converted under WSL2 | Phase 7 |
| Very long paths on Windows | Clear error if the path cannot be used | Phase 7 |
| Image with no spots | Empty spot rows, status done, elbow plot still written; lower limit applies | unit, regression (negative control) |
| Single-plane (2D) image | 2D processing; no z columns | unit |
| Different image sizes in one batch | Each processed at its own size | end-to-end |
| Image layout differs from the config (e.g. missing channel) | Image fails with the reason | end-to-end |
| Channel index out of range | Stopped before processing (checked on the first image); per image afterwards | unit |
| Two inputs giving the same output name | Stopped before processing with the clashing names | unit |
| Calibration filter matches no image | Stopped before processing | unit |
| Bailout limit exceeded | Channel skipped with the reason | unit |
| Missing or mismatched label file | Cell-level results skipped with a warning; `cell_id = -1` | unit, end-to-end |
| Cellpose finds no cells | Warning; empty cell table; `cell_id = -1` | unit |
| Corrupt or unreadable file; NaN or infinite values | Image fails with the reason; run continues | end-to-end |
| Input stored as 8-bit, 16-bit or 32-bit float | Processed | unit |
| Voxel sizes missing from metadata | Must be entered; never assumed | unit, app |
| Metadata voxel sizes differ from the config | Config values used; warning logged | unit |
| Very large image or out of memory | Workers limited by memory; a dead worker's images fail and the run continues | end-to-end, Phase 2 benchmarks |
| No GPU | CPU used, warning about time | unit |
| OMERO connection drops | One retry, then the image fails | manual (lab network) |
| Output folder not writable | Stopped before processing | unit |
| Input folder already contains `bigfish_results/` | Ignored (top level only) | unit |
| Run cancelled or computer sleeps | Finished images kept and combined; run marked cancelled; keep-awake on by default | end-to-end |
| `tkinter` missing | Text box instead of the folder dialog | app |
| Browser refreshed during a batch | Batch page reconnects to the running batch | app |

## 14. Documentation (brief: J3)

**README (root):** what the pipeline does and for which experiments, installation in brief, quick start for the app and the command line, link to the guide, citation, licence, to-do list.

**User guide:** Quarto website from `docs/guide/`, published on GitHub Pages (HTML only).

1. Start here: choosing a preset by experiment type (smFISH in cells or tissue, HCR, RNAscope; whole image or per cell).
2. Installation: Miniforge, creating the env, GPU notes (Apple, NVIDIA on Windows and WSL2), first-run Cellpose model download (~1.2 GB).
3. Preparing images: converting to TIFF in Fiji, image layout, voxel sizes.
4. Optimising in the app, step by step, with screenshots.
5. Optimising in the notebook.
6. Running a batch (app and command line).
7. Understanding the outputs: each table and QC image, and how to match results back to images.
8. Settings reference: every config setting, what it does, how to choose a value, default, related QC image.
9. Background: RNA-FISH methods, what each big-fish step does, rolling ball vs top-hat, Cellpose-SAM; links to big-fish (paper and documentation), Cellpose, ImageJ, Fiji, OMERO.
10. Troubleshooting.
11. For existing users: v1 config names → v2, `.npz` → CSV, why manual threshold values shift with rolling ball.

Screenshots: taken from the running app with `playwright-cli`, cropped, saved as `www/screenshots/<page>-<step>.png`. `_quarto.yml` sits at the repo root and renders only `docs/guide/`, so images in `www/screenshots/` are included in the site.

Code docstrings and comments: short and plain, no meta-narration.

## 15. Risks

| Risk | Mitigation |
|---|---|
| big-fish behaves differently under numpy 2, scipy 1.18 or scikit-image 0.26 | big-fish's own tests in the fork; Phase 2 comparison with Phase 1 |
| scikit-image removes `square`/`rectangle` used by big-fish | scikit-image pinned below 0.27; patch in the fork if needed |
| Rolling ball at 5 px too slow for 100–200 images | Phase 0 benchmark; top-hat option |
| Cellpose-SAM slow without a GPU | Device warning; guide recommends a GPU machine for large batches |
| Cellpose 4 masks differ from Cellpose 3 | Phase 2 comparison reviewed by the user |
| Memory per worker higher than expected | Worker estimate from measurements; dead-worker recovery |
| Native Windows untested until Phase 7; OMERO untested on Windows by its developers | Cross-platform coding rules from the start; Phase 7 testing before release |
| Library updates break the env | Exact versions pinned and recorded |
| Streamlit API changes | Streamlit version pinned |
| `tkinter` behaviour differs between systems | Text-box fallback |

## 16. Later (to-do)

- Nucleus segmentation alongside cytoplasm (README to-do).
- 3D segmentation and multi-channel Cellpose input.
- Other image formats (e.g. through `bioio`).
- Resuming interrupted runs.
- Uploading results to OMERO.
- Repo clean-up (brief: C4): commit notebooks without outputs, `.gitignore` entries for outputs, remove personal paths from example configs, fix the two GitHub owners in the README.

## 17. Points to confirm

These were not explicitly decided in the brief:

1. **Phase order 7 → 8.** Windows users would receive v2 (Phase 7) before Windows testing (Phase 8). Swapping the two phases would test first and release second. - Yes Swap the phases. 
2. **Phase 1 contents.** New threshold modes, measurements, label-file input, new cell assignment and the CSV tables are built in Phase 1 (they do not change the v1 algorithms, and the tables are needed for comparisons); logs, run record and QC images follow in Phase 3. - fine. 
3. **Dev env in Phases 0–1** uses the v1 stack, upgraded in Phase 2. - fine. 
4. **Run folder layout:** grouped by type (`labels/`, `qc/`, `per_image/`) rather than one folder per image, so labels can be reused directly and QC images of the same kind sit together. - fine. 
5. **File names** use the channel index (`_ch2`); channel names appear only in the tables. - fine.
6. **Spot intensity definition:** value of the background-subtracted image at the spot's pixel (alternatives: raw image value, or mean over the spot). - MIP rna_log value (so background subctracted and log filtered).
7. **Font:** Inter or IBM Plex Sans. - choose one for me. 
8. **`posthoc_analysis/`:** left as it is, or archived in Phase 7. - archived in phase 7. 
9. **Optimise page sidebar:** editable settings of the current step and channel plus a whole-config summary. - fine. 
10. **Cellpose `batch_size`:** 1 as in the workbook (gentle on memory), or Cellpose's default 8 (faster on a GPU). - stick to 1. 
