# M5StopWatch BLE STT helper

This Linux/Hyprland helper receives push-to-talk audio from the **BLE Remote** app,
runs `faster-whisper` locally, and types stable transcript segments into the
window that was focused when recording started. Recognized Chinese is
normalized to Simplified Chinese and Mainland terminology with OpenCC before
it is typed.

## Install

Requirements: BlueZ, `bluetoothctl`, `wtype`, Python 3.10+, and a paired
`M5StopWatch HID` device.

```bash
cd tools/ble_stt
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

The default multilingual Medium model is downloaded on first launch. After the
download, recognition is fully offline.

For NVIDIA GPU inference on Linux, install the CUDA 12 runtime wheels inside
the virtual environment. `run-service.sh` automatically exposes their library
directories to CTranslate2 when the background service starts.

```bash
.venv/bin/python -m pip install nvidia-cublas-cu12 'nvidia-cudnn-cu12==9.*'
```

## Run

Open **BLE Remote** on the watch, then run:

```bash
source tools/ble_stt/.venv/bin/activate
ble-stt
```

Wait for `speech input ready`, focus a text field, hold the right watch button
for 500 ms, speak, and release it. A short right-button press still sends Enter.
The release does not automatically submit the recognized text.

## Background service

The repository includes a user service at
`systemd/m5stopwatch-ble-stt.service`. Once linked and enabled, it starts at
login and reconnects to the watch automatically.

```bash
systemctl --user status m5stopwatch-ble-stt.service
journalctl --user -u m5stopwatch-ble-stt.service -f
systemctl --user restart m5stopwatch-ble-stt.service
```

To stop it temporarily, run `systemctl --user stop
m5stopwatch-ble-stt.service`. To remove it from login startup, run `systemctl
--user disable m5stopwatch-ble-stt.service`.

Useful overrides:

```bash
ble-stt --device cpu
ble-stt --device cuda
ble-stt --model small
ble-stt --address AA:BB:CC:DD:EE:FF
```

To verify the BLE service without loading or downloading a speech model:

```bash
python -m ble_stt.check
```

If the existing bond still exposes only the old HID service, use **Forget
computer** in the app, remove the device with `bluetoothctl remove ADDRESS`, and
pair it again with PIN `123456`.

## Tests

```bash
cd tools/ble_stt
PYTHONPATH=. python -m unittest discover -s tests -v
```
