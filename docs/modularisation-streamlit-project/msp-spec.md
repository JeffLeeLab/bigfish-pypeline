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
- Users download the repository and create the conda environment with Miniforge. Creating the environment also installs the pipeline from the downloaded folder, so that folder must stay where it is. No other installation steps are expected of them.
- Development and testing on macOS until Phase 7, which tests native Windows, WSL2 and Linux before the v2.0 release (brief: J1).

## 3. Working rules

- Development happens in the `bigfish-msp` conda env (`docs/modularisation-streamlit-project/msp-environment.yml`). The main `bigfish-pypeline` env and `environment.yml` stay unchanged until the user says otherwise (Phase 8). The main env is used only to produce the v1 reference results (Phase 0).
- The model that orchestrates the work and the models and effort levels that carry out each task are set out in `msp-plan.md` (brief: R9). Repo exploration and web research use Haiku subagents; simple documentation updates use Sonnet subagents.
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
    steps.py                the steps of one channel, each reading its settings from the config; used by the batch, the notebook and the app
    notebook.py             small helpers for the Optimise notebook (problems shown as one plain line)
    outputs.py              tables, run folder, run record, combining per-image files
    qc.py                   QC figures
    batch.py                batch runner (process pool, logging, progress, cancel)
    cli.py                  command-line entry point
