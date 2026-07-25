import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ble_stt.config import UserConfig
from ble_stt.main import (
    _clear_cached_device_after_timeout,
    _ensure_bluetooth_permission,
    _is_bluetooth_permission_error,
    _is_device_unavailable,
    _is_pairing_removed_error,
)


class ClearCachedDeviceAfterTimeoutTests(unittest.TestCase):
    def test_clears_auto_cached_device(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "ble-stt.json")
            config.set("device_id", "stale-device")
            adapter = SimpleNamespace(config=config)

            cleared = _clear_cached_device_after_timeout(adapter, None)

        self.assertEqual(cleared, "stale-device")
        self.assertEqual(config.get("device_id"), "")

    def test_keeps_explicit_device_id(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "ble-stt.json")
            config.set("device_id", "saved-device")
            adapter = SimpleNamespace(config=config)

            cleared = _clear_cached_device_after_timeout(adapter, "manual-device")

        self.assertIsNone(cleared)
        self.assertEqual(config.get("device_id"), "saved-device")

    def test_ignores_missing_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "ble-stt.json")
            adapter = SimpleNamespace(config=config)

            cleared = _clear_cached_device_after_timeout(adapter, None)

        self.assertIsNone(cleared)
        self.assertIsNone(config.get("device_id"))


class DeviceUnavailableClassificationTests(unittest.TestCase):
    def test_detects_missing_ble_device_message(self):
        exc = RuntimeError("M5StopWatch HID was not found; reopen BLE Remote")

        self.assertTrue(_is_device_unavailable(exc))

    def test_keeps_other_runtime_errors_strict(self):
        exc = RuntimeError("Speech GATT service is missing")

        self.assertFalse(_is_device_unavailable(exc))

    def test_detects_stale_pairing_errors(self):
        self.assertTrue(
            _is_pairing_removed_error(
                RuntimeError('failed to connect: Error Domain=CBErrorDomain Code=14 "Peer removed pairing information"')
            )
        )
        self.assertTrue(_is_pairing_removed_error(RuntimeError("CBErrorDomain Code=14")))
        self.assertFalse(_is_pairing_removed_error(RuntimeError("M5StopWatch HID was not found")))


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

    def test_bluetooth_permission_requests_prompt_once(self):
        prompts = []

        def check(prompt=False):
            prompts.append(prompt)
            return False, "macOS Bluetooth permission has not been granted yet"

        adapter = SimpleNamespace(check_bluetooth_permission=check)

        with self.assertRaisesRegex(RuntimeError, "Bluetooth permission"):
            _ensure_bluetooth_permission(adapter)
        with self.assertRaisesRegex(RuntimeError, "Bluetooth permission"):
            _ensure_bluetooth_permission(adapter)

        self.assertEqual(prompts, [False, True, False])

    def test_detects_bluetooth_permission_errors(self):
        self.assertTrue(_is_bluetooth_permission_error(RuntimeError("macOS Bluetooth permission is denied")))
        self.assertTrue(_is_bluetooth_permission_error(RuntimeError("Bluetooth access is denied")))
        self.assertFalse(_is_bluetooth_permission_error(RuntimeError("M5StopWatch HID was not found")))


if __name__ == "__main__":
    unittest.main()
