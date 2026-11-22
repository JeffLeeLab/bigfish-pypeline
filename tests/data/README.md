# Test kit

A small crop of a real smFISH image, used by the automated tests to compare the pipeline with the v1 results.

| File | Contents |
|---|---|
| `sypN_DAPI_Phal_jim-exon_crop.tif` | The image: 11 Z-planes × 3 channels × 384 × 384 px (layout `ZCYX`), 16-bit. Pixel size 65 nm, Z-step 200 nm. |
| `sypN_DAPI_Phal_jim-exon_crop_config.yaml` | Pipeline settings for this image. |

Channels, counted from 0:

| Channel | Stain |
|---|---|
| 0 | DAPI (nuclei) |
| 1 | Phalloidin |
| 2 | *jim* exon smFISH probes (the channel the tests analyse) |

The crop was cut from `20240308_sypN_DAPI_Phal_jim-exon_jim-intron_100x_00001.tiff` (2048 × 2048 px, 35 planes; Olympus IX83 with a Yokogawa CSU-W1 spinning disk, 100×/1.45 oil objective). Its top-left corner is at y = 1408, x = 1632, and it holds planes 17–27, counted from 0. The full-size image is not part of the repository.
