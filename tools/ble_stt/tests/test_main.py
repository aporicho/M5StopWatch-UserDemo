import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ble_stt.config import UserConfig
from ble_stt.main import (
    _create_configured_recognizer,
    _ensure_bluetooth_permission,
    _is_bluetooth_permission_error,
    apply_runtime_defaults,
)
from ble_stt.models import model_status


class RuntimeDefaultTests(unittest.TestCase):
    def test_reads_config_when_model_args_are_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "ble-stt.json")
            config.set("engine", "faster-whisper")
            config.set("model", "medium")
            args = SimpleNamespace(engine=None, model=None)

            apply_runtime_defaults(args, config)

        self.assertEqual(args.engine, "faster-whisper")
        self.assertEqual(args.model, "medium")

    def test_explicit_model_args_win_over_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "ble-stt.json")
            config.set("engine", "faster-whisper")
            config.set("model", "medium")
            args = SimpleNamespace(engine="mlx", model="small")

            apply_runtime_defaults(args, config)

        self.assertEqual(args.engine, "mlx")
        self.assertEqual(args.model, "small")

    def test_configured_recognizer_preserves_downloaded_source_for_local_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            snapshot = (
                cache
                / "models--mlx-community--whisper-small-mlx"
                / "snapshots"
                / "revision"
            )
            snapshot.mkdir(parents=True)
            (snapshot / "weights.npz").write_text("weights", encoding="utf-8")
            config = UserConfig(root / "ble-stt.json")
            config.set("engine", "auto")
            config.set("model", "small")
            args = SimpleNamespace(engine="auto", model="small", device="auto", cpu_threads=2)

            with (
                patch("ble_stt.models.model_cache_dir", return_value=cache),
                patch("ble_stt.models.resolve_engine", return_value="mlx"),
            ):
                with patch("ble_stt.main.create_recognizer", return_value=object()) as create:
                    _create_configured_recognizer(args, config)
                status = model_status(config, "auto", "small")

        self.assertEqual(Path(create.call_args.args[1]), snapshot)
        self.assertEqual(status.source, "downloaded")
        self.assertEqual(Path(status.resolved), snapshot)


class BluetoothPermissionTests(unittest.TestCase):
    def test_bluetooth_permission_passes_when_granted(self):
        adapter = SimpleNamespace(check_bluetooth_permission=lambda prompt=False: (True, "granted"))

        _ensure_bluetooth_permission(adapter)

    def test_bluetooth_permission_raises_clear_error(self):
        adapter = SimpleNamespace(
            check_bluetooth_permission=lambda prompt=False: (False, "macOS Bluetooth permission is denied")
        )

        with self.assertRaisesRegex(RuntimeError, "Bluetooth permission"):
            _ensure_bluetooth_permission(adapter)

    def test_background_bluetooth_check_never_requests_prompt(self):
        prompts = []

        def check(prompt=False):
            prompts.append(prompt)
            return False, "macOS Bluetooth permission has not been granted yet"

        adapter = SimpleNamespace(check_bluetooth_permission=check)

        with self.assertRaisesRegex(RuntimeError, "Bluetooth permission"):
            _ensure_bluetooth_permission(adapter)
        with self.assertRaisesRegex(RuntimeError, "Bluetooth permission"):
            _ensure_bluetooth_permission(adapter)

        self.assertEqual(prompts, [False, False])

    def test_detects_bluetooth_permission_errors(self):
        self.assertTrue(_is_bluetooth_permission_error(RuntimeError("macOS Bluetooth permission is denied")))
        self.assertTrue(_is_bluetooth_permission_error(RuntimeError("Bluetooth access is denied")))
        self.assertFalse(_is_bluetooth_permission_error(RuntimeError("M5StopWatch HID was not found")))


if __name__ == "__main__":
    unittest.main()
