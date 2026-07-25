from pathlib import Path
import unittest


class MacOSPackagingTests(unittest.TestCase):
    def test_agent_app_can_present_privacy_prompts(self):
        spec = Path(__file__).resolve().parents[1] / "macos" / "M5StopWatch.spec"
        value = spec.read_text(encoding="utf-8")

        self.assertIn('"LSUIElement": True', value)
        self.assertIn('"LSBackgroundOnly": False', value)
        self.assertIn("com.aporicho.m5stopwatch-ble-stt-helper", value)
        self.assertIn("NSBluetoothAlwaysUsageDescription", value)
        self.assertIn('"AppKit"', value)

    def test_development_signing_has_stable_requirement(self):
        script = Path(__file__).resolve().parents[1] / "macos" / "build-app.sh"
        value = script.read_text(encoding="utf-8")

        self.assertIn('HELPER_BUNDLE_ID="com.aporicho.m5stopwatch-ble-stt-helper"', value)
        self.assertIn("--identifier \"$HELPER_BUNDLE_ID\"", value)
        self.assertIn("=designated => identifier \\\"$HELPER_BUNDLE_ID\\\"", value)

    def test_desktop_control_uses_single_product_identity(self):
        root = Path(__file__).resolve().parents[1] / "desktop"
        service = (Path(__file__).resolve().parents[1] / "ble_stt" / "service.py").read_text(encoding="utf-8")
        config = (root / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
        plist = (root / "src-tauri" / "Info.plist").read_text(encoding="utf-8")
        install = (root / "scripts" / "install-macos.sh").read_text(encoding="utf-8")
        sidecar = (root / "scripts" / "prepare-sidecar.mjs").read_text(encoding="utf-8")

        self.assertIn('"productName": "M5StopWatch"', config)
        self.assertIn('"identifier": "com.aporicho.m5stopwatch-ble-stt"', config)
        self.assertIn("NSBluetoothAlwaysUsageDescription", plist)
        self.assertIn('APP_NAME="M5StopWatch.app"', install)
        self.assertIn('HELPER_ID="com.aporicho.m5stopwatch-ble-stt-helper"', install)
        self.assertIn('HELPER_SOURCE_APP="$BLE_STT_ROOT/dist-macos/M5StopWatch.app"', install)
        self.assertIn('ditto --noextattr --noqtn "$HELPER_SOURCE_APP" "$HELPER_APP"', install)
        self.assertIn("Helper Python.framework symlink was not preserved", install)
        self.assertIn("BLE_STT_SERVICE_HELPER", service)
        self.assertIn("BLE_STT_SERVICE_RUNNER", service)
        self.assertIn("main app service runner", install)
        self.assertIn("<string>service-run</string>", install)
        self.assertIn("com.aporicho.m5stopwatch-control", install)
        self.assertIn('tccutil reset Bluetooth "$HELPER_ID"', install)
        self.assertNotIn('tccutil reset Bluetooth "$APP_BUNDLE_ID"', install)
        self.assertIn('"M5StopWatch.app", "Contents", "MacOS", "M5StopWatch"', sidecar)
        self.assertIn('"--noextattr", "--noqtn", sourceApp, targetApp', sidecar)


if __name__ == "__main__":
    unittest.main()