app/                        Streamlit app (section 10)
launchers/                  double-click launchers (.command, .bat)
notebooks/                  bigfish-optimise.ipynb
tests/                      unit, regression and end-to-end tests; tests/data/ test kit
docs/guide/                 Quarto user guide source
www/screenshots/            screenshots used by the guide
pyproject.toml
_quarto.yml                 Quarto website project (renders docs/guide/ only)
```

### 4.2 Commands

- `bigfish-pypeline batch <config.yaml> [--input-folder …] [--filter …] [--output-folder …] [--workers …]`: values given on the command line override the file (brief: F2). The run folder is shown before the summary, and the last line in the terminal says how the run ended, with the number of failed and skipped channels; the command ends with 0 when the run finished, also when images failed.
- `bigfish-pypeline check <config.yaml>`: validates a config and lists the images it would process, without running anything. Images whose pixel type cannot be used are listed with the reason.
- `bigfish-pypeline app`: starts the Streamlit app. The command finds `app/` in the repository folder and starts Streamlit with `app/` as its working folder, so it can be run from anywhere.
- Installed from the repository folder with `pip install -e .`, which the environment file runs (entry point declared in `pyproject.toml`).

### 4.3 Software environment

`msp-environment.yml` uses the stack below from Phase 0 (brief: B1–B4, R1). The v1 reference results come from the unchanged main env (Python 3.9, Cellpose 3.1.1.2).

The versions listed are targets. The versions actually installed are recorded in the devlog when the env is first built on each system (macOS in Phase 0; Windows, WSL2 and Linux in Phase 7), together with the device PyTorch uses there. If conda-forge has no suitable build of a listed version for a system, the nearest version that has one is used and recorded.

| Package | Source | Version |
|---|---|---|
| python | conda-forge | 3.12 |
| numpy, scipy, scikit-image, scikit-learn, matplotlib, pandas, tifffile, pyyaml, tqdm | conda-forge | current; scikit-image < 0.27; pandas 3 only if big-fish tests pass, otherwise < 3 |
| pytorch | conda-forge | 2.14.1 (selects CUDA, Apple GPU or CPU build per machine) |
| zeroc-ice, omero-py | conda-forge | 3.6.5, 5.22.x |
| pydantic, plotly, tk, jupyterlab, ipykernel, pytest, pytest-xdist | conda-forge | current |
| streamlit | conda-forge | current, pinned (Phase 5) |
| cellpose | pip | 4.2.1.1 |
| imagecodecs | pip | current, pinned; reads packed 12-bit and compressed TIFF files |
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
- Images are read with `tifffile`. Accepted layouts: `ZCYX`, `CZYX`, `ZYX`, `CYX`, `YX` (2D and 3D, one or several channels). The detected layout and image dimensions are shown and must be confirmed by the user; the confirmed layout is stored in the config. A time axis of length 1 is dropped; files with several time points or positions are rejected with a message.
- In a batch, each file's own axes, when its metadata gives them (ImageJ, OME, or the axes that `tifffile` writes), must equal the confirmed layout, whether or not they are one of the accepted layouts. A file that does not match fails with a message naming both, and the run goes on. A file whose metadata does not give its axes is read with the confirmed layout.
- Pixel types: 8-bit, 12-bit and 16-bit images are accepted. A 12-bit image is read as 16-bit, whether its values are saved in a 16-bit file or packed as 12-bit. A TIFF file must store 8, 12 or 16 bits per pixel: packed files of another depth (e.g. 10-bit) are refused. Any other type (32-bit float, signed, 32-bit) is refused by `bigfish-pypeline check` and when the image is opened, before any work on it, with a message that names the type found and says how to convert the image to 16-bit in Fiji. The same holds for OMERO images.
- Voxel sizes are read from ImageJ or OME metadata when present and shown for confirmation. Missing values must be entered; no silent defaults. In batch, an image whose metadata disagrees with the config is processed with the config values and a warning is logged.
- One pixel size is used for both X and Y. If the metadata gives different X and Y sizes, this is shown and the user enters the value to use.
- Channel numbers count from 0 and always refer to the channel's position in the original file, also when only some channels are read.
- 2D images are processed as 2D throughout (YX coordinates, two-value voxel size and spot radius); no dummy Z axis is added.
- Other formats: the guide explains conversion to TIFF in Fiji.

**OMERO**

- Optimise by image ID; batch by dataset ID or a list of image IDs.
- Default host and port of the lab server are stored in the package (public repo is acceptable).
- Passwords are asked each time and never written to disk. Session keys are never written to the config, the run record or the log.
- One process owns the OMERO session: it logs in, keeps the session alive and closes it at the end. In a command-line batch this is the main batch process. When the app starts a batch, the app hands its session to the batch process, which then keeps it alive and closes it when the run ends; the user logs in again for further OMERO work in the app.
- Batch workers join the session with its key (passed in memory) instead of logging in again, and only detach when they finish (`conn.close(hard=False)`). They never close the session, because closing it from one process ends it for all of them. This behaviour is checked against the lab server in Phase 1.
- Images are streamed into memory and not saved locally. Outputs go to a local folder chosen by the user.
- Output names use `<image ID>_<image name>` so that images with the same name in one dataset do not collide. Characters that Windows does not allow in file names are replaced with `_`.
- `omero_tools.connect_to_omero` (login by the owning process) and `get_omero_image` are reused; a second helper lets workers join by session key without the close-on-exit step. The archived app's OMERO metadata reader (voxel sizes converted to nm) is brought in.

### 5.4 Background subtraction (brief: B5)

- `subtract_background(image, radius, light_bg=False, method="rolling_ball")`, applied to each Z-plane.
- `rolling_ball`: the single file `misc/python-rolling-ball/imagej_rolling_ball.py` from JeffLeeLab/Image-analysis, copied into the package with a header naming the source repo and commit. Default.
- `tophat`: the current white top-hat with a disk, kept to reproduce v1 results.
- Defaults: radius 5 px for FISH channels; radius 200 px for the segmentation channel (section 5.7).

### 5.5 Spot detection and thresholds (brief: D4, D5)

- PSF per channel from `calculate_psf` with that channel's ex/em; LoG filter, local maxima and thresholding as in v1.
- Threshold modes, set per channel:
  - `manual`: one value per channel. Works for any number of channels (fixes the v1 two-channel limit).
  - `auto`: big-fish elbow method on each image, with an optional lower limit that the value cannot go below. On an image with noise but no real spots the elbow method returns a low value and many false spots; the lower limit protects against this. If big-fish finds no candidate spots at all and returns no threshold, the channel finishes with zero spots, an empty threshold and a warning. Zero is never used in place of a missing threshold.
  - `calibrated`: before the main run, `auto` (with the lower limit, if set) runs on the images whose names contain a chosen text; the median of those values is then used as a fixed threshold for every image. The per-image values are saved as a table and a plot. Images that cannot be read or give no automatic threshold are left out of the median and listed with the reason in the table. Bailout is not applied during calibration. The run stops before the main run if a channel has no usable value.
- Bailout (optional, any mode): if an image has more spots than a set limit for a channel, the remaining steps for that channel are skipped, and that channel is marked "skipped" with the reason in the log and in `images.csv`. Other channels of the same image are not affected.

### 5.6 Decomposition, subpixel fitting, clusters, measurements (brief: D7, D8)

- Decomposition as in v1: Gaussian-denoised copy (sigma = 5 × spot radius) for `build_reference_spot`, `modelize_spot`, `get_dense_region` and `simulate_gaussian_mixture`; alpha 0.5, beta 1. As in v1, two reference spots are built for every image and channel: one from the denoised copy, used for the spot model, and one from `rna`, saved as the QC TIFF.
- Decomposition is skipped for a channel, and the detected spots are passed on unchanged, when there are no spots, when no reference spot can be built, when the spot model cannot be fitted, or when no dense regions are found. Each case except the last is recorded as a warning in the log and in `images.csv`.
- big-fish builds the reference spot from a random 2,000 spots when an image has more. The random seed is set before each call from `run.seed`, the image name and the channel number, so a repeated run gives the same result whatever the order of the workers.
- Subpixel fitting: `detection.fit_subpixel` on the current spots; skipped when there are none.
- Clusters: `detection.detect_clusters` on the current spots, radius 500 nm, minimum spots 4 (big-fish default). A cluster's centre is the exact mean position of its spots (decimals), also when the spots are at whole pixels; v1 cut the centre to whole pixels in that case. The clusters and their spots are the same as in v1.
- Measurements, taken at each spot's pixel position (not the subpixel position):
  - SNR: the posthoc function `compute_snr_spots_individual`, extended to 2D images. On `rna`, the mean within the spot radius minus the mean of a surrounding ring (1.5 to 2.5 times the radius), divided by the standard deviation of the ring. The value is left empty when the ring is empty or has no variation.
  - Intensity: the value of `rna_log` at the spot's own position (z, y, x; or y, x in 2D), which is the value the threshold was applied to. Column `log_intensity` (brief: R3).

### 5.7 Segmentation (brief: B4, D9, D10, E4)

**Cellpose**

- One input channel, 2D. Pre-treatment, in order: Z projection (max or mean), of every plane or of the planes chosen in `segmentation.z_planes` → background subtraction (on; rolling ball, radius 200 px; or top-hat), after which values below 0 are set to 0 → clip (off; value 100) → median filter (off) → Gaussian filter (off). The clip comes after background subtraction, so its value does not depend on the camera offset; v1 clipped first.
- `segmentation.z_planes` gives the first and last plane of the projection, counted from 0 and both included; either may be left empty (from plane 0, or up to the image's last plane). It is for cultured cells, where the lower planes hold cells spread over the coverslip and the stain of neighbours merges. Spot detection always uses every plane.
- Cellpose 4 `CellposeModel(pretrained_model="cpsam_v2", use_bfloat16=False)`.
- Default `eval` settings follow the Cellpose-SAM workbook: `normalize=True`, `diameter=None`, `flow_threshold=0.4`, `cellprob_threshold=0`, `min_size=15`, `batch_size=1`, `niter=None`, `do_3D=False`.
- Device chosen automatically: CUDA, then Apple GPU (MPS), then CPU. A quick test calculation on the chosen device runs before the model loads, the device used is logged, and running on CPU triggers a warning that segmentation will be slow.
- The model is loaded once per batch run (main process) and cached in the app. The app releases its copy when a batch starts, so two copies are not held in memory.
- The 4-panel QC figure from the workbook's `qc_figure` is rewritten to take its settings as arguments instead of reading notebook-wide variables. Its title shows the projection, channel, pre-treatment, diameter, cell count and time.
- Label images are saved as `<image>_seglabels.tif` (uint32, 2D) when switched on. The file carries the pixel size, so that Fiji shows µm.

**Label files**

- The user chooses a folder; each image's labels are read from `<image>_seglabels.tif`. Only 2D labels whose shape matches the image's Y × X are accepted, and they must hold whole numbers of 0 or more, with 0 as background.
- A missing, mismatched or invalid label file skips cell-level results for that image with a warning; spot results are still written.

### 5.8 Cell assignment (brief: D11, E1)

- Each spot is looked up in the 2D label image at its pixel position (y, x), also when subpixel fitting is on; each cluster at its centre. The label value is the `cell_id` (matching the Cellpose label); positions outside any cell get `cell_id = -1`. This replaces big-fish `extract_cell` and avoids the v1 notebook bug.
- `touches_border` is recorded for every cell; `drop_border_cells` (off by default) removes those cells and sets their spots and clusters to `cell_id = -1`.
- A cluster can lie across a cell boundary. Its spots are counted in the cells they sit in, and the cluster itself in the cell that holds its centre (section 8.2).
- No minimum cell area filter.

## 6. Configuration file (brief: F1–F3)

### 6.1 Principles

- One YAML layout written by the notebook and the app and read by the batch; the same names are used everywhere.
- Validated by a `pydantic` model before any image is processed. Messages are in plain English and name the setting, e.g. "`nb_min_spot` is not a known setting – did you mean `min_spots`?" or "`voxel_size_nm.z` must be a positive number". Unknown settings are errors, not silently ignored.
- Values that a step cannot use are refused: `decomposition.alpha` outside 0 to 1, `decomposition.beta` of 0 or less, a background radius below 1 px, `clusters.min_spots` below 2, `cellpose.min_size` below −1, an empty `cellpose.model`, and an infinite or missing number (`.inf`, `.nan`) in any setting.
- `config_version` identifies the layout so later versions can convert older files.
- Loaded with the safe YAML loader.
- Switches are written `enabled: true` or `enabled: false`. The words `on`, `off`, `yes` and `no` are not used as setting names or choices, because YAML reads them as true or false.
- Old v1 configs are not read; the guide has a page mapping old names to new ones.
- `image.axes` and `image.voxel_size_nm` have no default values; a config without them is rejected. The notebook and the app suggest values from the metadata, which the user confirms.
- Folders may be given relative to the config file's folder; full paths are saved in `run_config.yaml`.

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
  seed: 0                          # fixes the random choice of spots for the reference spot
image:
  axes:                            # required, e.g. ZCYX; confirmed by the user
  voxel_size_nm: {z: , yx: }       # required; confirmed by the user; z left out for 2D
microscope:
  type: confocal                   # confocal | widefield | nipkow
  NA: 1.45
  RI: 1.45
channels:
  - index: 2                       # counted from 0
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
  z_planes: {first: , last: }      # planes of the projection, counted from 0; empty = every plane
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

### 6.3 Repeating a run

`run_config.yaml` in a run folder also records what the run worked out for itself, in a `resolved` block written by the pipeline: the list of images and any calibrated thresholds. It can be used in two ways (brief: F3):

- **Repeat the run:** passing the file back unchanged processes the same images with the same thresholds, without calibrating again. The run stops before processing if a listed image is missing.
- **Same settings, other images:** giving a new input folder, filter or image IDs (on the command line or the Batch page) drops the `resolved` block, so images are listed and thresholds calibrated afresh.

A repeated run on the same computer gives the same tables. Tables are compared after sorting, leaving out `runtime_s`. Cellpose masks can differ slightly between devices (GPU or CPU), so per-cell results are expected to match exactly only on the same device.

## 7. Batch runs (brief: F5, G1)

### 7.1 Run flow

1. Validate the config; list the images; check that the output folder can be written; check every image from its file header against the settings (pixel type, layout, channels). The run stops before processing with a plain message when the settings are not valid, the output folder cannot be written, or no image at all can be used. An image that cannot be used among images that can is left to fail in the run with its reason, and `check` lists it.
2. Create the run folder, start `run.log`, and write `run_config.yaml` (all defaults filled in, with the image list) and the first part of `run_info.yaml`.
3. Start a pool of worker processes (`concurrent.futures.ProcessPoolExecutor`, "spawn" start method). Before the pool starts, `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` are set to 1 so workers do not compete for cores.
4. If any channel uses `calibrated` thresholds, run `auto` on the subset in the pool, write `calibration.csv` and its plot, fix the threshold values and add them to `run_config.yaml`. This step is skipped when the config already holds calibrated values from an earlier run (section 6.3).
5. Streamed processing:
   - With Cellpose: the main process loads the model once, then for each image in order reads only the segmentation channel, segments it, saves the labels, and submits that image to the pool. Segmentation of the next image overlaps with spot detection of earlier ones.
   - With label files or no segmentation: images go to the pool in order.
   - Each worker reads only the FISH channels it needs, runs steps 1–8 and 10 for each channel, writes that image's tables and QC files, and returns a summary row for each channel.
   - The main process hands an image to the pool only when a worker is free, so it always knows which images are in progress and segmentation never runs far ahead of detection.
   - Labels always reach the workers as files. When `outputs.label_images` is off they are written to a temporary folder in the run folder and deleted as each image finishes.
   - A worker writes an image's files under temporary names and renames them once all are written. An image counts as finished only after this, so every file in `per_image/` is complete.
6. The main process writes each result to `run.log`, records failures, and replaces `progress.json` with a new copy (written under a temporary name, then renamed, at least every 10 s) so the app never reads a half-written file.
7. At the end, the per-image tables of finished images are combined into one table per type, `run_info.yaml` is completed, and the summary is logged.

Each image is complete as soon as its detection finishes, so a stopped run keeps every finished image. Interrupted runs are not resumed; the user re-runs into a new run folder.

### 7.2 Workers and memory

- `workers: auto` = the smaller of (CPU cores − 1) and (available memory ÷ estimated memory per worker), after a reserve has been taken off the available memory.
- The reserve covers the main process, the Cellpose model when segmentation is on, and a safety margin. The per-worker estimate is based on the largest image in the list (sizes are read from the file headers) and the steps switched on. Both come from the Phase 0 and Phase 2 measurements (expected 3–4 GB for a 2048 × 2048 × 30 channel).
- The number of workers used and the reason are logged.
- If there is not enough memory for one worker, the run stops before processing with a plain message.

### 7.3 Errors, cancel and keep-awake

- Each image, and each channel within it, is processed inside its own error handling. A failure in one channel marks that channel "failed" with a one-line reason in `run.log` and `images.csv` (full details in the log); the other channels are kept. A failure that affects the whole image (e.g. an unreadable file) marks all its channels failed. The run continues in both cases.
- If a worker process stops unexpectedly (e.g. out of memory), every image in progress at that moment is lost, and it is not possible to tell which one caused it. A new pool is started with half as many workers (at least one) and those images are tried again once. An image caught in a second such stop is marked failed ("worker stopped unexpectedly, probably out of memory"). If it happens with a single worker, the run ends with a plain message and the finished images are combined. Each restart is logged (brief: R4).
- If the OMERO connection drops, the image is retried once after rejoining the session, then marked failed. If the session itself has ended, no new images start, the finished images are combined and the run ends with a message to log in and run again.
- Once a reason to stop the run is found (the OMERO session has ended, or results cannot be written), no further result is kept: the workers are stopped at once and the files of every image not yet recorded as finished are removed, whichever worker or step reported the reason.
- Cancel (Ctrl+C on the command line, or Cancel in the app): no new images start, the worker processes are stopped at once, images in progress are discarded, finished images are combined into the run tables, and the run is marked "cancelled" (brief: R4). The app cancels by writing a `cancel` file in the run folder, which the runner checks every second; this works the same on macOS, Windows and Linux.
- With `keep_awake: true`, the computer is kept awake for the length of the run (`caffeinate` on macOS, the system keep-awake request on Windows; Linux logs that this is not available).

## 8. Outputs (brief: E1–E4, F3, F4)

### 8.1 Run folder

Default location: `<input folder>/bigfish_results/<YYYY-MM-DD_HHMM>_<run name>/`; a number is added if that folder already exists. OMERO runs and read-only input folders must name an output folder. Saving results from the notebook or the Optimise page uses the same layout.

```
<run folder>/
    run_config.yaml        fully filled-in config with the image list and calibrated thresholds; passing it back repeats the run
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

