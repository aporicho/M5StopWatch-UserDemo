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

    def test_correction_runtime_is_pinned_and_hash_verified(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "desktop" / "scripts" / "prepare-llama-runtime.mjs").read_text(
            encoding="utf-8"
        )
        build = (root / "macos" / "build-app.sh").read_text(encoding="utf-8")

        self.assertIn('const LLAMA_VERSION = "b9000"', script)
        self.assertIn('createHash("sha256")', script)
        self.assertIn("llama-b9000-bin-macos-arm64.tar.gz", script)
        self.assertIn('Contents/Resources/llama/llama-server', build)

    def test_correction_model_is_pinned_below_one_gigabyte(self):
        source = (
            Path(__file__).resolve().parents[1] / "ble_stt" / "correction_models.py"
        ).read_text(encoding="utf-8")

        self.assertIn("MAX_CORRECTION_MODEL_BYTES = 1_000_000_000", source)
        self.assertIn("DEFAULT_CORRECTION_REVISION", source)
        self.assertIn("DEFAULT_CORRECTION_SHA256", source)
        self.assertIn("correction model SHA-256 does not match", source)

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
        self.assertNotIn("tccutil reset", install)
        self.assertNotIn("ResetLaunchPad", install)
        self.assertNotIn("sqlite3", install)
        self.assertNotIn("lsregister", install)
        self.assertNotIn("killall Dock", install)
        self.assertIn('APP_TARGET="$USER_APP_TARGET"', install)
        self.assertIn('SHIM="$BIN_DIR/ble-stt"', install)
        self.assertIn('/bin/ln -sfn "$APP_EXEC" "$SHIM"', install)
        self.assertIn("BLE_STT_SKIP_LLAMA_RUNTIME=1 npm run build:mac:app", install)
        self.assertIn('"minimumSystemVersion": "15.0"', config)
        self.assertIn('"M5StopWatch.app", "Contents", "MacOS", "M5StopWatch"', sidecar)
        self.assertIn('"--noextattr", "--noqtn", sourceApp, targetApp', sidecar)

        public_install = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("doctor --request-permissions --wait-forever", public_install)
        self.assertIn("CFBundleExecutable", public_install)
        self.assertIn('macos_validate_app_structure "$MAC_APP"', public_install)
        self.assertIn('"$MAC_APP"/Contents/MacOS/*', public_install)
        self.assertNotIn('app_executable="$MAC_APP/Contents/MacOS/M5StopWatch"', public_install)

    def test_release_packages_outer_desktop_app_with_signed_nested_helper(self):
        workflow = (
            Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ble-stt-release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("npm run build:mac:app", workflow)
        self.assertIn("src-tauri/target/release/bundle/macos/M5StopWatch.app", workflow)
        self.assertIn("resources/ble-stt-helper/M5StopWatch.app", workflow)


if __name__ == "__main__":
    unittest.main()
