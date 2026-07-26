import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ble_stt.status import collect_status, latest_log_line, snapshot_to_dict, status_lines
from ble_stt.telemetry import make_telemetry, write_telemetry


class FakeConfig:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeManager:
    def __init__(self, installed=True, active=True):
        self.installed = installed
        self.active = active

    def is_installed(self):
        return self.installed

    def is_active(self):
        return self.active


class BrokenManager:
    def is_installed(self):
        raise RuntimeError("launchctl failed")

    def is_active(self):
        return False


class FakePlatform:
    def __init__(self, input_result=(True, "allowed"), bluetooth_result=(True, "allowed")):
        self.input_result = input_result
        self.bluetooth_result = bluetooth_result

    def check_input_permission(self, prompt):
        return self.input_result

    def check_bluetooth_permission(self, prompt):
        return self.bluetooth_result


class StatusTests(unittest.TestCase):
    def test_collects_ready_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_snapshot = root / "cache" / "hub" / "models--Systran--faster-whisper-small" / "snapshots" / "revision"
            model_snapshot.mkdir(parents=True)
            (model_snapshot / "model.bin").write_text("weights", encoding="utf-8")
            event_log = root / "ble-stt-events.log"
            event_log.write_text(
                "old\n"
                "2026-07-25 20:00:00.000 DEBUG [123:MainThread] ble_stt.runtime: "
                "host status sent status=READY error=0\n",
                encoding="utf-8",
            )
            with patch("ble_stt.models.model_cache_dir", return_value=root / "cache"):
                snapshot = collect_status(
                    manager=FakeManager(installed=True, active=True),
                    config=FakeConfig(
                        {
                            "device_id": "watch-123",
                            "engine": "faster-whisper",
                            "model": "small",
                            "prepared_model": "small",
                        }
                    ),
                    platform_adapter=FakePlatform(),
                    log_directory=root,
                    log_paths=(event_log,),
                )

        self.assertTrue(snapshot.ready_for_voice)
        self.assertEqual(snapshot.watch_id, "watch-123")
        self.assertEqual(snapshot.engine, "faster-whisper")
        self.assertEqual(snapshot.model, "small")
        self.assertIn("host status sent status=READY", snapshot.latest_event)
        self.assertTrue(all(line.ok for line in status_lines(snapshot)))

    def test_permission_gap_keeps_voice_not_ready(self):
        snapshot = collect_status(
            manager=FakeManager(installed=True, active=True),
            config=FakeConfig({"device_id": "watch-123", "engine": "faster-whisper", "model": "small"}),
            platform_adapter=FakePlatform(input_result=(False, "enable Accessibility")),
            log_directory=Path("/tmp/logs"),
            log_paths=(Path("/tmp/missing.log"),),
        )

        lines = {line.label: line for line in status_lines(snapshot)}
        self.assertFalse(snapshot.ready_for_voice)
        self.assertFalse(lines["text input"].ok)
        self.assertEqual(lines["text input"].detail, "enable Accessibility")

    def test_runtime_log_gap_keeps_voice_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_log = root / "ble-stt-events.log"
            event_log.write_text(
                "2026-07-25 20:00:00.000 WARNING [123:MainThread] ble_stt.runtime: "
                "Bluetooth permission not ready: macOS Bluetooth permission has not been granted yet\n",
                encoding="utf-8",
            )
            snapshot = collect_status(
                manager=FakeManager(installed=True, active=True),
                config=FakeConfig(
                    {
                        "device_id": "watch-123",
                        "engine": "faster-whisper",
                        "model": "small",
                        "prepared_model": "small",
                    }
                ),
                platform_adapter=FakePlatform(),
                log_directory=root,
                log_paths=(event_log,),
            )

        lines = {line.label: line for line in status_lines(snapshot)}
        self.assertFalse(snapshot.ready_for_voice)
        self.assertFalse(lines["voice service"].ok)
        self.assertEqual(lines["voice service"].detail, "Bluetooth permission is not granted to the service")

    def test_snapshot_dict_exposes_ui_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_log = root / "ble-stt-events.log"
            event_log.write_text(
                "2026-07-25 20:00:00.000 INFO [123:MainThread] ble_stt.runtime: "
                "connected mtu=185 services=[]\n",
                encoding="utf-8",
            )
            snapshot = collect_status(
                manager=FakeManager(installed=True, active=True),
                config=FakeConfig(
                    {
                        "device_id": "watch-123",
                        "engine": "auto",
                        "model": "medium",
                        "prepared_model": "mlx-community/whisper-medium-mlx",
                    }
                ),
                platform_adapter=FakePlatform(),
                log_directory=root,
                log_paths=(event_log,),
            )

        payload = snapshot_to_dict(snapshot)

        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["overall"]["code"], "watch_connected")
        self.assertEqual(payload["overall"]["label"], "Watch connected")
        self.assertEqual(payload["watch"]["id"], "watch-123")
        self.assertFalse(payload["voice"]["ready"])

    def test_fresh_runtime_telemetry_overrides_unrelated_latest_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_snapshot = root / "cache" / "hub" / "models--Systran--faster-whisper-small" / "snapshots" / "revision"
            model_snapshot.mkdir(parents=True)
            (model_snapshot / "model.bin").write_text("weights", encoding="utf-8")
            event_log = root / "ble-stt-events.log"
            event_log.write_text(
                "2026-07-25 20:00:00.000 INFO [123:MainThread] ble_stt.runtime: "
                "watch event event=touch.scroll_delta action=hid.mouse.wheel handled=True value=1 sequence=31\n",
                encoding="utf-8",
            )
            write_telemetry(make_telemetry(stage="ready", session_id=10), root / "ble-stt-runtime.json")
            with patch("ble_stt.models.model_cache_dir", return_value=root / "cache"):
                snapshot = collect_status(
                    manager=FakeManager(installed=True, active=True),
                    config=FakeConfig(
                        {
                            "device_id": "watch-123",
                            "engine": "faster-whisper",
                            "model": "small",
                            "prepared_model": "small",
                        }
                    ),
                    platform_adapter=FakePlatform(),
                    log_directory=root,
                    log_paths=(event_log,),
                )

        payload = snapshot_to_dict(snapshot)

        self.assertTrue(snapshot.ready_for_voice)
        self.assertEqual(payload["overall"]["code"], "voice_ready")
        self.assertTrue(payload["voice"]["ready"])
        self.assertEqual(payload["voice"]["message"], "ready")

    def test_service_error_is_reported_as_failed_service_line(self):
        snapshot = collect_status(
            manager=BrokenManager(),
            config=FakeConfig({"engine": "faster-whisper", "model": "small"}),
            platform_adapter=FakePlatform(),
            log_directory=Path("/tmp/logs"),
            log_paths=(Path("/tmp/missing.log"),),
        )

        service_line = status_lines(snapshot)[0]
        self.assertFalse(snapshot.ready_for_voice)
        self.assertFalse(service_line.ok)
        self.assertEqual(service_line.detail, "launchctl failed")

    def test_missing_model_blocks_voice_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_log = root / "ble-stt-events.log"
            event_log.write_text(
                "2026-07-25 20:00:00.000 DEBUG [123:MainThread] ble_stt.runtime: "
                "host status sent status=READY error=0\n",
                encoding="utf-8",
            )
            snapshot = collect_status(
                manager=FakeManager(installed=True, active=True),
                config=FakeConfig({"device_id": "watch-123", "engine": "faster-whisper", "model": "medium"}),
                platform_adapter=FakePlatform(),
                log_directory=root,
                log_paths=(event_log,),
            )

        payload = snapshot_to_dict(snapshot)

        self.assertFalse(snapshot.ready_for_voice)
        self.assertEqual(payload["overall"]["code"], "model_missing")
        self.assertFalse(payload["model"]["installed"])

    def test_latest_log_line_skips_missing_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty.log"
            empty.write_text("\n\n", encoding="utf-8")
            log = root / "events.log"
            log.write_text("first\n\nsecond\n", encoding="utf-8")
            self.assertEqual(latest_log_line((root / "missing.log", empty, log)), "second")


if __name__ == "__main__":
    unittest.main()
