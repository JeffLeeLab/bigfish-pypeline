# MSP specification review

Review of `msp-spec.md` against the current codebase (`src/bigfish_pypeline/`, `general/`, `HCRv3_spot-count/`, `tissue-culture_cells/`, `omero/` and `posthoc_analysis/`).

## 1. Test images and reference runs

### Why the six-image reference suite in Phase 0 is unnecessary

1. **Outputs are expected to change by design.** Switching background subtraction from top-hat to ImageJ rolling ball changes pixel intensities in `rna_log`, shifting both manual and automatic elbow thresholds. Switching from Cellpose 3 (`cyto`) to Cellpose 4 (`cpsam_v2`) changes cell masks. Running all v1 batch scripts across six curated datasets in Phase 0 to build a reference set that Phase 2 immediately replaces adds heavy preparation work for little benefit.
2. **Core `big-fish` calculations can be checked without real images.** Upgrading Python (3.9 to 3.12) and NumPy (1.21 to 2.x) can be validated by running `big-fish`'s own test suite (22 test files in `/Users/jefflee/Documents/Incubator/big-fish`) and synthetic 3D Gaussian spot arrays in `pytest`.
3. **Edge cases are easier to test with synthetic arrays.** Image layouts (`ZCYX`, `CZYX`, `ZYX`, `CYX`, `YX`), 2D vs 3D handling, three or more FISH channels, blank images with zero spots, bailout limits, border-cell filtering, and file names with spaces or accents can all be generated on the fly in `pytest`.

### Where a real image is still needed

Synthetic images fall short in three places:

1. **Cellpose 4 (`cpsam_v2`) and QC plots.** Cellpose-SAM is trained on real cell textures and often finds no cells on synthetic shapes. A real image is needed to check `segmentation.py`, the 4-panel Cellpose QC figure, and the final cell-map overlay (`final.png` and `final.html`).
2. **App walkthrough and user guide screenshots.** Phase 5 (Streamlit app) and Phase 6 (Quarto guide screenshots via `playwright-cli`) need a real image so channel MIPs, the LoG line profile, elbow plots, and cell overlays look realistic.
3. **Speed and memory benchmarks.** Timing rolling-ball background subtraction at 5 px and measuring peak worker memory require one full-size `2048 × 2048 × 30` Z-stack so `workers: auto` is calibrated accurately.

### Minimal test dataset (one image)

- **Local full-size image (outside git, via `BIGFISH_TEST_DATA`):** One 3D multi-channel `.tif` (for example, cultured cells with one cytoplasm or nucleus channel for Cellpose and one or two smFISH channels containing spots and clusters). Both the smFISH preset (decomposition and clustering on) and the amplified FISH preset (decomposition and clustering off) can be tested on the same file.
- **Committed test kit (`tests/data/`):** One small crop (`~256 × 256 × 15`, 1–2 MB) cut from that image containing 2–3 cells and a few dense regions. All other test cases (2D slice, `CZYX` order, $\ge 3$ channels via channel duplication, blank negative control, spaces in file names) can be derived in `pytest` fixtures from this single crop.

---

## 2. Phase structure: collapsing Phases 0–2

### Issue in the current plan

In `msp-spec.md` (sections 4.3 and 11), Phase 0 creates `bigfish-msp` as a copy of the legacy Python 3.9 + Cellpose 3.1.1.2 environment; Phase 1 builds the new package against Cellpose 3 (`models.Cellpose`); Phase 2 then replaces `msp-environment.yml` with Python 3.12 + Cellpose 4.2.1.1 (`CellposeModel`) and rewrites `segmentation.py`.

### Recommendation

Because Cellpose 3 parity is not needed, build `bigfish-msp` directly with **Python 3.12, Cellpose 4.2.1.1, and the patched `big-fish` fork (`0.6.2.post1`) in Phase 0**:

- **Phase 0 (Environment, patched `big-fish`, test crop and benchmarks):** Patch the `big-fish` fork (`0.6.2.post1`), create `bigfish-msp` on Python 3.12 + Cellpose 4.2.1.1, run `big-fish`'s test suite, prepare the single test image and crop, and benchmark rolling ball (5 px) and Cellpose-SAM on the full-size image.
- **Phase 1 (Unified package and CLI batch):** Build `src/bigfish_pypeline` directly with Cellpose 4 and rolling ball (with `tophat` retained as an option). If a spot/cluster comparison against v1 is desired on the test image, running Phase 1 with `background: {method: tophat}` already tests that in Python 3.12 without needing a temporary Python 3.9 environment.

