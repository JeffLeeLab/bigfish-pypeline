# MSP specification review — Astra

## Overall assessment

The shared package, configuration format and local app are a sound direction. The main risks are in image interpretation, the connections between processing steps, batch execution and output definitions. Keeping the big-fish algorithms does not by itself preserve results when their inputs or surrounding code change.

The reference-image requirements in [Phases 0–2](msp-spec.md#11-development-phases-brief-a3) are heavier than necessary. Reduce them, remove the temporary Cellpose 3 implementation, and resolve the batch and configuration issues below before substantial implementation. The main environment should remain unchanged throughout development.

## 1. Test images and comparisons

### Minimum useful dataset

| Item | Contents | Purpose |
|---|---|---|
| One full-size raw TIFF, kept locally | A representative 3D stack with a FISH channel, a suitable cell-segmentation channel, isolated spots and a dense region | Cellpose 4 review, visual QC, initial runtime and memory measurements |
| One crop from that image | Approximately 256–512 pixels square, sufficient Z depth, several complete cells, comfortably more than 30 isolated spots away from the edges, and a dense region | Routine processing, command-line, notebook and app checks |
| One fixed label image for the crop | A reviewed 2D label map | Repeatable cell-assignment and table checks without loading Cellpose |

Choose the crop by its contents. More than 30 isolated spots avoids the local big-fish reference-spot warning threshold, but is not a guarantee of successful modelling. Generate reference results from the crop itself: cropping changes background estimation and automatic thresholds. The fixed labels need not be an exhaustive biological ground truth.

Use generated images for alternative axes, 2D input, three or more channels, blank images, filenames, bailout, invalid inputs and exact cell-boundary cases. A second HCR or tissue image is useful only where its appearance needs separate practical assessment. Testing the amplified-FISH switches on a smFISH crop checks the software path, not HCR image quality. A synthetic blank checks empty-output handling, not experimental false-positive rates.

The tracked `rna_log.tif` files are processed outputs, not replacements for a raw input fixture. One full-size image provides an initial resource estimate; the planned workstation batch must still check sustained processing.

Image preparation need not block package and configuration work. Keep full-size data outside git through `BIGFISH_TEST_DATA`; include the small crop only if suitable for the public repository.

### Keep comparisons focused

- Compare the old and new spot-processing paths on the crop using top-hat, equivalent settings and no segmentation. There is no need to run every old script across every proposed dataset.
- Assess Cellpose 4 masks on their usefulness. Agreement with Cellpose 3 is not an acceptance requirement; existing masks can provide context.
- Check rolling-ball accuracy against the existing ImageJ reference fixture. Review its effect on thresholds and detections separately from the top-hat comparison.
- Exercise decomposition, subpixel fitting and clustering explicitly under the new stack. In the local big-fish fork, `test_spot_detection.py`, `test_dense_decomposition.py`, `test_spot_modeling.py` and `test_cluster_detection.py` contain TODOs for these functions. Passing the upstream suite alone does not establish this coverage.

## 2. Issues to resolve before implementation

### 2.1 Cancellation and worker recovery need an explicit design

**Spec: sections 7.1–7.3 and 10.3.**

The spec promises to stop running workers on cancellation and recover when a worker dies. Python 3.12's `ProcessPoolExecutor` does not provide those behaviours simply by cancelling futures: cancellation leaves running tasks active, and an abrupt worker exit breaks the pool. See the [Python 3.12 executor documentation](https://docs.python.org/3.12/library/concurrent.futures.html).

Define a cancellation signal shared by the app, coordinator and workers. The simplest policy is to stop scheduling and check for cancellation between processing steps; document that a long Cellpose or decomposition call may finish first. Immediate termination needs a separately designed process-control mechanism.

On pool failure, retain confirmed complete images, distinguish unfinished from never-started work, and limit retries. Repeatedly restarting with the same memory settings could repeat the failure. Write per-image outputs to temporary locations, then mark the image complete only after its required outputs are safely written. Combine only completed results. Update `progress.json` by replacement so the app cannot read a half-written file.

The recent-runs record also needs a run identifier and reliable liveness check. A stale record must not make a dead batch appear active, or let Cancel target an unrelated process.

### 2.2 Memory estimates omit competing allocations

**Spec: sections 7.1–7.2 and 10.1.**

The worker formula allocates available memory to workers without an explicit allowance for the coordinator, Cellpose, image buffers and the app. The app may retain its model while a separate batch process loads another. On Apple silicon these compete for unified memory.

Reserve memory for these allocations and limit queued image/label data. Base the estimate on the largest selected image and enabled steps, with a margin; the spec permits different image sizes in one batch. Allow at least one worker only when sufficient memory remains, otherwise stop with a useful message. Include a policy to release the app's model or prevent concurrent segmentation while a batch uses it.

Specify how labels reach workers when `outputs.label_images` is false: disabling a saved output must not break cell assignment. Internal temporary labels or a bounded in-memory transfer are both possible.

### 2.3 Saved configurations do not yet guarantee repeatable runs

**Spec: sections 5.5, 7.1, 8.1, 8.4 and Phase 3.**

`run_config.yaml` is written before calibration. Resolved thresholds are saved in `run_info.yaml`, but passing only `run_config.yaml` back will rediscover inputs and recalibrate. Adding files to the folder or changing dataset membership can therefore change the result.

Save the resolved input list and calibrated values in a form the runner can reuse. Distinguish repeating the recorded run from applying its settings to a new selection. Record input identity/change information and the model-weight identity as well as software versions. Keep the original calibration settings for traceability.

The local big-fish `detection/utils.py` randomly selects up to 2,000 candidate spots for a reference spot. Record a seed and derive stable image/channel seeds independent of worker order. Define equality as matching scientific table contents after sorting, excluding timestamps and runtime fields. State tolerances for fitted coordinates; do not promise identical masks across devices.

### 2.4 Calibration and partial failures need defined outcomes

**Spec: sections 5.5, 7.1, 8.2 and 13.**

The spec covers a calibration filter matching no images, but not images that fail loading, produce no usable automatic threshold or exceed the bailout limit. Define which values enter the median. Record exclusions and reasons; stop before the main run if a required channel has no valid calibration values. Do not silently substitute zero for an unavailable threshold.

Clarify the difference between a valid threshold yielding zero spots and no threshold being available. Define when decomposition is skipped for insufficient usable reference spots, and retain a visible warning rather than hiding the fallback.

`images.csv` has one row per image/channel, while error handling is described per image. Make channel-specific bailout affect only that channel; specify whether other channel failures also preserve successful channels. Missing labels or failed segmentation must be distinguishable from a valid segmentation with zero cells. Use explicit segmentation/step status or warning fields rather than making readers infer this from `cell_id = -1`.

### 2.5 Cell counts and measurements need precise meanings

**Spec: sections 5.6, 5.8, 8.2 and 17.**

Spots are assigned individually to cells, while clusters are assigned by their centres. A cluster can cross a cell boundary: a cell may contain clustered spots without owning the cluster centre. Define `n_spots_in_clusters`, `n_clusters` and especially `mean_spots_per_cluster` so they remain interpretable in this case. For example, count clustered spots by their own cell membership, count clusters by centre, and calculate mean cluster size over those centre-assigned clusters. Document that these quantities need not divide into each other; use an empty value when there are no assigned clusters.

Specify whether cell assignment and measurements use fitted or integer coordinates, including bounds checks before label indexing. Label files also need non-negative integer validation, with zero reserved for background; matching shape alone is insufficient.

Keep the user's chosen intensity definition: the LoG maximum-projection value at the spot's XY position. Name and document it explicitly, for example `log_mip_intensity`; two spots at different Z positions but the same XY position will share this value. Do not silently replace it with the 3D voxel value.

The [existing per-spot SNR function](../../posthoc_analysis/snr/formamide_ec/batch_script_20260120/smFISH_snr_analysis_multiprocess.py) assumes three dimensions and fixes `ndim=3`. Supporting 2D therefore requires more than removing unused variables. Specify its input image, coordinate sampling and treatment of an empty or constant background neighbourhood.

### 2.6 Image confirmation conflicts with configuration defaults

**Spec: sections 5.3 and 6.2.**

The spec requires explicit confirmation and no silent voxel defaults, but the schema example supplies `ZCYX` and `{z: 200, yx: 65}`. If these become operational defaults, an incomplete configuration can produce plausible but wrongly scaled results.

Make axes and required voxel sizes mandatory in a runnable configuration. Use suggested values only in the interface until confirmed. Resolve relative paths against the configuration file's directory and save resolved paths in the run record.

The single `yx` value assumes equal X and Y spacing. Reject unequal metadata spacing with an explanation unless separate X/Y support is added. Define handling of singleton time axes and ambiguous TIFF axes without silently accepting genuine time series. State that channel indices start at zero, and preserve original indices when reading only selected channels.

The existing batch scripts fix `ndim=3`. Specify native 2D processing with YX coordinates throughout filtering, decomposition, fitting and measurements; adding a singleton Z axis is not enough to establish the promised 2D behaviour.

### 2.7 App results can become stale after settings change

**Spec: sections 10.1–10.2.**

Changing background subtraction, PSF, voxel sizes or threshold must invalidate all affected later results. Otherwise a newly displayed threshold can coexist with old clusters or cell counts and be exported as if consistent. The [archived app](../archive/streamlit-serverside-withdrawn/bigfish-optimise/app.py) already links processing-stage cache keys; retain and extend that approach for the new switches and segmentation.

Use separate cache identities for images and models. Image keys need source, image identity, selected channels and interpretation settings; model keys need weights, device and precision. A path and modification time is not a complete key for every resource, particularly OMERO.

Bound cached image data, keep shared arrays unmodified and serialise access to a shared model where needed. Streamlit resource caches can share objects between sessions, so their safety must be deliberate. See [Streamlit resource caching](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_resource).

### 2.8 OMERO connection reuse needs separate owner and worker behaviour

**Spec: sections 5.3, 7.3 and 10.3.**

The [current helper](../../src/bigfish_pypeline/omero_tools.py) accepts username/password, creates a keep-alive thread and registers `conn.close()` on exit. It does not implement the proposed worker attachment by session key. Reusing it unchanged will not satisfy the design.

Define who owns the session when the app launches a batch, how workers attach and release their connections, and who keeps the session alive after an app refresh or exit. Verify the selected OMERO client's shared-session close behaviour rather than copying the existing cleanup handler into every worker. A dropped connection and an expired session need separate outcomes: an expired session may require another login. Keep session keys out of run records and logs.

## 3. Phase and installation corrections

| Issue | Recommended correction |
|---|---|
| Phase 1 implements Cellpose 3; Phase 2 replaces it | Build new segmentation with Cellpose 4 once. Retain the existing main environment for the narrow old/new spot-processing comparison. |
| Phase 1 requires logged failures, cancellation and completed-image recovery, but run records and logs are assigned to Phase 3 | Implement the minimum run folder, completion records and logging with the batch runner. Leave additional QC and presentation work for Phase 3. |
| Calibration uses a worker pool in section 7.1 step 3, but the pool starts in step 4 | Start the pool before calibration and reuse it where appropriate. |
| Plotly is installed in Phase 5, but used by the Phase 4 notebook and potentially Phase 3 HTML QC | Install it before the first dependent phase. |
| Section 2 promises environment-only installation; section 4.2 requires `pip install -e .` | State how users obtain the repository and how environment creation installs it. If using an editable checkout, document that the folder must remain in place. |
| The app and launchers sit outside `src/`, and commands can start from any folder | Define how the installed command locates app files and assets. Ensure the package or required checkout contains them. |
| The theme lives at `app/.streamlit/config.toml` | Launch with a controlled working directory or pass configuration explicitly. Streamlit searches the working directory, not automatically the script's directory: see [configuration locations](https://docs.streamlit.io/develop/api-reference/configuration/config.toml). |
| Exact package versions and automatic GPU-build selection are stated before an environment file exists | Resolve and record a working installation for each supported platform; verify the actual device. Treat the proposed pins and GPU selection as unverified until then. |
| Section 17 contains settled answers and old phase numbers | Fold decisions into the body, retain the user's MIP intensity choice, and place archiving consistently in Phase 8. |

## 4. Smaller output details worth fixing now

- Give run folders a unique suffix: minute-resolution timestamps and a reused run name can collide.
- Define stable image keys separately from display names, with safe filenames for OMERO names on Windows.
- Define the scope of spot and cluster IDs and the keys used to join tables: image/channel/spot, image/channel/cluster, and image/cell.
- Narrow the optional NPZ compatibility promise. The [general script](../../general/batch_script/smFISH_data_analysis_multiprocess.py) writes `spots_post_clustering` and `clusters`, while the [HCR script](../../HCRv3_spot-count/batch_script/HCRv3_data_analysis_multiprocess.py) writes `spots`; tissue outputs are per cell. Keeping two keys does not preserve all previous consumers.
- Define reference-spot QC when decomposition is disabled or cannot build a reference, and whether the saved spot is the Gaussian-background-subtracted modelling reference or the other reference saved by the old general script.

## 5. Recommended implementation order

1. Resolve the upgraded development environment and targeted big-fish checks, without changing the main environment.
2. Define runnable configuration, image interpretation, table meanings and repeat-run behaviour.
3. Build the shared single-image pipeline and label-based cell assignment, then add Cellpose 4.
4. Build batch execution with bounded memory, completion records, cancellation and failure handling.
5. Add the notebook and app on those shared functions, followed by documentation and the planned Windows/Linux checks.

The existing phase structure can accommodate this order. The key changes are removing throwaway Cellpose 3 work, reducing reference-data preparation and bringing essential batch records forward.
