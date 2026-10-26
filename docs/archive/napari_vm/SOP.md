# SOP: Browser Napari + OMERO Image ID + napari-bigfish (POC)

## Audience
Lab users running spot detection from a browser-hosted napari session.

## Operations Reference
For service lifecycle, browser URL, reboot behavior, and connection handling, see `omero/napari_vm/OPERATIONAL_NOTES.md`.

## Preconditions
- You can reach `https://<vm-host>/napari/` from university network or VPN.
- You have valid OMERO credentials.
- Target image ID is known.

## Shared VM Coexistence (Shiny + Streamlit)
- Napari VNC service uses isolated localhost ports and does not bind externally.
- Napari service runs with reduced scheduler priority (`Nice=10`) and CPU quota limits.
- Default VNC session mode is `minimal` (xterm only) to reduce background memory/CPU.
- To switch to a richer desktop session temporarily, set `PREFERRED_SESSION=gnome` in the user service and restart.
- Avoid running large Napari analyses during peak Shiny/Streamlit usage windows.
- Stop Napari service when not in use:

```bash
systemctl --user stop napari-vnc.service
```

- Start Napari service when needed:

```bash
systemctl --user start napari-vnc.service
```

## Workflow
1. Open `https://<vm-host>/napari/`.
2. In the streamed desktop, start `Napari + OMERO ID prompt`.
3. Enter image ID as `12345` or `Image:12345`.
4. Enter OMERO username/password when prompted.
5. Wait for image layer to load.
6. Verify scale metadata before analysis.
7. Open napari-bigfish widget and run spot detection with baseline parameters.
8. Confirm a `Points` layer was generated.
9. Export result layer and/or screenshot.

## Scale Check (Mandatory)
Before running napari-bigfish:
- Open layer properties and confirm XY(Z) scale in nm/px (or calibrated unit).
- If missing, set scale manually according to acquisition metadata.
- Do not interpret counts from uncalibrated scale.

## Export Guidance
- Save a screenshot for QC.
- Export points/layers using napari export actions.
- Record image ID, parameters, and date in your analysis log.

## Troubleshooting

### Invalid image ID
- Symptom: napari reports missing object or launcher returns failure.
- Action: verify numeric ID exists and that you have permissions.

### Authentication failure
- Symptom: login denied or repeated auth prompts.
- Action: retry credentials, then verify OMERO account status.

### OMERO unreachable
- Symptom: launcher fails preflight connectivity check to `10.34.168.89:4064`.
- Action: connect to VPN, confirm firewall policy, retry.

### Missing scale metadata
- Symptom: uncertain scale fields in napari.
- Action: stop analysis and set scale manually from microscope metadata.

### Large image performance or memory issues
- Symptom: slow load, lag, or process termination.
- Action: use ROI/crop-first workflow and single channel when possible.

## Session Lifecycle
- Closing the browser does not always terminate the backend VNC session.
- Manual cleanup command if needed:

```bash
vncserver -kill :21
```

## Performance Baseline Template
Use this table during POC validation.

| Date | Image ID | Load Time (s) | Spot Run Time (s) | Peak Memory | Notes |
| --- | --- | --- | --- | --- | --- |
| YYYY-MM-DD | Image: |  |  |  |  |
