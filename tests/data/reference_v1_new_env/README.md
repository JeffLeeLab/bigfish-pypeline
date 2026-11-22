# v1 scripts run in the new env

Results of the unchanged v1 batch scripts (tag `v1.0`) on the test kit crop, run in the `bigfish-msp` env instead of the main env. Only the four runs with subpixel fitting on are kept here, because they are the ones that differ from `reference_v1/`.

| Folder | Script | Threshold |
|---|---|---|
| `general_manual18_subpixel-on` | general | manual 18 |
| `general_auto_subpixel-on` | general | auto (13.0) |
| `hcr_manual18_subpixel-on` | HCRv3 | manual 18 |
| `hcr_auto_subpixel-on` | HCRv3 | auto (13.0) |

Each folder holds the `.npz` output and the command used. The settings are those of the folder with the same name in `reference_v1/`.

Why they are here: subpixel fitting gives slightly different positions with the newer packages (scipy 1.18 in place of 1.7). Most spots move by less than a millionth of a pixel; 3–4 % move by more than 0.1 px, almost all of it in Z, and the largest change is 1.7 px. Spot counts, cluster membership and whole-pixel positions are unchanged. The tests compare the pipeline with these files exactly, and with `reference_v1/` within those limits. The numbers are in `docs/modularisation-streamlit-project/msp-devlog.md`, entry 1.5.