This removes an entire environment rebuild and avoids writing throwaway Cellpose 3 code.

---

## 3. Technical findings from codebase and spec comparison

### 3.1 OMERO session closing across worker processes (`src/bigfish_pypeline/omero_tools.py`)

- **Spec (sections 5.3 and 7.1):** The main process opens one OMERO session and passes the session key in memory to batch workers so they join the existing session instead of logging in again.
- **Codebase issue:** `connect_to_omero` in `src/bigfish_pypeline/omero_tools.py` (lines 51–60) registers an `atexit` handler that calls `conn.close()`. In OMERO's `BlitzGateway`, calling `conn.close()` on a connection joined by session key closes the session on the server for all processes. As soon as the first worker process exits, the main process and all other workers will lose their OMERO connection.
- **Change needed:** Add a worker helper that attaches with `conn.connect(sUuid=session_key)` without registering `conn.close()` on exit. Only the main process should create, keep alive (`keepAlive`), and close the session.

### 3.2 Rolling-ball speed at 5 px on 3D FISH stacks (section 5.4)

- **Spec:** Default background subtraction for FISH channels is `rolling_ball` with `radius_px: 5` applied to each Z-plane (`imagej_rolling_ball.py`).
- **Risk:** For radii $\le 10\text{ px}$, ImageJ's rolling-ball algorithm does not shrink the image before sliding the ball. On a `2048 × 2048 × 30` stack, running unshrunk sliding-minimum loops in Python/NumPy across 30 planes per channel can take 30–90+ seconds per channel per image (unlike the 2D segmentation pre-treatment at radius 200 px, which shrinks by $8\times$ and finishes in milliseconds).
- **Change needed:** Treat the Phase 0 benchmark of `rolling_ball` at 5 px on a 30-plane stack as a decision gate. If `imagej_rolling_ball.py` is too slow at 5 px, check whether `scipy.ndimage.grey_erosion` / `white_tophat` with the 3D ball footprint or parallel plane evaluation brings the runtime down, or keep `tophat` as the 5 px FISH default and `rolling_ball` (200 px) as the segmentation default.

### 3.3 Dense-region decomposition on images with zero or very few spots (section 5.6)

- **Spec (section 13):** An image with no spots should finish with status `done` and empty spot rows.
- **Codebase issue:** In `general/batch_script/smFISH_data_analysis_multiprocess.py` (lines 106–157), `detection.build_reference_spot` and `detection.modelize_spot` raise a `ValueError` or `RuntimeError` inside `big-fish` when `spots` is empty or when too few isolated spots pass the SNR check to build a reference spot.
- **Change needed:** In `decomposition.py`, guard `build_reference_spot` and `modelize_spot`: if `len(spots) == 0` or a reference spot cannot be built, log a warning in `run.log`, skip decomposition for that channel, and pass `spots` forward as `spots_post_decomposition` instead of failing the image.

### 3.4 Spot intensity definition for 3D stacks (section 5.6 and section 17, point 6)

- **Spec note (line 618):** Spot intensity is noted as *"MIP rna_log value (so background subtracted and log filtered)"*.
- **Issue:** In 3D stacks, `spots_thresholding` detects and thresholds each spot at its 3D coordinate `rna_log[z, y, x]`. Sampling the 2D maximum projection `rna_log_mip[y, x]` assigns the wrong value whenever a dim spot at one Z-plane sits above or below a brighter spot or out-of-focus feature at another Z-plane.
- **Recommendation:** Record `rna_log[z, y, x]` at the spot's actual `(z, y, x)` coordinate (which is identical to the MIP for 2D images, and matches the thresholded LoG value in 3D).

### 3.5 PyTorch version number in section 4.3

- **Spec (line 96):** Lists `pytorch | conda-forge | 2.14.1`.
- **Correction:** PyTorch is in the `2.x` series (currently `2.5.x`–`2.6.x`; `2.14.1` does not exist). Use `pytorch >=2.4` in `msp-environment.yml` and record the exact resolved version in `msp-devlog.md`.

### 3.6 Incorporating confirmed points from section 17

When `msp-spec.md` is next updated, the confirmed answers in section 17 (lines 609–622) can be folded into the body of the spec:

- **Font (point 7):** Use **Inter** as the open font in `app/.streamlit/config.toml` (clean legibility for dense parameter sidebars and data tables).
- **Phase 7 and 8 numbering (points 1 and 8):** Section 11 already has Phase 7 as Windows/Linux testing and Phase 8 as main env replacement and archiving; update point 8 so `posthoc_analysis/` is archived in Phase 8 alongside the other v1 folders.