`image` is the output name: the file name without its extension, or `<image ID>_<image name>` for OMERO. It is the same in every table and file name. `spot_id` and `cluster_id` are numbered from 0 within each image and channel; `cell_id` is the label value within each image. Rows are matched between tables on image + channel + `spot_id` or `cluster_id`, and on image + `cell_id`.

| Table | One row per | Columns |
|---|---|---|
| `spots.csv` | spot | image, channel, channel_name, spot_id, z_px, y_px, x_px, z_nm, y_nm, x_nm, [z_sub_px, y_sub_px, x_sub_px, z_sub_nm, y_sub_nm, x_sub_nm when subpixel fitting is on], cluster_id, cell_id, [snr], [log_intensity] |
| `clusters.csv` | cluster | image, channel, channel_name, cluster_id, z_px, y_px, x_px, z_nm, y_nm, x_nm, n_spots, cell_id |
| `cells.csv` | cell × channel (every label, including cells with no spots) | image, channel, channel_name, cell_id, area_px, area_um2, centroid_y_px, centroid_x_px, touches_border, n_spots, n_spots_in_clusters, n_spots_outside_clusters, n_clusters, mean_spots_per_cluster |
| `images.csv` | image × channel | image, channel, channel_name, status (done / failed / skipped), reason, threshold_mode, threshold, n_spots_detected, n_spots, n_clusters, n_cells, segmentation_source, segmentation_status (done / no_labels / failed; empty when segmentation is off), warnings, runtime_s |
| `calibration.csv` | subset image × channel | image, channel, auto_threshold (after the lower limit), elbow_threshold (the elbow method's value before the lower limit), used, reason |

In `cells.csv`, `n_spots`, `n_spots_in_clusters` and `n_spots_outside_clusters` count each spot in the cell it sits in. `n_clusters` counts the clusters whose centre lies in the cell, and `mean_spots_per_cluster` is the mean size of those clusters (empty when the cell has none). Because a cluster can lie across a cell boundary, a cell can have clustered spots without a cluster, and these numbers need not divide into one another.

In `images.csv`, `n_cells` is 0 when segmentation ran and found no cells, and empty when there were no usable labels. `warnings` lists anything that did not stop the channel (e.g. decomposition skipped, no candidate spots, metadata mismatch).

The optional `.npz` files use the v1 keys for old downstream scripts: `spots_post_clustering` and `clusters`, as written by the v1 general script, or `spots` for a channel with clusters switched off, as written by the v1 HCRv3 script. The `clusters` array always holds decimal numbers, because of the exact centres; in v1 it held whole numbers when subpixel fitting was off. The per-cell `.npz` files of the v1 tissue-culture script are not reproduced.

### 8.3 QC images

Each has its own switch (brief: E3). Names start with `<image>_ch<index>_`.

- `elbow.png`: elbow plot with the legend "Selected threshold = 11.0", plus the lower limit when set. Its axis names what is plotted: the natural log of the number of candidate spots above each threshold, smoothed, before spots sharing a peak are merged. In calibrated mode, `calibration.png` shows the per-image auto values and the median used, and marks the images whose value was raised to the lower limit.
- `detection.png`: spots (and clusters) over the MIP. Clusters are drawn as outlines, here and in the final QC, so that the spots of a bright focus stay visible.
- `referencespot.tif`: the reference spot built from `rna`, as in v1 (always TIFF). Not written when decomposition is switched off or skipped.
- `<image>_cellpose_qc.png`: 4-panel Cellpose QC (one per image).
- `final.png` or `final.html`: spots, clusters, cell outlines, and for each cell its index and counts. PNG by default; HTML (interactive, with hover) as an option. Only the cells of `cells.csv` are shown, so cells left out by `drop_border_cells` are not drawn.

### 8.4 Run record and log

- `run_info.yaml`: start and end time, pipeline version and git commit (when available), Python and key package versions (big-fish, cellpose, torch, numpy, scipy, scikit-image, scikit-learn, pandas, tifffile, pydantic, plotly, omero-py), OS, CPU count, memory, Cellpose device, workers, the command used, the random seed, any worker restarts, final status with a message that gives the number of failed and skipped channels, and calibrated threshold values. For each label file given by the user and each Cellpose model file of the user's own that the run read: its path, size, date last changed and SHA-256 checksum, so that a later run can tell whether a file has changed. A label file's checksum is worked out from the same bytes its labels are read from; a model file is recorded before it is loaded and checked again afterwards.
- `run.log`: config file used, image list, the spot radius in pixels of each channel, each image started / finished / skipped / failed with the reason, threshold used per image and channel, the cells found and kept when `drop_border_cells` is on, warnings (metadata mismatch, missing labels, CPU segmentation), and a summary (counts per status, total time). The total time is the duration given in `run_info.yaml`.

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
- `app/.streamlit/config.toml`: smFISHProbeDesign palette and settings with the open font Inter in place of Styrene B. Streamlit reads this file from its working folder, so the app is always started with `app/` as the working folder (section 4.2).
- Reused from the archived app: per-session step cache (`hash_payload`, `get_cached_stage_result`), `stretch_for_display`, `show_matplotlib_figure` (closes figures), the plotly LoG hover view with threshold histogram.
- Each step's cache key includes the key of the step before it, as in the archived app, and this is extended to segmentation and cell assignment. Changing an earlier setting (voxel sizes, PSF, background, threshold) therefore clears every later result, so results from old and new settings are never shown or saved together.
- Large images are downsampled for display only (about 1024 px), shown as MIPs with percentile contrast. Loaded images and the Cellpose model are cached with `st.cache_resource`: images keyed on path and modification time (for OMERO, server and image ID) plus the confirmed layout, the model on its name and device. Cached images are never changed in place.

### 10.2 Optimise page

- Top: input (folder picker + filter + matching file list, or OMERO login + image ID), image information to confirm, channel MIP previews, preset choice, FISH channel picker.
- One long page with collapsible steps in pipeline order (expanders). Each step has its settings, a Run button, and its result figures; results are cached until a setting changes.
- Threshold helper: LoG MIP with pixel values on hover; intensity profile along a line between two clicked points (`streamlit-image-coordinates`) or typed end points; histogram with the threshold marked; detected spots redrawn as the threshold slider moves.
- Sidebar: editable settings of the current step and channel, plus a short summary of the whole config.
- End of page: save config (download or to a folder), "Send to Batch", and optionally save this image's results.

### 10.3 Batch page

- Config from the Optimise page, from a YAML file, or from a previous run's `run_config.yaml`. For a previous run, the page offers "Repeat this run" or "Use these settings on other images" (section 6.3).
- Batch settings: input folder (folder picker) and filter with the matching file list, output folder, workers (suggested value shown), keep awake.
- Validation before starting, with plain messages.
- Start launches `bigfish-pypeline batch` as a separate process; the user never opens a terminal. For OMERO runs the app hands its session to the batch process as a session key in that process's environment, never as a password (section 5.3).
- Live view, refreshed every ~2 s from `progress.json` and `run.log`: progress (n of N, current image), log tail, failures table, Cancel button.
- Recent runs are listed in a small file in the user's home folder (`~/.bigfish-pypeline/runs.json`), so the page reconnects to a running batch after a browser refresh. A run is shown as running only while its `progress.json` says so and has been refreshed in the last minute; otherwise it is shown as stopped. Cancel always acts through the run folder's `cancel` file, never on a process number, so it cannot affect anything else.

### 10.4 Results page

- Choose a run folder (picker or recent runs).
- Summary from `images.csv` (filter by status), run details, link to the log.
- Per image: QC images; interactive final view built on demand from the tables and labels when the original image is reachable; downloads.

### 10.5 Help page

Link to the guide, quick-start steps, pipeline version and device information.

### 10.6 Folder picker and launchers

- Folder picker: a native folder dialog opened by a small helper process (`tkinter`); if unavailable, a text box. Typed paths are cleaned (quotes and surrounding spaces removed, `~` expanded) and checked.
- Launchers: `launchers/bigfish-pypeline.command` (macOS) and `launchers/bigfish-pypeline.bat` (Windows) activate the conda env from its default Miniforge location and run `bigfish-pypeline app`; a clear message is shown if conda is not found. WSL2 users start the app from the Ubuntu terminal (documented).

## 11. Development phases (brief: A3, R1)

Each phase ends with its tests passing, a devlog entry, and user review before merging into `main`.

### Phase 0: Foundations

- Tag the current `main` as `v1.0`; create the `msp` branch.
- big-fish fork (`/Users/jefflee/Documents/Incubator/big-fish`, based on `master` = 0.6.2): guard the `selem` imports, replace `selem=` with `footprint=`, replace `np.int`, fix whatever big-fish's own tests flag under the new stack, set version `0.6.2.post1`, tag and push. Optionally offer the fixes to fish-quant as a pull request.
- Create `msp-environment.yml` and the `bigfish-msp` env (section 4.3), `pyproject.toml` skeleton, `tests/` with `pytest`, and `msp-devlog.md`.
- Test data (brief: R2, R6, R7):
  - Full-size image: `20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001.tiff` (ZCYX, 35 × 4 × 2048 × 2048, 16-bit; 65 nm pixels, 200 nm Z-steps; channels 0 DAPI, 1 Phalloidin, 2 jim exon, 3 jim intron). Channel 2 (exon) is the FISH channel used for testing; the intron channel is not used. The DAPI channel is kept for later work on nucleus segmentation. The image stays on the laptop, outside git; tests find it through the `BIGFISH_TEST_DATA` environment variable and are skipped when it is not set. Further local images (e.g. a negative control, an HCR image) can be added for visual review but are not required.
  - Test kit, committed to `tests/data/` (public): one crop of that image with channels 0–2, so the exon channel keeps index 2 (about 256–384 px square, cut down in Z if needed, about 10 MB), holding several whole nuclei, well over 30 isolated spots away from the edges and a dense region; a reviewed 2D nuclear label image for the crop (`_seglabels.tif`), drafted from the DAPI channel and corrected by the user; and its config. The crop's Z range is chosen so that nuclei stay separate in the DAPI projection.
  - Other cases (2D, other layouts, three or more channels, blank image, awkward file names) are generated inside the tests.
- Reference run: the v1 general and HCRv3 batch scripts run in the unchanged main env on the crop and on the full-size image, with top-hat background, manual and auto thresholds, subpixel fitting on and off, and no segmentation. Settings start from the config of the earlier analysis of this image series (manual threshold 18, cluster radius 600 nm, minimum spots 12). Per-cell reference counts for the crop come from big-fish `extract_cell` with the nuclear label image. Reference results for the crop are produced from the crop itself, not cut out of the full-image results, because cropping changes the background and the automatic threshold. Configs, commands and `conda env export` are stored with the outputs. Existing outputs from earlier lab runs can be added as a further reference.
- Benchmarks on the full-size image: time and memory of top-hat vs rolling ball at 5 px per channel and of the v1 steps; first estimate of memory per worker. Cellpose-SAM is measured in Phase 2 (brief: R8).

Done when: big-fish's tests pass in `bigfish-msp`; the reference outputs, test kit and benchmark numbers are recorded; and `pytest` runs in `bigfish-msp`.

### Phase 1: Package and unified pipeline

- Package modules (section 4.1) on the new stack, with both background methods: rolling ball (the file copied in with its ImageJ reference tests and fixture) and top-hat.
- Image input (local and OMERO), 2D and 3D, any number of channels, layout and voxel-size confirmation. OMERO session sharing between the main process and the workers, checked against the lab server (section 5.3).
- Config schema version 1 with validation; `bigfish-pypeline batch` and `check`.
- Threshold modes (manual, auto with lower limit, calibrated), bailout as a general option, decomposition with the seeded reference spot, subpixel fitting, clusters, measurements (SNR, intensity).
- Per-cell results from label files, with the new cell assignment. Cellpose follows in Phase 2.
- Batch runner (section 7): sorted image order, error handling per image and channel, cancel, restart after a worker stops, and the basic run folder (`run_config.yaml`, `run.log`, `progress.json`, per-image and combined tables), so that failures and finished images are recorded from the start.
- v1 bugs fixed here: manual thresholds limited to two channels, workers stopping silently on errors, config read from the current folder with the unsafe loader, unsorted image order, bailout without a log entry.

Done when, on the crop and the full-size image with top-hat and the reference settings:

- detected spots are identical to v1;
- decomposed spots and clusters are identical to v1 on images with up to 2,000 spots (above that, v1 picks the spots for its reference spot at random, so counts are compared and the difference is recorded);
- per-cell counts on the crop match `extract_cell` for cells not touching the border;
- a cancelled run and a run with a deliberately stopped worker leave combined tables for the finished images;
- any difference from v1 is explained in the devlog. If one appears, the v1 script is run in the new env to show whether it comes from the package versions or from the new code.

### Phase 2: Cellpose 4 and comparisons

- Cellpose 4: model, device selection, pre-treatment, eval settings, 4-panel QC, label saving (section 5.7); streamed segmentation in the batch runner, with the model loaded once (section 7.1). Checked by automated tests only: Cellpose-SAM does not suit the lab's brain images, so its masks are not judged on the test image (brief: R8).
- Comparisons, recorded in the devlog with figures:
  1. Rolling ball vs top-hat (spot counts, threshold values, examples).
  2. Cellpose 4 (`cpsam_v2`) masks on an image the user supplies later (e.g. cultured cells), judged by the user on whether they are good enough for per-cell results. Existing Cellpose 3 `cyto` masks can be shown alongside for context; matching them is not required. This comparison waits for that image and must be reviewed before Phase 8.
- Benchmarks: rolling ball on full stacks; time and memory of Cellpose-SAM on the Apple GPU and on CPU (masks not judged); memory per worker with every step switched on; the final `workers: auto` estimate and reserve.

Done when: the package tests pass and the rolling ball comparison is reviewed by the user.

### Phase 3: Outputs, logs and QC

- `run_info.yaml`, the full `run.log` contents (section 8.4) and the optional `.npz` files, added to the basic run folder from Phase 1.
- QC images with their switches (section 8.3), including the elbow plot with the threshold value, the calibration plot and the final QC (PNG and HTML).
- Keep-awake during runs.

Done when: a full run on the test kit produces every output; repeating the run from `run_config.yaml` gives the same tables (section 6.3); the user has reviewed sample QC images and the log.

### Phase 4: Optimise notebook

- `notebooks/bigfish-optimise.ipynb` (section 9), committed without outputs.

Done when: the notebook runs top to bottom on the test kit inside the test suite, and the config it saves runs unchanged through `bigfish-pypeline batch` with results identical to the notebook's own saved results for that image.

### Phase 5: Streamlit app

- Pages, look, folder picker, threshold helper, batch launching and monitoring, results browsing, launchers (section 10).
- Add Streamlit and `streamlit-image-coordinates` to the env.

Done when: smoke tests pass for every page; a config sent from Optimise to Batch gives results identical to the command line; cancel and reconnect after refresh work, and a run that has stopped is not shown as running; the user has walked through the app on a Mac.

### Phase 6: Documentation

- README and Quarto guide (section 14); screenshots with `playwright-cli` into `www/screenshots/`; site published on GitHub Pages.

Done when: every config setting is documented, the guide builds without errors, and the user has reviewed it.

### Phase 7: Windows and Linux testing

- Native Windows (app through the `.bat` launcher, command line, CUDA, OMERO), WSL2 Ubuntu with an NVIDIA GPU (including Windows paths under `/mnt/c/` and pasted `C:\…` paths), and Linux, all in the `bigfish-msp` env.
- Full test suite on each, plus one full-size batch on the lab workstation.
- Fixes made on the `msp` branch and re-tested on the affected systems.

Done when: the test suite passes on native Windows, WSL2 and Linux, and the user has reviewed the workstation batch.

### Phase 8: Main env, old folders and release

Only on the user's instruction, after Phase 7 and the Cellpose 4 mask review (Phase 2):

- Replace `environment.yml` with the new stack; update `AGENTS.md` (Cellpose 4 in the main env).
- Move `general/`, `HCRv3_spot-count/`, `tissue-culture_cells/`, `omero/` and `posthoc_analysis/` to `docs/archive/`; archive `general/further_analysis/*.qmd`.
- Merge `msp` into `main`; tag `v2.0`.

## 12. Testing

- **Unit tests (synthetic data):**
  - PSF values.
  - Top-hat against scikit-image; rolling ball against the ImageJ fixture.
  - Detection of Gaussian spots at known positions (all found within 1 px; none on a blank image).
  - Each threshold mode, lower limit and bailout; the calibration median with unreadable and blank images in the subset.
  - Decomposition, subpixel fitting and clusters on synthetic images, including images with no spots and with very few; the same reference spot from two runs with the same seed. big-fish's own tests do not cover these functions.
  - SNR and intensity on 2D and 3D synthetic spots.
  - Cell assignment on synthetic labels with adjacent cells, border cells and a cluster lying across a boundary (guards against the v1 notebook bug); rejection of invalid label files.
  - Config validation messages and YAML round trip.
  - File discovery (filter, extension, top level only, sorting, spaces and accents in names).
  - Image layouts (2D/3D, single or several channels).
  - Table columns and the `-1` conventions.
- **Regression tests:** the test kit against its v1 reference outputs (in the repo); the full-size image against the reference run (local, `BIGFISH_TEST_DATA`).
- **End-to-end tests:** `bigfish-pypeline batch` on the test kit and generated images, with and without segmentation (label file and Cellpose), including a failing image, a cancelled run and a deliberately stopped worker. Tests that need the Cellpose weights are marked so they can be skipped.
- **Notebook test:** the optimise notebook executed on the test kit.
- **App tests:** Streamlit `AppTest` smoke tests per page; config round trip Optimise → Batch.
- **Manual checks:** listed at the end of each phase in the devlog and signed off by the user.
- macOS only until Phase 7.

## 13. Edge cases

| Case | Expected behaviour | Tested in |
|---|---|---|
| Spaces, accents or other non-ASCII characters in paths and file names | Processed normally | unit, end-to-end |
| Windows paths pasted into the app (`C:\…`) or used in WSL2 (`/mnt/c/…`) | Accepted; converted under WSL2 | Phase 7 |
| Very long paths on Windows | Clear error if the path cannot be used | Phase 7 |
| Image with no spots | Zero spots, status done; decomposition and subpixel fitting skipped; elbow plot written when a threshold exists; lower limit applies | unit (generated blank image) |
| Single-plane (2D) image | 2D processing; no z columns | unit |
| Different image sizes in one batch | Each processed at its own size | end-to-end |
| Image layout differs from the config (e.g. missing channel) | Image fails with the reason | end-to-end |
| Channel index out of range | Stopped before processing when no image holds the channel; an image that lacks it among images that hold it fails with the reason | unit, end-to-end |
| Plane of `segmentation.z_planes` beyond an image's planes | As for a channel: stopped before processing when no image holds the plane; otherwise that image fails with the reason. With a 2D layout the settings check refuses the setting | unit, end-to-end |
| A file that cannot be used at the front of the list (other pixel type, colour, other axes, damaged) | That image fails with the reason and the run continues; the run stops before processing only when no image can be used | unit, end-to-end |
| Two inputs giving the same output name | Stopped before processing with the clashing names | unit |
| Calibration filter matches no image | Stopped before processing | unit |
| No usable automatic threshold in a calibration image | Left out of the median with the reason; run stopped if none is usable | unit |
| Bailout limit exceeded | That channel skipped with the reason; other channels kept | unit |
| Too few spots for a reference spot | Decomposition skipped with a warning; detected spots passed on | unit |
| Missing, mismatched or invalid label file | Cell-level results skipped with a warning; `cell_id = -1` | unit, end-to-end |
| Cellpose finds no cells | Warning; empty cell table; `cell_id = -1` | unit |
| Cluster lying across a cell boundary | Spots counted in their own cells; cluster counted where its centre lies | unit |
| Corrupt or unreadable file | Image fails with the reason; run continues | end-to-end |
| Input stored as 8-bit, 12-bit or 16-bit | Processed; 12-bit read as 16-bit | unit, end-to-end |
| Input of another pixel type (32-bit float, signed, 32-bit) | Refused by `check`; in a run the image fails with the type found and how to convert it, and the run continues | unit, end-to-end |
| File whose own axes differ from the confirmed layout (e.g. stored `ZCYX` or `YXC`, layout `CZYX`) | Image fails with a message naming both; run continues | unit, end-to-end |
| Voxel sizes missing from metadata | Must be entered; never assumed | unit, app |
| Metadata voxel sizes differ from the config | Config values used; warning logged | unit |
| Metadata X and Y pixel sizes differ | Shown; the user enters the value to use | unit, app |
| File with several time points or positions | Rejected with a message | unit |
| Very large image or out of memory | Workers limited by memory, based on the largest image; after a worker stops unexpectedly the run restarts with fewer workers and retries the images in progress once | end-to-end, Phase 0 and 2 benchmarks |
| No GPU | CPU used, warning about time | unit |
| OMERO connection drops | One retry, then the image fails | manual (lab network) |
| OMERO session ended | No new images start; finished images combined; message to log in again. Only when the server refuses the session key or says the session was removed or timed out: any other failure to rejoin (no answer, a timeout, the session service not available) is handled as a dropped connection | unit (stand-in), manual (lab network) |
| Output folder not writable | Stopped before processing | unit |
| Input folder already contains `bigfish_results/` | Ignored (top level only) | unit |
| Run cancelled or computer sleeps | Workers stopped at once; images in progress discarded; finished images kept and combined; run marked cancelled; keep-awake on by default | end-to-end |
| Two runs with the same name started in the same minute | The second run folder gets a number | unit |
| `tkinter` missing | Text box instead of the folder dialog | app |
| Browser refreshed during a batch | Batch page reconnects to the running batch | app |
| Batch stopped without the app knowing | Shown as stopped, not running | app |

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
| big-fish behaves differently under numpy 2, scipy 1.18 or scikit-image 0.26 | big-fish's own tests in the fork (these do not cover detection, decomposition, fitting or clusters); the pipeline's synthetic-image tests; Phase 1 comparison with the v1 reference |
| Code restructuring and package upgrades happen together, so the cause of a changed result is not obvious | If Phase 1 differs from v1, the v1 script is run in the new env to separate the two causes |
| scikit-image removes `square`/`rectangle` used by big-fish | scikit-image pinned below 0.27; patch in the fork if needed |
| Rolling ball at 5 px too slow for 100–200 images | Phase 0 benchmark; top-hat option |
| Cellpose-SAM slow without a GPU | Device warning; guide recommends a GPU machine for large batches |
| Cellpose 4 masks not good enough on lab images | Review by the user on a suitable image before Phase 8; label-file input as a fallback |
| Memory per worker higher than expected | Worker estimate from measurements, with a reserve; restart with fewer workers |
| Native Windows untested until Phase 7; OMERO untested on Windows by its developers | Cross-platform coding rules from the start; Phase 7 testing before release |
| Library updates break the env, or a listed version has no build for one system | Exact versions pinned and recorded for each system |
| Streamlit API changes | Streamlit version pinned |
| `tkinter` behaviour differs between systems | Text-box fallback |

## 16. Later (to-do)

- Nucleus segmentation alongside cytoplasm (README to-do); the test image's DAPI channel can be used for this.
- 3D segmentation and multi-channel Cellpose input.
- Other image formats (e.g. through `bioio`).
- Resuming interrupted runs.
- Uploading results to OMERO.
- Repo clean-up (brief: C4): commit notebooks without outputs, `.gitignore` entries for outputs, remove personal paths from example configs, fix the two GitHub owners in the README.
