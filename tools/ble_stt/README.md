# M5StopWatch BLE STT

The BLE Remote watch app streams push-to-talk audio to a local, login-time
service. Stable transcript fragments are inserted into the window that was
focused when recording began. Audio and recognition stay on the computer.

| Platform | Bluetooth | Text input | Recognition | Login service |
| --- | --- | --- | --- | --- |
| Linux/Hyprland | BlueZ/Bleak | `hyprctl` + `wtype` | faster-whisper | systemd user service |
| Apple Silicon macOS | CoreBluetooth/Bleak | Accessibility + Quartz | MLX Whisper | LaunchAgent |
| Windows 11 | WinRT/Bleak | `GetForegroundWindow` + `SendInput` | faster-whisper | Scheduled Task |

## Install once

macOS or Linux:

```bash
curl -fsSL https://github.com/aporicho/M5StopWatch-UserDemo/releases/latest/download/ble-stt-install.sh | sh
```

Windows PowerShell:

```powershell
irm https://github.com/aporicho/M5StopWatch-UserDemo/releases/latest/download/ble-stt-install.ps1 | iex
```

The installer downloads the latest stable Release, verifies its SHA-256,
creates an isolated user installation, installs the current platform backend,
downloads and exercises the `medium` model, checks permissions, guides pairing,
and asks for one real push-to-talk test. Only then does it register the login
service. Administrator access is not required unless the computer is missing a
system package such as Python, BlueZ, or `wtype`.

The model download is large. Its progress is shown during installation so the
first daily use never waits for a hidden download. Interrupted installs may be
rerun safely; model caches and completed downloads are reused.

For unattended setup, set `BLE_STT_SKIP_TEST=1`. `BLE_STT_MODEL=small` selects a
smaller model, `BLE_STT_VERSION=ble-stt-v0.3.0` pins a Release tag, and
`BLE_STT_ASSET_BASE` selects a trusted internal Release mirror.

## Pair and verify

Keep **BLE Remote** open on the watch during installation.

- macOS pairs when CoreBluetooth first connects. Accept the Bluetooth prompt
  and grant the displayed Python executable access in **System Settings →
  Privacy & Security → Accessibility**.
- Windows and Linux use the operating system's Bluetooth pairing flow. Select
  `M5StopWatch HID` and enter `123456` when requested.

For the final test, focus an empty text document, hold the right watch button,
speak, and release. The watch progresses through `Preparing speech model`,
`Speech input ready`, `Listening`, and `Recognizing`. A short right-button press
still sends Enter; releasing after speech never submits the recognized text.

## Daily management

The service starts automatically at login. The bare command gives a short
health summary:

```bash
ble-stt
ble-stt status
```

Maintenance commands are consistent on all three platforms:

```bash
ble-stt doctor --request-permissions
ble-stt doctor --ble
ble-stt test
ble-stt logs -n 100
ble-stt logs --follow
ble-stt restart
ble-stt upgrade
ble-stt uninstall
ble-stt uninstall --purge-models
```

Uninstall preserves the downloaded model by default so reinstalling is fast;
`--purge-models` removes it as well.

Foreground and development use remains available under `run`:

```bash
ble-stt run --engine auto --model medium
ble-stt run --engine faster-whisper --device cpu --model small
```

Old invocations such as `ble-stt --model small` are routed to `run` for
compatibility. Device identifiers are cached automatically; `--device-id` (and
the legacy `--address` alias) are only for troubleshooting.

Logs live in `~/.local/state/m5stopwatch` on Linux,
`~/Library/Logs/M5StopWatch` on macOS, and `%LOCALAPPDATA%\M5StopWatch\Logs` on
Windows. If the bond exposes only the old HID service, choose **Forget
computer** on the watch, remove it from the operating system, and pair again.

## Local development

Running the checked-in installer directly uses this checkout instead of a
Release asset:

```bash
./tools/ble_stt/install.sh
```

On Windows:

```powershell
tools\ble_stt\install.ps1
```

Tests do not download models:

```bash
PYTHONPATH=tools/ble_stt python -m unittest discover -s tools/ble_stt/tests -v
```
