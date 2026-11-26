# Test kit

Small crops of real smFISH images, used by the automated tests.

## Tissue

A crop of a tissue image, used to compare the pipeline with the v1 results.

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

## Cultured cells

A crop of an image of cultured cells, used to test cell segmentation by Cellpose.

| File | Contents |
|---|---|
| `culture_DAPI_cellmask_exon_crop.tif` | The image: 31 Z-planes × 3 channels × 384 × 384 px (layout `ZCYX`), 16-bit, saved with lossless compression. Pixel size 65 nm, Z-step 200 nm. |
| `culture_DAPI_cellmask_exon_crop_config.yaml` | Pipeline settings for this image: Cellpose on the cell-mask channel, spots in the exon channel. |

Channels, counted from 0:

| Channel | Stain |
|---|---|
| 0 | DAPI (nuclei) |
| 1 | Cell mask (whole cells) |
| 2 | Exon smFISH probes, Quasar 570 (the channel the tests analyse) |

The crop was cut from a 2000 × 2000 px image with 31 planes (100× objective). Its top-left corner is at y = 640, x = 1344, and it holds every plane. In planes 0–11, counted from 0, the cells spread over the coverslip and overlap; from plane 12 upwards they stand apart. The crop holds three to four cells, two of which touch. The full-size image is not part of the repository.
