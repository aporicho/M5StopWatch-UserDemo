# M5StopWatch-UserDemo
M5Stack StopWatch user demo for hardware evaluation.

## Build

### Fetch Dependencies

```bash
python3 ./fetch_repos.py
```

### Tool Chains

[ESP-IDF v5.5.4](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/index.html)

### Build

```bash
idf.py build
```

### Flash

```bash
idf.py flash
```

## BLE speech input helper

The BLE Remote app can stream push-to-talk audio to a local login service on
Linux/Hyprland, Apple Silicon macOS, or Windows 11. Installation is one command:

```bash
curl -fsSL https://github.com/aporicho/M5StopWatch-UserDemo/releases/latest/download/ble-stt-install.sh | sh
```

See [tools/ble_stt/README.md](tools/ble_stt/README.md) for the Windows command,
pairing flow, management commands, and development setup.
