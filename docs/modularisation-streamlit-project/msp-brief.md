## Modularisation-streamlit-project (MSP) Project overview

I want to make big structural changes to the bigfish-pypeline, without affecting the core functionality. 
The changes includes:
 - Updating packages and some module scripts. 
 - Modularisation of individual analysis components.
 - Improve connectivity of optimise block with the batch block.
 - Create a sleek streamlit GUI front end for optimise and batch block separately with handover functionality from optimise block to batch block. 
 - Improve user instruction with proper documentation and screenshots. 

## Rationale 

The bigfish-pypeline is our lab's flagship image analysis pipeline for RNA-FISH (e.g. smFISH/HCR/RNAScope...). The pipeline works well, but it's fragmented, outdated, redundant in places, fiddly when switching from optimise block to batch block, outputs are not easy for people to interpret, and overall not so generally accessible to biologists with little coding experience. The MSP project (modularisation-streamlit-project), therefore aims to address these as a sub-project within the repo. 

## Project specifics

### Updating packaged and module scripts. 

All updates to the conda env should be compatible with multiple OS (macos - including ARM, windows, linux), and must make sure the updated packages are compatible with existing scripts/functions, otherwise the script should be updated. 

#### Cellpose

- Update the old cellpose version to the latest cellpose 4 (cellpose-sam) in the repo and update the corresponding cellpose argument blocks. 
- cellpose-SAM should be able to make use of Apple M processor MPS or CUDA GPU if available. 
- See the existing implementation in the scripts/jupyter notebooks as well as my new implemtation with the cellpose-SAM here (https://github.com/JeffLeeLab/Image-analysis/blob/main/Segmentation/Cellpose-SAM-AppleM1/cellpose-sam-workbook.ipynb).
- The MSP project should update most if not all of the new EVAL_SETTINGS in the workbook above.
- The MSP project should update pre-treatment (median, gaussian, background-subtraction) similar to the workbook, but the background subtraction should use the python implemented version of the imagej-rolling-ball in my repo (https://github.com/JeffLeeLab/Image-analysis/tree/main/misc/python-rolling-ball).
- If the cellpose segmentation module is turned on, the batch mode should also output cellpose QC image like the one in th `qc_figure` of the workbook.
- Depending on the user-option, the cellpose label image should also be outputed. 
- Cellpose module should be updated to take also pre-segmented label images from cellpose as well as other sources that can be seamlessly integrated into the pipeline.  

#### Background substraction script

- There are a few places where background is subtracted in the pipeline (cellpose segmentation, RNA FISH image segmentation), which uses scikit-image disc. This should be updated to more faithful python port of imagej rolling ball (https://github.com/JeffLeeLab/Image-analysis/tree/main/misc/python-rolling-ball). 

#### general update to python version itself, scipy, scikit-image, numpy, pandas, matplotlib

- I want to update the python to the latest possible without breaking the bigfish package functionality.
- I also want to update rest of the scientific python packages (scipy, scikit-image, numpy, pandas, matplotlib), without breaking the pipeline.

### Modularisation and update of individual analysis components. 

- Currently the pipelines are split into "HCRv3..", "general", "omero", "tissue-culture..." versions, which are almost essentially the same pipeline with different modules turn on or different input image methods. So I want to combine them into a single one, and the user will choose how they want to analyse the image. The user should be guided on what they should turn on and off based on their image type and analysis needs. Below is a general workflow in order, someone of the are essential and others are optional. 

#### 1. Import image.

- Requires image input either as directory or omero id. 
- Either allow importing image from OMERO or from local/harddrive. OMERO import is mainly for people in our lab in University of Glasgow under internal network. 
- AFAIK, omero import only works on macos and linux. 
- Batch mode later on omero should be dealt with dataset id, rather than image ID. 
- For local image, I'm not sure if defining folder than giving index of the images in that folder or specifying one image would be better. 
- It'd be good at this point to show the datatype and max projection (MIP) images of each channel (auto-contrasted) as in the cellpose workbook above. 

#### 2. Image preparation. 

- Requires RNA FISH channel to analyse and image pixel, PSF parameters. 

#### 3. Image pre-filtering. 

- Requires filtering parameters.
- (1) Background subtraction of the channel of interest (5px as default). 
- (2) LoG filtering of the background subtracted image --> output is called `rna_log`. (parameter is not user-definable).
- `rna_log.tif` (MIP) is often saved and opened in imagej to find manual threshold value. If there's a way to draw a line profile in jupyter notebook/lab or streamlit, it would be very helpful to not having to open external imagej. 

#### 4. Single-spot detection (pre-detection in BigFISH documentation).

- Requires thresholding mode, and threshold values. 
- Spots are detected based on intensity either manually or automatically. 
- Manual: users often use their typical values from experience or imagej line profile to get appropriate values from rna_log.
    - Not an issue for optimisation mode, but currently, the pipeline only supports 2 FISH channels. This is too limiting as more users have more than 5 FISH channels, so the configuration file for batch mode should be expandable with FISH channel name (0-based) and each channels' manual threshold values. 
- Automated: Uses bigfish elbow plot. In batch mode, the elbow plot is exported as QC, however, the current elbow plot does not include the actual threshold value, so it would be helpful to state the value in the plot where the "Selected threshold" legend is to something like "Selected treshold = 11.0". 
- For batch mode, it would be useful to output a log (more on this below) that logs each individual images' selected threshold values. 
- Would it also be possible to have a hybrid mode, where this auto elbow plot is run across a subset of user-defined (string match?) images and the median/mean (which?) of the auto value is used as manual input for the batch processing? Is this a good idea? Its often useful when in a biological condition when there are no spots (expected), then the auto-mode does not have to force-fit an elbow plot and find a ridiculously low threshold. 

- Results create spot array (Z,Y,X).
- For HCR/HCRv3 (where spots are not PSF-approximatable) and other amplification-based FISH, this is where the analysis stops. User may want to simply get the coordinates (and SNR?) of the images at this point for the entire field-of-view (FOV) or also combine the cell segmentation module. 

#### 5. Quantify dense regions.

- Optional (for HCR) but almost always run with smFISH images. 
- Requires decomposition bigfish parameters, but most often just default bigfish values. 
- Builds reference spot profile (QC outputted), and uses it to decompose dense foci. 
- creates a new decomposed spot array (Z, Y, X). 


#### 6. Subpixel fitting. 

- Optional, can be quite slow, but useful for co-localisation analysis since this modules provides more precise RNA localisation. 


#### 7. Cluster decomposed spots. 

- Optional, but almost always run with smFISH images.
- This runs together with step 5 quantify dense regions. 
- Requires cluster radius and nb_min_spots parameters.
- The highlight of bigfish that allows quantification of RNA transcription site, virus factories, RNA granules etc. 
- The input should take decomposed spots with or without subpixel fitting optional module. A user might also want to run clustering without the decomposition altogether for a novel analysis, so it should simply be able to take spot array as input. 
- creates a cluster array with cluster position and rna content count. I believe it also creates a new spot array with a column saying whether it belongs to a particular cluster index or not.

- This is often the final output if users are not combining their analysis with the segmentation module. It has traditioanlly been outputted as listed npz file, but users have been complaining npz files are not accessible and prefer csv for other commonly used file formats. 
- So the output csvs may have to be two separate outpus in this case? 
    - One that is spot-centric, and the other cluster centric? What do you think is a good output format? 

#### 8. Cellpose segmentation.

- Optional.
- Requires cellpose model and input parameters. 
- Should also be able to take input of pre-segmented label images (from other workflows, existing cellpose runs, or manually segmented). 
- output QC should now include cellpose (the four panel image with parameters, see above workbook example). 

#### 9. Extracting cell-level results. 

- Optional but should be turned on if segmentation module is turned on. 
- Requires cellpose label image. 
- This has traditionally been a separate workflow that takes step 7 output npz and cellpose output to get cell-level results, but it will be beneficial to include it together. 
- This currently uses bigfish fov_results suite of function - not sure if this is the best. 
- The aim is to essentially distribute spots and clusters to individual cells, but the current batch mode users' feedback has been that it's been difficult to match back their output to the actual images. 
- So it might be good to have a QC output similar to the individual cell-cropped images that bigfish plot_cell produces but combine them in to a single image as PNG in the original image, showing at the centre (or somewhere?) of each cell of the coordinate representation cell index, spot count, cluster count, cluster content, cell outline.
- For the MSP project, focus on cytoplasm single segmentation, but put it in the To-Do in readme about incorporation of nucleus segmentation as well as cytoplasm. 
- I think the output with cell-level results module turned on should be similar to the step 7 output, but now they have a column which cell index the spot or cluster belong to or not belong to (outside cell area). What do you think is there a better output format? It's difficult to have a single output that contains xyz coordinates of both spots and clusters without making it look cluttered. 
- there should be option to include or exclude cells outline segmentations touching the border of the images. I think bigfish handles this already. 


### Improve connectivity of optimise block with the batch block.

- At the end of MSP project, I expect two usage streams for the bigfish-pypeline:
    1. using jupyter notebook optimise (for optimising analysis parameters or for small number of images) --> port configuration file --> use batch mode via CLI pointing to the configuration file. 
    2. using streamlit local web app, which has optimise tab --> fills in configuration parameters at the end or in the persistant sidebar --> exported or automatically ported to the batch mode tab that a user can run the batch mode within the app interface and monitor the progress of the run etc. 
- Typically, the user should use optimise mode in either jupyterlab or optimise tab streamlit gui only to set up the correct parameters for analysis, and use batch mode for full analysis. But do allow optimise mode/tab to save outputs as some users just use it to analyse a few images per channel basis. 
- I want to make the optimise notebook/tab to also function as creating a configuration file, which is currently detached from optimise-to-batch workflow. Users have given feedback it's cluttering having to optimise then to configure again for batch mode. 
    - I want to unify the arguments between optimise and configuration so it makes sense to users what it does. 
    - I want to make it and build it intuitively that as user goes through optimise notebook/tab the configuration is built.
    - Obviously, there are a few batch config that is not directly pull-able from optimise notebook/tab, such as directory input, text string for input image search, number of cpus. How should we handle these? 
    - The point is to make it as streamlined as possible to handoff from optimise to batch modes. 
    - The config should also behave as a truth file of dates and run conditions, and it should be importable from batch runs or to batch tab in steamlit.
- Regarding outputs:
    - The current pipeline does not give any logs (which config file was used, the run date, skipping problematic images, images with errors, general summary), so a log file output would be helpful. 
    - Currently I make the user define output directories (for npz and qc for example), but would it make sense to just have the output default to where the images are stored, unless explicitly defined by the user? This would entail the pipeline forcing the flat image directory input without recursive search, so a second run doesn't find images in the output dir of the first run. 
    - and yes the point is that the user may run several runs on the same input directory with different config, so it needs to be properly distinctive (different output directory based on timestamp?) and reproducibly identifiable. 
- I'm also open for ideas on complete re-organisation of the repo/code structure or pipeline format to improve user experience and maintenance. 

### Create a sleek streamlit GUI front end for optimise and batch block separately with handover functionality from optimise block to batch block. 

- Some users are not a fan of jupyterlab having many code blocks (confusing for them), changing parameters as changing the python variables, and simply finding going back and forth in the optimise block very cumbersome. So a streamlit web app would be welcomed.
- The design should follow my other streamlit app for continuity (https://github.com/JeffLeeLab/smFISHProbeDesign/tree/master/streamlit_app).
- I am currently envisioning the left sidepanel acting as each configuration parameter that gets filled up or editable as the user goes through the optimisation step (with default values pre-populated). 
- A user would be happy to install the env using conda, so no worry about this. 
- The streamlit app should primarily be GUI with buttons that allows user to explore their image in all of the steps above, whilst allowing iteration to optimise the right analysis parameters. This would be the first top navigation tab. 
    - It would be even better if there's a way to easily to a line profile style to set their manual threshold. 
- Then there would be the second batch mode tab that handsoff the config from optimise tab and allows the user to run batch mode directly in this tab, while being able to monitor the progress and error messages, quick summary/logs as it builds.
- This would be useful particularly with setting and opening file explorere or directory selectors which they would be familiar with rather than the full path. Also some users have weird path names with spaces and so on, so the pypeline should be able to handle edge cases. 
- I'm still in the brainstorming stage of the streamlit app, so I'm open to new ideas and suggestions. 


### Improve user instruction with proper documentation and screenshots. 

- Need a sigle collated readme as well as a html/md/pdf version of the user instruction, explaining the background, reference (links, papers, github repos, theories), step-by-step usage instruction, description of what each arguments do and how to set them, troubleshooting, where to start if a user's starting with smFISH/HCR etc. 


## Development rules

- Since we are updating some packages, create a dev-only conda env for the msp project. Do NOT modify the existing bigfish-pypeline conda env until I tell you to do so. 
- Repo exploration and web fetch and research should be performed with haiku subagents. Simple documentation updates should be performed with sonnet subagents. 
- My development choices and rationale should be documented. Not in the persistant memory or AGENTS/CLAUDE.md as these take up unncessary context. Ideally, all development related documentations should be saved under `docs/modularisation-streamlit-project` folder and `msp-` prefix to avoid ambiguity with future projects (e.g. msp-plan.md, msp-spec.md ...).
- Based on this brief, a comprehensive spec document should be created that specifies development phases, tests, edge-cases, documentation plans etc. 
- You must ask me for clarification if anything's not clear and not make assumptions yourself. 
- Try to maintain the existing object names and general style of code writing, so I can read/understand and maintain the pipeline. 
- Can the multiprocessing be upgraded somehow with latest options? I'm not an expert on this. 

## Pre-spec review (26 Oct 2026)

Findings from exploring the repo and external resources, followed by the decisions still needed before `msp-spec.md` can be written. Answers can go directly under each "Decision:" line.

### Findings that shape the spec

**Packages**

- big-fish is no longer maintained: last release 0.6.2 (April 2022), last commit October 2023, fix PRs left unmerged. The modules the pipeline uses (`stack`, `detection`, `plot`, `multistack`) mostly cope with newer scikit-image thanks to version checks, but:
  - `bigfish.segmentation` imports the removed `skimage.morphology.selem` (the notebooks import this module);
  - `detection.compute_snr_spots` uses `np.int` (removed in numpy 1.24);
  - it relies on the private `sklearn.utils.fixes.parse_version`;
  - behaviour under numpy 2 and pandas 3 is untested.
- Python version limits: omero-py ≥5.22 needs numpy ≥2 and Python ≥3.10 (the current 5.21 needs numpy <2); Streamlit 1.66 needs Python ≥3.11; numpy 2.5, scipy 1.18 and current tifffile need ≥3.12; Cellpose recommends 3.12. zeroc-ice 3.6.5 has conda-forge builds for Python 3.10–3.13 on macOS (ARM and Intel), Linux and Windows, so OMERO on Windows is not blocked by packaging (but untested in use).
- Cellpose 4: `models.Cellpose` is gone (only `CellposeModel`); `channels` is ignored in favour of `channel_axis`; `eval` returns 3 values; default model is `cpsam_v2`; default diameter is `None`. Model weights are ~1.2 GB, downloaded on first use. conda-forge only has 4.1.1 (4.2.1.1 is pip-only). PyPI torch has no Intel-Mac builds (conda-forge does). On Apple GPUs, 3D mask post-processing falls back to CPU.
- Cellpose-SAM workbook: GPU selection is Apple-only (no CUDA or CPU fallback); pre-treatment is median and Gaussian only, no background subtraction; `qc_figure` reads notebook-wide variables rather than taking arguments; several markdown defaults disagree with the code (`cpsam` vs `cpsam_v2`, diameter 400 vs None, Z projection mean vs max); label files are named `_nucllabel` (nuclei).
- python-rolling-ball: numpy + scipy only, a single file, processes each 2D plane separately, matches ImageJ 1.54p. The repo has no licence file. For radii ≤10 px ImageJ skips its shrink step, so it is slow: ~5 s per 2048×2048 plane at radius 10 (README figure, M1 Pro). Speed at the 5 px FISH default on full Z-stacks is unknown.

**Current pipeline**

- FISH background subtraction is a white top-hat with a 5 px disk on each Z-plane (`src/bigfish_pypeline/image_utils.py`). Cellpose input has no background subtraction (MIP → optional clip → median filter).
- Five optimise notebooks and five batch scripts share most of their code. Notebooks copy helper functions instead of importing `src/bigfish_pypeline`; scripts reach it by editing `sys.path`; nothing is installable (no `pyproject.toml`); there are no tests.
- Notebook defaults differ from batch configs (cluster radius 400 vs 600 nm, `nb_min_spots` 5 vs 12, manual threshold 8 vs 50/30, `cellprob_threshold` −6 vs 0, clip value 10 vs 120, segmentation channel 0 vs 1). This is the optimise → batch handover problem in concrete form.
- Bugs that affect results or runs:
  - Cell-level notebooks (general, HCRv3): `in_mask` is not reset when a spot falls in a *different* cell, so a neighbouring cell's spot can be counted in the current cell. Past per-cell counts from these notebooks may be inflated.
  - Manual thresholds only work for two hard-coded channel keys; any other channel crashes.
  - A failing image stops its worker without any record; if all workers stop, the rest of the batch is skipped without notice.
  - General and OMERO notebooks pass `mask_threshold` to Cellpose, which 3.1.1.2 does not accept.
  - The tissue batch script reloads the Cellpose model for every image; the HCR "bailout" skips outputs without logging.
  - Configs are read from the current folder with the unsafe YAML loader; image order is not sorted.
- Repo: ~96 MB of notebooks with embedded outputs and ~330 MB of tracked files in total (TIFFs, PNG/CSV outputs); committed configs contain personal paths (including another user's Windows path); `AGENTS.md` points to `test/streamlit/...` (now archived) and `www/screenshots` (does not exist yet); the README links two different GitHub owners.

**Reusable material**

- Archived server-side Streamlit app: `bigfish_processing.py` (one function per step, 6 tests), `config_export.py` (YAML export, 4 tests), an OMERO metadata reader (voxel sizes in nm), a Plotly LoG view with hover values plus a histogram with the threshold marked, and a per-session step cache. Its review notes warn against silent default voxel sizes and `sys.path` imports. Its import paths broke when it was archived.
- smFISHProbeDesign app: the look comes entirely from `.streamlit/config.toml` (warm palette, Styrene B font served from `static/`), hidden `st.navigation` with a top button bar, parameters in the sidebar with expanders for advanced options, no custom CSS, no parameter export. The bundled Styrene B files are trial licences.
- Streamlit limits: no built-in way to draw a line on an image; folder selection needs a native dialog opened by a helper process (possible only because the app runs locally); long batch runs should be a separate process that the app watches, not multiprocessing inside Streamlit.

### Decisions needed

Items marked ★ shape the architecture and are best settled first.

#### A. Scope and validation

**A1 ★ What "core functionality unchanged" means.** Rolling ball, Cellpose 4 and the bug fixes will all change numbers. Suggestion: before any change, run the current pipeline on a fixed test set in the current env and keep those outputs as the reference. Each later phase either reproduces them (within a stated tolerance) or documents why it differs, with before/after figures.

Decision: Bug fixes and updated cellpose and rolling ball is fine to give different results. I do have some outputs from previous runs that I can possibly use as reference. I meant "core functionality" as in core bigfish scripts. 

**A2 ★ Test images.** Which images make up the test set, and where are they stored (git, OMERO, Zenodo, lab drive)? Suggested minimum: smFISH in cultured cells (with segmentation), smFISH in tissue, HCR, a negative control with no expected spots, an image with ≥3 FISH channels, and a file name with spaces. Cropped to keep them small.

Decision: I'll prepare some test images that will be saved locally in my laptop. I'll provide some and you can make test kits form them.

**A3 ★ Phase order.** Suggestion: (0) reference run, dev env, test set-up → (1) installable package + unified pipeline + config + command-line batch, still using the current algorithms → (2) package upgrades (Python, big-fish patch, rolling ball, Cellpose 4) → (3) new outputs, logs, QC → (4) optimise notebook → (5) Streamlit app → (6) documentation and screenshots → (7) swap main env and retire old folders. Restructuring before upgrading means any change in results can be traced to a single step.

Decision: I'm onboard with the suggested phase order. Then I should first curate images for reference run first. 

**A4 Where it runs.** Laptops only, or also lab workstations with NVIDIA GPUs (Windows or Linux), or an HPC cluster? Typical batch size (number of images) and image size (Z-planes, channels)? This sets performance targets and whether the batch must run without a screen.

Decision: Laptops and lap workstations. Typical batch size is 100-200 images, with 2048x2048x30 (x:y:z) images. 

**A5 Results from the buggy cell-level notebooks.** Re-check, or tell past users? Outside MSP scope, but the spec could include a small script that re-runs cell assignment on old outputs.

Decision: does the buggy cell-level notebook affect also the batch mode scripts? What exactly was wrong? 

#### B. Packages and environment

**B1 ★ big-fish.** Options: (a) copy a patched big-fish into this repo (its BSD-3 licence allows this, keeping the licence and credit); (b) a JeffLeeLab fork on GitHub, installed with pip from git; (c) stay on an older stack (Python 3.11, numpy <2), which rules out current omero-py and newer scientific packages. Suggestion: (b), patching only what the pipeline uses, with tests.

Decision: I think selem is not used in my pipelinel, so perhaps only the np.int is the issue? I think (b) is probably the way to go. What do I need to do? 

**B2 Python version.** Suggestion: 3.12 (satisfies every package; recommended by Cellpose). 3.13 is possible but less tested.

Decision: 3.12 is fine. 

**B3 Cellpose/torch install.** pip `cellpose==4.2.1.1` inside the conda env, or conda-forge 4.1.1? Does anyone in the lab use an Intel Mac (needs conda-forge torch) or Windows/Linux with an NVIDIA GPU (needs the CUDA build of torch)? One env file for everyone, or a separate GPU env file?

Decision: conda-forge 4.1.1. Our lab workstation has windows (ubuntu wsl2) with an NVIDIA GPU, it's been working with the older version of cellpose. 

**B4 Cellpose model and weights.** Default `cpsam` or `cpsam_v2`? The first run downloads ~1.2 GB: acceptable, or document a download step during installation? Cellpose-SAM masks need checking against current `cyto` results on lab images.

Decision: Default cpsam_v2. first run download is acceptable. 

**B5 ★ Rolling ball.** (i) Add a licence to python-rolling-ball before copying it in. (ii) Copy the single file into the package, as its README suggests? (iii) If it is too slow at 5 px on full stacks: process planes in parallel, or keep the current top-hat as a choice. Suggestion: `bg_method: rolling_ball | tophat`, rolling ball as default for new configs, top-hat kept to reproduce old results. Users' familiar manual threshold values will shift with the new method.

Decision: (i) do not need licensing, it's my repo. (ii) copy the single file into the package. (iii) give user the option to use rolling-ball or the current top-hat. Dropdown menu in the streamlit app. 

**B6 Image formats.** Currently TIFF only, assumed ZCYX, with no checks. Add .nd2/.czi/.lif/OME-TIFF through `bioio` and its plugins, or stay TIFF-only and document conversion in Fiji? Read voxel sizes from file metadata where present (shown for the user to confirm, never assumed silently)? User states the axis order (e.g. `ZCYX`), as in the workbook?

Decision: Stay TIFF-only and document conversion in Fiji. Read voxel sizes from file metadata where present (shown for the user to confirm, never assumed silently). The notebook/app should show the image dimension and the user should confirm. 

**B7 Dev env.** Name and file location, e.g. `bigfish-msp` from `docs/modularisation-streamlit-project/msp-environment.yml`? Update the out-of-date lines in `AGENTS.md` now or at the end?

Decision: your suggestion is fine. Update the AGENTS.md now too. 

#### C. Repository layout and versions

**C1 ★ Layout.** Suggestion:

```
src/bigfish_pypeline/   installable package (pyproject.toml, pip install -e .)
    io (local + OMERO), config, background, detection, decomposition,
    subpixel, clusters, segmentation, cells, outputs, qc, batch, cli
app/                    Streamlit app
notebooks/              one optimise notebook
docs/                   user guide (+ www/screenshots)
tests/
```

Users get one command, e.g. `bigfish-pypeline batch config.yaml` and `bigfish-pypeline app`.

Decision: your suggestion is fine. 

**C2 Old folders.** Once replaced, move `general/`, `HCRv3_spot-count/`, `tissue-culture_cells/` and `omero/` to `docs/archive/`, or remove them from `main` and keep them on a tagged release (e.g. `v1-legacy`)? What happens to `posthoc_analysis/snr` (fold per-spot SNR into the pipeline as an option?) and `further_analysis/*.qmd` (update to the new CSVs, or archive)?

Decision: move them to an archive folder under docs? for snr, yes fold per-spot snr into the pipeline as an option. Archive the further_analysis qmd. 

**C3 Versions and branch.** Tag the current state (`v1.0`) before starting; MSP becomes `v2.0`; the pipeline version is written into every output. Work on an `msp` branch, merging once per phase?

Decision: yes sounds good. 

**C4 Repo clean-up.** New notebooks committed without outputs; `.gitignore` entries for outputs; personal paths removed from example configs. Leave git history as it is (rewriting it to drop the ~330 MB would break existing copies)?

Decision: Let's do repo clean-up later, keep it in the to-do for now. 

#### D. Pipeline modules

**D1 ★ Image dimensions.** Always 3D Z-stacks, or must single 2D planes work too (big-fish supports both; current code assumes 3D)? Any multi-position or time-lapse files?

Decision: Both 2D and 3D. no multi-position or time-lapse. 

**D2 Local input.** Suggestion: choose a folder and a file-name filter (text match plus extension); show the list of matching files; optimise picks one from the list; batch uses the whole list, top level only (no subfolders), sorted by name.

Decision: sounds good. 

**D3 OMERO.** Optimise by image ID, batch by dataset ID: also by project or a list of image IDs? Passwords asked each time, never saved. Is the internal server address fine in a public repo, or should it sit in a local settings file? Outputs need a local folder: any wish to upload results back to OMERO (attachments or ROIs)? Keep a local copy of downloaded images for repeat runs?

Decision: optimise by image ID, batch by dataset ID or list of image IDs. Internal server address is fine on public repo. Outputs should be saved to a local folder. Do not keep a local copy of downloaded images. 

**D4 ★ Per-channel settings.** The PSF depends on emission wavelength, so `ex`/`em` belong to each channel, not the whole image. Suggestion: a `microscope` block (voxel sizes, NA, RI, microscope type) plus a `channels` list, each entry with index, name (e.g. "Ago1-Q570"), ex/em, threshold settings, and optional overrides for background radius, decomposition and cluster settings.

Decision: Although I find ex/em settings do not change much, your suggestion is fine.

**D5 ★ Threshold modes.** Suggestion: `manual` (value per channel); `auto` (elbow, per image); `calibrated` (the hybrid): run auto on a subset chosen by file-name match, then apply one fixed value to the whole batch. Use the median, not the mean, so one failed elbow on an empty image cannot drag the value down. Show the per-image auto values as a table and plot so the spread is visible. Should `auto` also accept a lower limit? Keep, replace or drop the HCR "bailout" (skip an image if the spot count exceeds a limit)?

Decision: Your suggestion is fine. Auto should also accept a lower limit. Keep the HCR bailout and make it a general config option. 

**D6 Step order and presets.** Unified order: detect → (decompose) → (subpixel) → (cluster) → (segment or load labels) → (assign to cells). Subpixel fitting and clustering take whatever spots exist at that point. Should presets set the module switches, e.g. "smFISH – cells", "smFISH – tissue", "HCR – spot count", "HCR – per cell"? Which ones?

Decision: Let's discuss more about this. 

**D7 Reference spot.** Keep building one per image per channel (current behaviour), or allow the one from the optimise image to be reused for the whole batch? Save it as PNG instead of TIFF?

Decision: keep building on per image per channel. 

**D8 Extra spot measurements.** Add optional per-spot SNR (from `posthoc_analysis/snr`) and intensity columns?

Decision: yes. 

**D9 ★ Segmentation target and input.** The brief says cytoplasm; the workbook segments nuclei. Which channel(s) go into Cellpose (Cellpose-SAM takes up to 3, e.g. cytoplasm + nucleus)? 2D on a Z projection only (max or mean)? Pre-treatment: median, Gaussian and rolling ball (the workbook has no background subtraction)? Keep the old "clip intensity" option?

Decision: For now, keep only one channel input, user-selectable max or mean. 2D only for now. Pre-treament should include background subtraction and keep clip-intensity. 

**D10 Pre-segmented labels.** How are label files matched to images (same file stem plus a suffix, e.g. `<image>_labels.tif`, in a chosen folder)? Accepted inputs: 2D label images (TIFF/PNG); binary masks split into separate objects; 3D labels? If a label file is missing: skip cell-level results for that image with a warning?

Decision: 2D labels only for now. file names matched to images. `<image>_cplabels.tif`. If a label file is missing, skip cell-level results for that image with a warning. 

**D11 Cell assignment.** Suggestion: replace big-fish `extract_cell` with a direct look-up of each spot's and cluster's (y, x) position in the label image. This is simpler and faster, and removes the `in_mask` bug. Always add a `touches_border` column, with an option to drop those cells. Minimum cell area filter? Clusters assigned by their centre.

Decision: I like your suggestions, do not add minimum cell area filter. 

#### E. Outputs

**E1 ★ Output tables.** Suggestion: linked CSV tables, one row per object, joined by `image`, `channel` and ID columns:

- `spots.csv`: image, channel, spot_id, z, y, x (+ subpixel coordinates if on), cluster_id (empty if none), cell_id (0 = outside cells), optional SNR/intensity
- `clusters.csv`: image, channel, cluster_id, z, y, x, n_spots, cell_id
- `cells.csv` (with segmentation): image, channel, cell_id, area, centroid, touches_border, n_spots, n_spots_in_clusters, n_spots_outside_clusters, n_clusters, mean spots per cluster
- `images.csv`: one row per image per channel: status, threshold mode and value, counts, run time, error message

This gives both a spot-centred and a cluster-centred view without cluttering either. Coordinates in pixels, nm, or both? Drop `.npz`, or keep it as an option for old downstream scripts?

Decision: These are mostly fine. cell_id index should match that of cellpose. Let's do cell_id = -1 for spots/clusters outside cells. 

**E2 Per-image or combined files.** Suggestion: write per-image files as each image finishes (nothing lost if a run stops), then combine them into one table per type at the end.

Decision: yes sounds good. 

**E3 QC images.** Per image per channel: elbow plot (with "Selected threshold = 11.0"), detection overlay, reference spot, Cellpose 4-panel QC, cell map. A switch for each? On a 2048×2048 cell map with ~100 cells, writing the index and three counts on every cell gets crowded: show only the cell index (counts in `cells.csv`), show everything, or add an interactive HTML version with hover?

Decision: A switch for each sounds great. Note that detection overlay is separate from final qc (detection + cell outline + index + count QC image). A toggle for the final qc to be interactive HTML or png also sounds good. 

**E4 Label image output.** Save Cellpose labels as `<image>_labels.tif` (uint32) when switched on, using the same name pattern as pre-segmented input so a later run can reuse them?

Decision: yes but `<image>_cplabels.tif`

#### F. Optimise → batch handover

**F1 ★ One config format.** One YAML file shared by the notebook, the app and the command line, with the same parameter names everywhere, a `config_version` field, and checks that give plain-English error messages (e.g. using `pydantic`). Must configs from the four current variants load automatically, or is a one-off conversion guide enough?

Decision: Not sure what you mean here. 

**F2 Batch-only settings.** Input folder, file filter, number of workers, output folder. Notebook: a final cell with defaults (input folder = folder of the optimised image; workers chosen from CPU count and memory). App: fields on the Batch tab. Command line: values in the file can be overridden.

Decision: sounds good 

**F3 Run record.** Every run writes the fully filled-in config (all defaults included) plus run details (date, time, pipeline version, package versions, OS, CPU/GPU used) into its output folder. Passing that file back to the command line or Batch tab repeats the run.

Decision: sounds good 

**F4 ★ Output location.** Suggestion: default `<input folder>/bigfish_results/<YYYY-MM-DD_HHMM>_<run name>/`, changeable. Because input search is top-level only, result files are never picked up as input. OMERO runs and read-only drives must choose a folder. Saving results from optimise uses the same layout.

Decision: sounds good

**F5 Log and restart.** `run.log` in plain language: config used, each image started/finished/skipped/failed with the reason, threshold per image and channel, summary. Should an interrupted run be able to continue (skipping images already done)? Should there be a "re-run failed images only" option?

Decision: No keep it simple, re-run from scratch to a new output folder. 

#### G. Parallel processing

**G1 ★ Design.** Suggestion: (1) segment all images first, on the GPU, one at a time in the main process (model loaded once), saving label images; (2) run spot detection on the CPU in a pool of worker processes (`concurrent.futures`, "spawn" start method, one image per task, errors caught and logged per image, threads per worker capped so workers do not compete). The number of workers is limited by memory as well as CPU cores.

Decision: splitting segmentation and detection could be a failpoint when re-run from interrruption is diabled. Let's discuss more about it. 

#### H. Streamlit app

**H1 ★ Pages.** The brief has two tabs (Optimise, Batch). Add a Results page to browse a finished run's QC images and tables (to help match outputs back to images)? A Help page linking to the guide?

Decision: yes to all. 

**H2 ★ Optimise layout.** One step per screen with Back/Next, or one long page with collapsible steps? A sidebar holding the live config works for one channel; with 5 channels × several modules it gets long. Suggestion: optimise one FISH channel at a time (channel picker at the top); the sidebar shows the settings for the current step and channel, plus a short summary of the whole config.

Decision: one long page with collapsible steps. 

**H3 Threshold helper.** Suggestion: LoG image (MIP) with pixel values shown on hover; an intensity profile along a line between two clicked points (small add-on package) or typed end points; a histogram with the threshold marked; detected spots redrawn as the threshold slider moves. Adds `plotly` and one small add-on. Acceptable?

Decision: yes acceptable. 

**H4 Folder picker.** Native folder dialog (opened by a small helper) with a text box as fallback?

Decision: yes. 

**H5 Batch tab.** Starts the command-line batch as a separate process; shows progress (n of N, current image), the live log, a table of failures and a Cancel button; reconnects to a running batch after a browser refresh. App and command-line runs give identical outputs.

Decision: starting a command-line batch separately is fine as long as the user doesn't have to open terminal themselves. 

**H6 Look.** Reuse the ProbeDesign palette and layout. Styrene B is a trial licence: switch to an open font (e.g. Inter or IBM Plex Sans), or buy a licence?

Decision: Switch to an open font.

**H7 Launching the app.** `bigfish-pypeline app` from a terminal only, or also double-click launchers (`.command` on macOS, `.bat` on Windows)?

Decision: both. 

#### I. Notebook

**I1 Notebook form.** One optimise notebook that imports from the package. Each step has one short parameter cell; a `config` object fills up as cells run; the last cell saves the YAML. Users still edit Python values in cells (the app is the no-code route). Or should the notebook use widgets?

Decision: The non-widget option. 

#### J. Tests and documentation

**J1 Tests.** Unit tests per module (including synthetic images with known spot positions), comparison with the reference run (A1), an end-to-end batch test on 2–3 small images, and basic app tests. Windows and Linux testing: automatic via GitHub Actions (needs tiny test images in the repo), or by hand on lab machines?

Decision: ok, but keep testing to my mac dev for now and window and linux testing for later. 

**J2 Edge cases.** Draft list: spaces or accents in paths; images with no spots; single-plane images; mixed image sizes in one batch; channel index out of range; missing label file; corrupt file; very large image; OMERO disconnecting mid-batch; no GPU; running out of memory. Others from lab experience?

Decision: these are fine. 

**J3 ★ Documentation format.** Suggestion: README (overview, install, quick start) plus one user guide written in Quarto (already used in the repo), rendered to HTML and PDF. The guide includes a "start here" chooser by experiment type (smFISH cells/tissue, HCR, RNAscope) pointing to the matching preset, and a page for existing users (old config → new config, `.npz` → CSV, why manual thresholds shift). Alternative: an MkDocs website on GitHub Pages.

Decision: Read me and HTML (no pdf) is fine. Would readthedocs be better?

### Follow-up to answers

`AGENTS.md` updated (B7). Repo clean-up (C4) kept as a later to-do.

#### A5: what the cell-level bug is and what it affects

- **Affected:** `general/smFISH-quantification_get-cell-level-results.ipynb` and `HCRv3_spot-count/HCRv3-quantification_get-cell-level-results.ipynb`, the step that takes batch `.npz` output plus mask images and splits spots and clusters into cells.
- **Not affected:** the batch scripts (general, HCRv3 and posthoc only write whole-image results); the tissue-culture batch script (uses big-fish's `extract_cell`, which assigns correctly); `parse_npz.ipynb` (only summarises).
- **What goes wrong:** for each cell, the notebook walks through every spot:

  ```python
  if masks[tuple(rna)] == label:   # spot is in this cell
      in_mask = 1
  elif masks[tuple(rna)] == 0:     # spot is in the background
      in_mask = 0
  # no rule for a spot in a different cell: in_mask keeps the previous spot's value
  ```

  Example for cell 1, spots in list order: A in cell 1 → counted; B in cell 2 → no rule, keeps "counted" → **wrongly counted in cell 1**; C in background → not counted; D in cell 2 → keeps "not counted" → correct.
- So a spot in another cell is wrongly counted whenever the spot before it in the list belonged to the current cell. Spots are listed plane by plane, row by row, so cells lying side by side with no background between them are hit hardest; cells well separated by background are barely affected. Clusters have the same problem. Counts can only be inflated, never reduced, and one spot can be counted in two cells.
- **Quick check on old results:** for each image, if the sum of per-cell `total_RNAs` is larger than the number of spots that fall inside any cell, the counts were inflated. A small re-run script could reuse the new cell-assignment step (Phase 3) at little extra cost. In scope?
- The notebook looks up masks with (z, y, x), so it was used with 3D mask stacks (`Hys_*.tif`). With 2D labels only (D10), those analyses would need a 2D mask. Acceptable?

Decision: Ah good, no one uses optimise jupyter lab for actual analysis yet. Let's fix the bug nonetheless. 

#### B1: big-fish, what is needed

- Correct that the pipeline does not use the `selem` code: it sits in `bigfish.segmentation` and `bigfish.classification`, which the new package will not import. `np.int` is only in `compute_snr_spots`, which the pipeline does not call either (per-spot SNR will come from the posthoc function, D8). A scan of the installed big-fish found no other functions removed in numpy 2.
- So the known problems can be avoided without changing big-fish. The unknown is whether results shift slightly under numpy 2, scipy 1.18 and scikit-image 0.26; also, `bigfish.stack` imports `square` and `rectangle`, which recent scikit-image has deprecated and may remove in a later release.
- Steps:
  1. You: fork `fish-quant/big-fish` to `JeffLeeLab/big-fish` on GitHub (Fork button only).
  2. Phase 2, on a branch of the fork: guard the `selem` import, replace `np.int`, fix whatever big-fish's own tests (22 test files) flag under the new packages, set the version to `0.6.2.post1` and tag it.
  3. The env file installs it with `pip install git+https://github.com/JeffLeeLab/big-fish.git@v0.6.2.post1`.
  4. The reference comparison (A1) confirms detection results are unchanged.
- Optional: offer the fixes back to fish-quant as a pull request.

Decision: doesn't posthoc snr also use the same `compute_snr_spots` function that requires `np.int?`. Nonetheless, let's do a fork first. The fork in my laptop is here: `/Users/jefflee/Documents/Incubator/big-fish`.

#### B3 + B4: conflict between conda-forge Cellpose and `cpsam_v2`

conda-forge Cellpose 4.1.1 only ships `cpsam`; `cpsam_v2` arrived in 4.2.0 (June 2026), which is pip-only. Options:

- (a) conda-forge Cellpose 4.1.1 with `cpsam`.
- (b) torch from conda-forge, then `pip install cellpose==4.2.1.1` on top, giving `cpsam_v2`. conda still handles torch and the GPU build (CUDA on the workstation, Apple GPU on Macs; to be confirmed on the workstation).

Suggestion: (b).

Decision: Can't both torch and cellpose 4.2.1.1 come from pip with specifiec versions?

#### New: Windows workstation through WSL2

The workstation runs Ubuntu inside WSL2.

- Is WSL2 the only Windows route, or must the pipeline also run natively on Windows? If WSL2 only, "Windows support" means Linux support plus a `.bat` launcher that starts the app inside WSL2.
- Images on the Windows side are reached as `/mnt/c/...`, and reading from there is noticeably slower than from WSL2's own disk. Users may paste Windows paths (`C:\Users\...`); the pipeline should convert them.
- The native folder dialog (H4) needs WSLg (Windows 11) and returns Linux-style paths.

Decision: WSL2 is not the only Windows route. People will run streamlit application natively on their windows. 

#### F1: one config format, explained

Today the same setting has different names in different places: the notebook uses `threshold`, `radius`, `Ex`; the batch YAML uses `smFISH_ch1_thresh`, `bf_radius`, `ex`. Users copy values across by hand. The proposal is one file layout, written by the notebook and the app and read by the batch, for example:

```yaml
config_version: 1
run:
  name: ago1_test
  input: {source: local, folder: "/Users/me/images", filter: ".tif"}
  output_folder:              # empty = <input folder>/bigfish_results/...
  workers: 4
image:
  axes: ZCYX
  voxel_size_nm: {z: 200, yx: 65}
microscope: {type: confocal, NA: 1.45, RI: 1.45}
channels:
  - index: 2
    name: Ago1-Q570
    ex: 570
    em: 610
    background: {method: rolling_ball, radius_px: 5}
    threshold: {mode: auto, lower_limit: 8}
    decomposition: {on: true, alpha: 0.5, beta: 1}
    subpixel: {on: false}
    clusters: {on: true, radius_nm: 600, min_spots: 12}
segmentation:
  on: true
  source: cellpose            # or: label_files
  channel: 1
  projection: max
outputs:
  qc: {elbow: true, detection: true, reference_spot: true, cellpose: true, final: png}
  label_images: true
```

- `config_version` lets a future pipeline recognise an older file and convert it or explain what changed.
- Checks run before any image is processed and stop with a plain message, e.g. "`nb_min_spot` is not a known setting – did you mean `min_spots`?" or "`voxel_size_nm.z` must be a positive number", instead of crashing halfway through a batch. `pydantic` is a package that does these checks.
- Old configs (general, HCRv3, tissue, posthoc): should the new pipeline read them directly, or is a page in the guide mapping old names to new ones enough? Suggestion: the guide page only.

Decision: your suggestion is fine. For old configs, guide page only. 

#### D6: step order and presets, for discussion

How the steps depend on each other:

- Always: load → prepare → background + LoG → detect spots.
- Optional, in this order: decompose dense regions → subpixel fitting → clusters → per-spot SNR/intensity. Each takes whatever spots exist at that point, so clustering works with or without decomposition.
- Optional, alongside: per-cell results (Cellpose or label files) → assign spots and clusters to cells.

Points to settle:

1. **Presets.** Suggestion: two questions, giving four presets:

   | | Whole image | Per cell |
   |---|---|---|
   | smFISH | detect + decompose + clusters | + segmentation |
   | HCR / RNAscope (amplified) | detect only | + segmentation |

   Tissue and cultured cells differ in parameter values (e.g. cluster radius, minimum spots), not in which steps run, so they would be hints within a preset rather than separate presets. Subpixel fitting off in all presets, recommended for colocalisation work.
2. **Per channel or per image.** Can one image mix assay types (e.g. smFISH in one channel, HCR in another)? If yes, the step switches belong to each channel (fits D4), while segmentation stays per image.
3. **Guidance.** App: a short "What are you analysing?" question at the top that sets the switches, plus a one-line note on each step saying when to use it. Notebook: a preset name in the first cell.
4. **Default values.** Notebooks and batch configs disagree (cluster radius 400 vs 600 nm, minimum spots 5 vs 12, `cellprob_threshold` −6 vs 0, clip value 10 vs 120). Which values become the defaults, per preset?

Decision: 1. Yes on the suggested presets. 2. yes it can mix assay types. 3. sounds good. 4. those values are just from empirical runs. set cluster radius 500, min_spot 5 (or whatever big-fish default is), and cellprob as 0, clip value 100 but turned off by default. Every preset has the same config default, preset only sets which module gets turned on. The preset is not set by the config, the preset only changes the module turning off and on and is over-ridable. 

#### G1: parallel processing, for discussion

Agreed: segmenting everything first means a stop during detection leaves no finished image, and with no resume (F5) the whole run is lost. With OMERO and no local copy (D3), each image would also be downloaded twice.

Per-image errors are caught and logged, so the run continues past a bad image. A whole run stops only through laptop sleep, Cancel, power loss or running out of memory.

Options:

- (a) **Everything per image in each worker.** Each worker loads its own Cellpose model. Simple, but each copy of `cpsam_v2` takes ~1.2 GB of (GPU) memory and the workers queue for the single GPU anyway; tight on a 16 GB Mac with 4 workers.
- (b) **Segment all, then detect all** (original suggestion). Downsides above.
- (c) **Streamed.** The main process loads the model once, segments image 1 and passes it to the worker pool for spot detection, then segments image 2 while image 1 is being processed. Each image is finished (labels, spots, tables, QC) as soon as its detection completes, so a stop loses only the images in progress. The main process reads only the segmentation channel and the workers read only the FISH channels, so nothing is downloaded twice from OMERO.

Suggestion: (c), plus keeping the computer awake during a run (`caffeinate` on macOS, the equivalent on Windows), since 100–200 images will take hours.

Numbers to measure in Phase 0: a 2048×2048×30 channel is ~250 MB as 16-bit and ~1 GB as 64-bit decimals during processing; with several intermediate copies each worker may need 3–4 GB, so a 16 GB laptop would run 2–3 workers. Cellpose-SAM without a GPU may take minutes per image. Rolling ball at 5 px may be the slowest step overall.

Decision: (c) is fine. 

#### Smaller follow-ups

- **B5:** which is the default background method, rolling ball or top-hat? Does the same choice apply to the segmentation pre-treatment (D9), and what default radius there?
- **D9:** pre-treatment order: projection → clip → background → median → Gaussian?
- **D10:** fixed suffix `_cplabels` even for hand-drawn labels, or a setting with `_cplabels` as default?
- **E1:** `cluster_id = -1` for spots not in a cluster (big-fish already does this), matching `cell_id = -1`? `cell_id` column left out when segmentation is off? Coordinates in pixels, nm or both? Keep an `.npz` option?
- **E3:** an interactive HTML cell map with a full-resolution image is several MB; 200 images × 2 channels could reach a few GB. Suggestion: PNG by default, HTML as an option, and the app's Results page shows the interactive view on demand from the tables and label images.
- **D7:** reference spot saved as TIFF (as now) or PNG?
- **H2:** with one long page, still one FISH channel at a time (channel picker at the top)?
- **A2 + J1:** can small crops of the test images go in the public repo? They are needed for automatic Windows/Linux testing.
- **Still open:** I1, J1, J2, J3.

Decision:

B5: rolling ball. In D9, rolling ball 200 is the default. 
D9: your suggestion is fine. 
D10: you have a good point let's do `seglabels`.
E1: Yes, but keep cell_id col even when seg is off, just all -1. Coordinates both in px and nm. Keep .npz option but turned off by default. 
E3: yes PNG by default and HTML as an option. 
D7: reference spot always saved as TIFF. 
H2: one FISH channel at a time with channel picker at the top. 
A2+J1: yes.


### Follow-up, round 2

#### A5: which notebooks

The bug is in the **get-cell-level-results** notebooks (general, HCRv3), not the optimise notebooks. If those have not been used for real analyses either, no past results are affected. The new cell-assignment step replaces this code. Should the one-line fix (`else: in_mask = 0`) also go into the two old notebooks before the `v1.0` tag, so the archived copies are correct?

Decision: yes fix the to-be-archived copies. 

#### B1: SNR and the fork

- The posthoc SNR code uses its own function, `compute_snr_spots_individual`, not big-fish's `compute_snr_spots`, so `np.int` is not a problem there. D8 will reuse the posthoc function.
- Fork checked: `/Users/jefflee/Documents/Incubator/big-fish`, linked to `JeffLeeLab/big-fish`, `master` = the 0.6.2 release, no local changes. Upstream also has an unreleased `develop` branch with 36 later commits (code reformatting, style checks, automatic testing; no changes to results). Suggestion: base the patches on `master` (0.6.2), so behaviour stays identical to what the lab has been using. Patching happens in Phase 2.

Decision: your suggestion sounds good. 

#### B3 + B4: torch and Cellpose both from pip?

Yes, both can come from pip with fixed versions. The catch is torch:

| | pip torch 2.14.1 | conda-forge torch 2.14.1 |
|---|---|---|
| Mac, Apple silicon | yes (macOS 14 or later) | yes |
| Mac, Intel | no current version | yes |
| Linux / WSL2 + NVIDIA | yes, with GPU | yes, with GPU |
| Windows + NVIDIA | without GPU by default; the GPU version needs a separate download address | yes, GPU version available |

Suggestion: torch from conda-forge, Cellpose 4.2.1.1 from pip, both pinned to exact versions (equally reproducible). All-pip works if no one uses an Intel Mac or a Mac older than macOS 14, and Windows users with an NVIDIA GPU accept one extra install step. Does anyone in the lab use an Intel Mac, or a Mac older than macOS 14?

Decision: let's go with your suggestion

#### Native Windows

Recorded: the app must run natively on Windows, with WSL2 as an extra route. With J1 (Mac testing only for now), native Windows will be untested until later. OMERO's own team also lists Windows as untested. Is Windows/Linux testing the last MSP phase, or after MSP?

Decision: last MSP phase. 

#### D6: presets, as decided

Because assays can differ between channels, a preset is two separate choices:

- **Assay type, per channel:** smFISH (detect + decompose + clusters) or amplified FISH, i.e. HCR/RNAscope (detect only).
- **Per-cell results, per image:** segmentation (Cellpose or label files) and cell assignment on or off.

Presets only set step switches; they can be overridden and are not saved in the config (only the switches are). Defaults: cluster radius 500 nm, `cellprob_threshold` 0, clip value 100 (clip off). big-fish's own default for minimum spots per cluster is **4** (its default radius is 350 nm). Use 4, or 5?

Decision: 4. 

#### E4: label file name

With D10 now `<image>_seglabels.tif`, Cellpose output would use the same name so a later run can reuse it. Confirm?

Decision: confirmed. 

#### J3: Read the Docs or not

Read the Docs is a hosting service, not a document format. It rebuilds the HTML site from the repo on every change and serves it at e.g. `bigfish-pypeline.readthedocs.io`, with search and a version switcher (v1/v2). It normally builds Sphinx or MkDocs sites; Quarto needs custom build steps. The free plan shows small adverts.

Alternative: a Quarto website on GitHub Pages (e.g. `jeffleelab.github.io/bigfish-pypeline`), built automatically by GitHub, with search, no adverts and no version switcher. Since v1 will be archived, version switching matters little.

Suggestion: Quarto on GitHub Pages. Read the Docs (with MkDocs) if a version switcher or the familiar Read the Docs look matters.

Decision: Let's stick to quarto then.

## Spec review (17 Nov 2026)

Two outside reviews of `msp-spec.md` (`archive/msp-spec-review-argon.md`, `archive/msp-spec-review-astra.md`) were checked against the repo, the big-fish fork and current package releases. The decisions below change or add to the ones above.

**R1 Phase order (changes A3).** The dev env uses Python 3.12 and Cellpose 4 from Phase 0; Phase 1 no longer builds on the v1 stack with Cellpose 3. Reason: Cellpose 3 results are not a target (A1), so that code would be written and then thrown away. The v1 reference comes from the unchanged main env. Cost: restructuring and upgrading now happen together. If Phase 1 differs from v1, the v1 script is run in the new env to separate the two causes.

**R2 Test images (changes A2).** One full-size image, one crop and one reviewed label image for the crop, in place of the six-image set. Other cases are generated in the tests. Reason: rolling ball and Cellpose 4 change results by design, so a large v1 reference set would be replaced almost at once. big-fish's own tests do not cover detection, decomposition, fitting or clusters, so the crop comparison and the synthetic tests carry that check.

**R3 Spot intensity.** The value of `rna_log` at the spot's own position (z, y, x), not the MIP value. Reason: the two agree except where something brighter lies above or below the spot, and there the MIP value belongs to the other object.

**R4 Cancel and worker failures.** Cancel stops the workers at once and discards images in progress. After a worker stops unexpectedly, the run restarts with fewer workers and retries the images in progress once. Reason: Python's process pool does neither by itself, and it cannot tell which image caused a stop.

**R5 Earlier answers folded into the spec.** Windows and Linux testing (Phase 7) comes before the release (Phase 8); `posthoc_analysis/` is archived in Phase 8; the app font is Inter; Cellpose `batch_size` stays at 1; the run folder is grouped by type; file names use the channel index.

**Checked and left unchanged.** PyTorch 2.14.1 exists (released 30 Sep 2026). Rolling ball at 5 px took about 1.2 s per 2048 × 2048 plane against 0.9 s for the current top-hat (one random plane, main env), so it stays the default background method.

## Before Phase 0 (22 Nov 2026)

**R6 Test image (changes R2).** `20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001.tiff`: ZCYX, 35 × 4 × 2048 × 2048, 16-bit, 65 nm pixels, 200 nm Z-steps; channels 0 DAPI, 1 Phalloidin, 2 jim exon, 3 jim intron. Only the exon channel (2) is used for testing, not the intron channel. The DAPI channel is kept for later work on nucleus segmentation. A small crop may be made public and may be cut down in Z. The earlier analysis of this image series used a v1 general config (manual threshold 18, cluster radius 600 nm, minimum spots 12) written for a related image set, so its values are the starting point for the reference run.

**R7 Crop labels.** The crop's label image holds nuclei, drafted from the DAPI channel and corrected by the user. Reason: Cellpose does not suit these brain images; cell assignment treats any label image the same way, so nuclei test it equally well, and they suit exon/intron work and later nucleus segmentation.

**R8 Cellpose 4 (changes Phase 0 and Phase 2).** Still built in Phase 2, checked by automated tests only. No Cellpose-SAM benchmark in Phase 0; Phase 2 measures its time and memory for the worker estimate without judging the masks. The user reviews masks on a suitable image (e.g. cultured cells) supplied later, before the release. Reason: Cellpose-SAM does not suit the lab's brain images.

**R9 Models.** `msp-plan.md` names the model that orchestrates the work and the models and effort levels that carry out each task.

Reviews archived to `archive/`.
