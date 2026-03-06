# Operational Notes: Napari noVNC Service

## Browser Access
- Primary URL for this VM: `https://shinytest.mvls.gla.ac.uk/napari/`
- Generic pattern: `https://<vm-host>/napari/`
- Explicit English UI URL (optional): `https://shinytest.mvls.gla.ac.uk/napari/vnc.html?path=websockify&lang=en`

## What You Should See
- noVNC streams a Linux desktop session, not a native web Napari page.
- You may briefly see an `xterm` window first.
- Napari is configured to auto-start and should appear after a few seconds.
- If Napari does not appear, run in the visible terminal:

```bash
~/Github/bigfish-pypeline/omero/napari_vm/launch-napari.sh
```

- For direct OMERO image-ID workflow, run:

```bash
~/Github/bigfish-pypeline/omero/napari_vm/launch-napari-omero.sh
```

## Service Quick Commands
Run as the service owner user (`jeff`) in a shell on the VM.

```bash
systemctl --user status napari-vnc.service
systemctl --user start napari-vnc.service
systemctl --user stop napari-vnc.service
systemctl --user restart napari-vnc.service
```

## Keep Napari Available After VM Reboot
To keep the user service available after VM restart (without requiring an interactive SSH/login first):

```bash
sudo loginctl enable-linger jeff
systemctl --user enable napari-vnc.service
```

Verify:

```bash
loginctl show-user jeff -p Linger
systemctl --user is-enabled napari-vnc.service
```

Expected:
- `Linger=yes`
- service enabled

## Connection Behavior (When Browser Closes)
- Closing the browser tab/window closes that WebSocket client connection.
- Service is configured with `WEBSOCKIFY_HEARTBEAT=30` to detect stale/broken browser sessions quickly.
- This cleans up inactive browser connections while keeping the service available for the next user.

## Resource-Saving Modes

### Mode A: Continuous Availability (current default)
- `WEBSOCKIFY_IDLE_TIMEOUT=0`
- Service stays online continuously.
- Best when users need immediate access at any time.

### Mode B: Auto-stop when idle (optional)
If you want the service to stop after no active browser users:

1. Edit the user service file:
```bash
nano ~/.config/systemd/user/napari-vnc.service
```

2. Set:
```ini
Environment=WEBSOCKIFY_IDLE_TIMEOUT=900
```
(Example: stop after 15 minutes with no connected browser clients.)

3. Reload and restart:
```bash
systemctl --user daemon-reload
systemctl --user restart napari-vnc.service
```

Note:
- In Mode B, when idle timeout is reached the service exits and will need to be started again.
- If you need both always-on access and strict idle stop, use external orchestration (for example, a portal button or scheduled health/start job).

## Existing Shared-VM Isolation
- noVNC listener: `127.0.0.1:16080`
- VNC listener: `127.0.0.1:5921` (display `:21`)
- Shiny remains on `:3838`
- Streamlit remains on `:8501`

## Troubleshooting
- Check service logs:
```bash
journalctl --user -u napari-vnc.service -n 200 --no-pager
```

- Confirm listeners:
```bash
ss -ltn | egrep '(:16080|:5921|:3838|:8501)'
```

- If noVNC shows `Connecting...` then fails:
```bash
curl --http1.1 -k -i https://127.0.0.1/websockify -H 'Host: shinytest.mvls.gla.ac.uk' -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==' | head
```
Expected: `HTTP/1.1 101 Switching Protocols`.

- If text appears in Korean (or another language):
  noVNC follows browser locale by default. This is not a VM fault.
  Use `?lang=en` in the URL or change browser preferred language.
