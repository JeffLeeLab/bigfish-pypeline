# Test kit

A small crop of a real smFISH image, used by the automated tests to compare the pipeline with the v1 results.

| File | Contents |
|---|---|
| `sypN_DAPI_Phal_jim-exon_crop.tif` | The image: 11 Z-planes × 3 channels × 384 × 384 px (layout `ZCYX`), 16-bit. Pixel size 65 nm, Z-step 200 nm. |
| `sypN_DAPI_Phal_jim-exon_crop_seglabels.tif` | Label image of the nuclei: 384 × 384 px, 0 for background and one whole number (1–44) per nucleus. |
| `sypN_DAPI_Phal_jim-exon_crop_config.yaml` | Pipeline settings for this image. |

Channels, counted from 0:

| Channel | Stain |
|---|---|
| 0 | DAPI (nuclei) |
| 1 | Phalloidin |
| 2 | *jim* exon smFISH probes (the channel the tests analyse) |

The crop was cut from `20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001.tiff` (2048 × 2048 px, 35 planes; Olympus IX83 with a Yokogawa CSU-W1 spinning disk, 100×/1.45 oil objective). Its top-left corner is at y = 1408, x = 1632, and it holds planes 17–27, counted from 0. The full-size image is not part of the repository.

The label image was drawn by Cellpose 3 (`nuclei` model) on the maximum projection of the DAPI channel and has not been corrected by hand. Its outlines are approximate. The tests use it to check that spots are assigned to the right label, not to judge segmentation.
