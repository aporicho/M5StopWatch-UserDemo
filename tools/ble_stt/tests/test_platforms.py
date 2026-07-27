import asyncio
import os
import plistlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

from ble_stt.config import UserConfig, config_dir, install_dir, model_cache_dir
from ble_stt.platforms import create_platform
from ble_stt.platforms.linux import LinuxPlatform, LinuxTextInjector
from ble_stt.platforms.macos import MacOSPlatform, MacOSTextInjector, MacWindowToken
from ble_stt.platforms.windows import WindowsTextInjector
from ble_stt.protocol import SERVICE_UUID
from ble_stt.recognizers import MlxWhisperRecognizer, create_recognizer, resolve_engine, resolve_model
from ble_stt.service import (
    SERVICE_LABEL,
    render_launch_agent,
    render_systemd_unit,
    service_arguments,
    windows_task_action,
)


class ConfigTests(unittest.TestCase):
    def test_platform_config_paths(self):
        self.assertTrue(
            config_dir("darwin").as_posix().endswith("Library/Application Support/M5StopWatch")
        )
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/test/AppData/Local"}):
            self.assertEqual(config_dir("win32"), Path("C:/Users/test/AppData/Local/M5StopWatch"))
            self.assertEqual(
                install_dir("win32"), Path("C:/Users/test/AppData/Local/M5StopWatch/ble-stt")
            )
        self.assertTrue(install_dir("darwin").as_posix().endswith("M5StopWatch/ble-stt"))
        self.assertTrue(model_cache_dir("darwin").as_posix().endswith("Caches/M5StopWatch/ble-stt"))

    def test_device_identifier_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            UserConfig(path).set("device_id", "device-123")
            self.assertEqual(UserConfig(path).get("device_id"), "device-123")


class RecognizerSelectionTests(unittest.TestCase):
    def test_auto_engine(self):
        self.assertEqual(resolve_engine("auto", "darwin", "arm64"), "mlx")
        self.assertEqual(resolve_engine("auto", "linux", "x86_64"), "faster-whisper")
        self.assertEqual(resolve_engine("auto", "win32", "AMD64"), "faster-whisper")

    def test_mlx_model_mapping(self):
        self.assertEqual(resolve_model("mlx", "medium"), "mlx-community/whisper-medium-mlx")
        self.assertEqual(resolve_model("mlx", "large"), "mlx-community/whisper-large-v3-mlx")
        self.assertEqual(resolve_model("mlx", "organization/custom-model"), "organization/custom-model")
        self.assertEqual(resolve_model("faster-whisper", "medium"), "medium")
        self.assertEqual(resolve_model("faster-whisper", "large"), "large-v3")

    def test_mlx_uses_greedy_decoder(self):
        module = Mock()
        module.transcribe.return_value = {"segments": []}
        numpy = Mock()
        numpy.float32 = "float32"
        numpy.asarray.return_value = MagicMock()
        recognizer = MlxWhisperRecognizer.__new__(MlxWhisperRecognizer)
        recognizer.module = module
        recognizer.model_name = "mlx-community/whisper-small-mlx"
        recognizer.simplifier = Mock()

        with patch.dict(sys.modules, {"numpy": numpy}):
            recognizer.transcribe([0] * 320)

        options = module.transcribe.call_args.kwargs
        self.assertNotIn("beam_size", options)
        self.assertEqual(options["temperature"], 0.0)

    def test_mlx_loads_model_before_reporting_ready(self):
        mlx_package = types.ModuleType("mlx")
        mlx_core = types.ModuleType("mlx.core")
        mlx_core.float16 = object()
        mlx_package.core = mlx_core
        mlx_whisper = types.ModuleType("mlx_whisper")
        holder = Mock()
        transcribe_module = Mock(ModelHolder=holder)

        with patch("ble_stt.recognizers._SimplifyingRecognizer.__init__", return_value=None):
            with patch("ble_stt.recognizers.sys.platform", "darwin"):
                with patch("ble_stt.recognizers.platform.machine", return_value="arm64"):
                    with patch("ble_stt.recognizers.importlib.import_module", return_value=transcribe_module):
                        with patch.dict(
                            sys.modules,
                            {"mlx": mlx_package, "mlx.core": mlx_core, "mlx_whisper": mlx_whisper},
                        ):
                            recognizer = MlxWhisperRecognizer("small")

        holder.get_model.assert_called_once_with(recognizer.model_name, mlx_core.float16)

    @patch("ble_stt.recognizers.model_cache_dir", return_value=Path("/tmp/ble-stt-test/model-cache"))
    @patch("ble_stt.recognizers.FasterWhisperRecognizer")
    def test_recognizer_uses_private_model_cache(self, recognizer: Mock, cache_dir: Mock):
        with patch.dict(os.environ, {}, clear=True):
            create_recognizer("faster-whisper", "small", "cpu", 2)
            self.assertEqual(os.environ["HF_HOME"], str(cache_dir.return_value))
        recognizer.assert_called_once_with("small", "cpu", 2)


class PlatformFactoryTests(unittest.TestCase):
    def test_platform_factory(self):
        self.assertEqual(create_platform("linux").name, "linux")
        self.assertEqual(create_platform("darwin").name, "macos")
        self.assertEqual(create_platform("win32").name, "windows")
        with self.assertRaises(RuntimeError):
            create_platform("plan9")


class LinuxInjectorTests(unittest.TestCase):
    @patch("ble_stt.platforms.linux.subprocess.run")
    def test_focus_guard_and_input(self, run: Mock):
        run.return_value = Mock(stdout='{"address":"0xabc"}')
        injector = LinuxTextInjector()
        self.assertFalse(injector.type_text("hello", "0xdef"))
        self.assertEqual(run.call_count, 1)

        self.assertTrue(injector.type_text("hello", "0xabc"))
        self.assertEqual(run.call_args_list[-1].args[0], ["wtype", "--", "hello"])


class LinuxConnectedDeviceTests(unittest.TestCase):
    def test_returns_only_a_system_connected_paired_device(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            config.set("device_id", "AA:BB:CC:DD:EE:FF")
            platform = LinuxPlatform(config)
            info = "Device AA:BB:CC:DD:EE:FF\n\tPaired: yes\n\tConnected: yes\n"
            with patch("ble_stt.platforms.linux.shutil.which", return_value="/usr/bin/bluetoothctl"):
                with patch("ble_stt.platforms.linux.subprocess.run", return_value=Mock(stdout=info)) as run:
                    device = asyncio.run(platform.find_connected_device(None))

        self.assertEqual(device, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(run.call_args.args[0], ["bluetoothctl", "info", "AA:BB:CC:DD:EE:FF"])
        self.assertNotIn("connect", run.call_args.args[0])
        self.assertNotIn("remove", run.call_args.args[0])

    def test_disconnected_device_is_never_returned_to_bleak(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            config.set("device_id", "AA:BB:CC:DD:EE:FF")
            platform = LinuxPlatform(config)
            info = "Device AA:BB:CC:DD:EE:FF\n\tPaired: yes\n\tConnected: no\n"
            with patch("ble_stt.platforms.linux.shutil.which", return_value="/usr/bin/bluetoothctl"):
                with patch("ble_stt.platforms.linux.subprocess.run", return_value=Mock(stdout=info)):
                    self.assertIsNone(asyncio.run(platform.find_connected_device(None)))

    def test_stale_cached_peer_does_not_hide_new_system_connected_peer(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            config.set("device_id", "AA:AA:AA:AA:AA:AA")
            platform = LinuxPlatform(config)
            paired = Mock(
                stdout=(
                    "Device AA:AA:AA:AA:AA:AA M5StopWatch HID\n"
                    "Device BB:BB:BB:BB:BB:BB M5StopWatch HID\n"
                )
            )
            stale = Mock(stdout="Device AA:AA:AA:AA:AA:AA\n\tPaired: yes\n\tConnected: no\n")
            connected = Mock(stdout="Device BB:BB:BB:BB:BB:BB\n\tPaired: yes\n\tConnected: yes\n")
            with patch("ble_stt.platforms.linux.shutil.which", return_value="/usr/bin/bluetoothctl"):
                with patch(
                    "ble_stt.platforms.linux.subprocess.run",
                    side_effect=[paired, stale, connected],
                ) as run:
                    device = asyncio.run(platform.find_connected_device(None))

        self.assertEqual(device, "BB:BB:BB:BB:BB:BB")
        self.assertEqual(config.get("device_id"), "BB:BB:BB:BB:BB:BB")
        self.assertEqual(
            [item.args[0] for item in run.call_args_list],
            [
                ["bluetoothctl", "devices", "Paired"],
                ["bluetoothctl", "info", "AA:AA:AA:AA:AA:AA"],
                ["bluetoothctl", "info", "BB:BB:BB:BB:BB:BB"],
            ],
        )


class FakeQuartz:
    kCGEventSourceStateCombinedSessionState = 0
    kCGHIDEventTap = 0

    def __init__(self):
        self.posts = []
        self.permission_requests = 0

    def CGPreflightPostEventAccess(self):
        return True

    def CGRequestPostEventAccess(self):
        self.permission_requests += 1
        return True

    def CGEventSourceCreate(self, state):
        return "source"

    def CGEventCreateKeyboardEvent(self, source, key, down):
        return {"down": down}

    def CGEventKeyboardSetUnicodeString(self, event, length, text):
        event["text"] = text

    def CGEventPost(self, tap, event):
        self.posts.append(event)


class FakeApplication:
    def __init__(self, pid):
        self.pid = pid

    def processIdentifier(self):
        return self.pid


class FakeWorkspace:
    pid = 42

    @classmethod
    def sharedWorkspace(cls):
        return cls()

    def frontmostApplication(self):
        return FakeApplication(self.pid)


class FakeAppKit:
    NSWorkspace = FakeWorkspace


class MacInjectorTests(unittest.TestCase):
    def test_accessibility_requests_only_post_event_access(self):
        quartz = FakeQuartz()
        injector = MacOSTextInjector(quartz, FakeAppKit)

        self.assertTrue(injector.check_accessibility(True))
        self.assertEqual(quartz.permission_requests, 1)

    def test_permission_error_identifies_python(self):
        adapter = MacOSPlatform()
        injector = Mock()
        injector.check_accessibility.return_value = False
        with patch.object(adapter, "create_text_injector", return_value=injector):
            with patch("ble_stt.platforms.macos.sys.executable", "/tmp/ble-stt/python"):
                passed, message = adapter.check_input_permission(True)
        self.assertFalse(passed)
        self.assertIn("/tmp/ble-stt/python", message)

    def test_frozen_permission_error_identifies_app(self):
        adapter = MacOSPlatform()
        injector = Mock()
        injector.check_accessibility.return_value = False
        with patch.object(adapter, "create_text_injector", return_value=injector):
            with patch.object(sys, "frozen", True, create=True):
                passed, message = adapter.check_input_permission(True)
        self.assertFalse(passed)
        self.assertIn("enable M5StopWatch", message)
        self.assertNotIn(sys.executable, message)

    def test_background_runtime_never_requests_permission(self):
        adapter = MacOSPlatform()
        injector = Mock()
        injector.check_accessibility.return_value = False
        with patch.object(adapter, "create_text_injector", return_value=injector):
            with patch("ble_stt.platforms.macos.platform.machine", return_value="arm64"):
                with self.assertRaises(RuntimeError):
                    adapter.validate_runtime()
                with self.assertRaises(RuntimeError):
                    adapter.validate_runtime()

        self.assertEqual(injector.check_accessibility.call_args_list, [call(False), call(False)])

    def test_bluetooth_permission_allowed(self):
        class FakeCBCentralManager:
            @staticmethod
            def authorization():
                return 3

        core_bluetooth = types.SimpleNamespace(
            CBCentralManager=FakeCBCentralManager,
            CBManagerAuthorizationAllowedAlways=3,
            CBManagerAuthorizationDenied=2,
            CBManagerAuthorizationNotDetermined=0,
            CBManagerAuthorizationRestricted=1,
        )
        with patch.dict(sys.modules, {"CoreBluetooth": core_bluetooth}):
            passed, message = MacOSPlatform().check_bluetooth_permission(False)

        self.assertTrue(passed)
        self.assertIn("Bluetooth permission is granted", message)

    def test_bluetooth_permission_not_determined_identifies_app(self):
        class FakeCBCentralManager:
            @staticmethod
            def authorization():
                return 0

        core_bluetooth = types.SimpleNamespace(
            CBCentralManager=FakeCBCentralManager,
            CBManagerAuthorizationAllowedAlways=3,
            CBManagerAuthorizationDenied=2,
            CBManagerAuthorizationNotDetermined=0,
            CBManagerAuthorizationRestricted=1,
        )
        with patch.dict(sys.modules, {"CoreBluetooth": core_bluetooth}):
            with patch.object(sys, "frozen", True, create=True):
                passed, message = MacOSPlatform().check_bluetooth_permission(False)

        self.assertFalse(passed)
        self.assertIn("enable M5StopWatch", message)
        self.assertIn("Bluetooth", message)

    def test_bluetooth_permission_prompt_creates_core_bluetooth_manager(self):
        calls = []

        class FakeCentralManagerInstance:
            def initWithDelegate_queue_options_(self, delegate, queue, options):
                calls.append((delegate, queue, options))
                return self

        class FakeCBCentralManager:
            authorizations = [0, 3]

            @classmethod
            def authorization(cls):
                return cls.authorizations.pop(0)

            @staticmethod
            def alloc():
                return FakeCentralManagerInstance()

        core_bluetooth = types.SimpleNamespace(
            CBCentralManager=FakeCBCentralManager,
            CBManagerAuthorizationAllowedAlways=3,
            CBManagerAuthorizationDenied=2,
            CBManagerAuthorizationNotDetermined=0,
            CBManagerAuthorizationRestricted=1,
        )
        with patch.dict(sys.modules, {"CoreBluetooth": core_bluetooth}):
            passed, message = MacOSPlatform().check_bluetooth_permission(True)

        self.assertTrue(passed)
        self.assertIn("Bluetooth permission is granted", message)
        self.assertEqual(calls, [(None, None, None)])

    @patch("ble_stt.platforms.macos.subprocess.run")
    def test_open_bluetooth_permission_settings(self, run: Mock):
        MacOSPlatform().open_bluetooth_permission_settings()

        self.assertIn("Privacy_Bluetooth", run.call_args.args[0][1])

    def test_unicode_input_and_focus_guard(self):
        quartz = FakeQuartz()
        injector = MacOSTextInjector(quartz, FakeAppKit)
        expected = injector.active_window()
        self.assertTrue(injector.type_text("你好 world", expected))
        self.assertEqual([event.get("text") for event in quartz.posts], ["你好 world", None])

        FakeWorkspace.pid = 43
        try:
            self.assertFalse(injector.type_text("blocked", expected))
        finally:
            FakeWorkspace.pid = 42


class MacBLEDiscoveryTests(unittest.TestCase):
    def test_connected_lookup_queries_vendor_speech_service_not_hid_service(self):
        uuid_queries = []
        managers = []

        class FakePeripheral:
            def name(self):
                return "M5StopWatch HID"

            def identifier(self):
                return types.SimpleNamespace(UUIDString=lambda: "watch-123")

        class FakeCentralManager:
            def retrieveConnectedPeripheralsWithServices_(self, services):
                self.services = services
                return [FakePeripheral()]

        class FakeDelegate:
            def __init__(self):
                self.central_manager = FakeCentralManager()
                managers.append(self)

            async def wait_until_ready(self):
                return None

        class FakeBLEDevice:
            def __init__(self, address, name, details):
                self.address = address
                self.name = name
                self.details = details

        class FakeCBUUID:
            @staticmethod
            def UUIDWithString_(value):
                uuid_queries.append(value)
                return value

        bleak = types.ModuleType("bleak")
        backends = types.ModuleType("bleak.backends")
        corebluetooth = types.ModuleType("bleak.backends.corebluetooth")
        delegate_module = types.ModuleType("bleak.backends.corebluetooth.CentralManagerDelegate")
        delegate_module.CentralManagerDelegate = FakeDelegate
        device_module = types.ModuleType("bleak.backends.device")
        device_module.BLEDevice = FakeBLEDevice
        core_bluetooth_module = types.ModuleType("CoreBluetooth")
        core_bluetooth_module.CBUUID = FakeCBUUID
        foundation_module = types.ModuleType("Foundation")
        foundation_module.NSArray = types.SimpleNamespace(arrayWithArray_=lambda value: value)

        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            adapter = MacOSPlatform(config)
            with patch.dict(
                sys.modules,
                {
                    "bleak": bleak,
                    "bleak.backends": backends,
                    "bleak.backends.corebluetooth": corebluetooth,
                    "bleak.backends.corebluetooth.CentralManagerDelegate": delegate_module,
                    "bleak.backends.device": device_module,
                    "CoreBluetooth": core_bluetooth_module,
                    "Foundation": foundation_module,
                },
            ):
                device = asyncio.run(adapter._retrieve_system_device(None))

        self.assertEqual(device.address, "watch-123")
        self.assertEqual(uuid_queries, [SERVICE_UUID])
        self.assertEqual(managers[0].central_manager.services, [SERVICE_UUID])
        self.assertNotIn("1812", uuid_queries)

    def test_connected_lookup_timeout_does_not_scan_or_connect(self):
        async def never_returns(identifier):
            await asyncio.Event().wait()

        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            adapter = MacOSPlatform(config)
            with patch.object(adapter, "_retrieve_system_device", side_effect=never_returns):
                with patch("ble_stt.platforms.macos.CORE_BLUETOOTH_CACHE_TIMEOUT_SECONDS", 0.01):
                    device = asyncio.run(adapter.find_connected_device(None))

        self.assertIsNone(device)
        self.assertIsNone(config.get("device_id"))

    def test_cached_identifier_is_only_a_filter_for_connected_hid(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            config.set("device_id", "stale-device")
            adapter = MacOSPlatform(config)
            with patch.object(adapter, "_retrieve_system_device", return_value=None) as retrieve:
                device = asyncio.run(adapter.find_connected_device(None))

        self.assertIsNone(device)
        retrieve.assert_awaited_once_with("stale-device")


class FakeWindowsAPI:
    def __init__(self):
        self.window = 100
        self.values = []

    def foreground_window(self):
        return self.window

    def send_unicode(self, text):
        self.values.append(text)


class WindowsInjectorTests(unittest.TestCase):
    def test_unicode_input_and_focus_guard(self):
        api = FakeWindowsAPI()
        injector = WindowsTextInjector(api)
        self.assertTrue(injector.type_text("你好", 100))
        self.assertEqual(api.values, ["你好"])
        api.window = 101
        self.assertFalse(injector.type_text("blocked", 100))


class ServiceRenderingTests(unittest.TestCase):
    def test_source_service_enters_module_foreground_runtime(self):
        with patch.object(sys, "frozen", False, create=True):
            with patch("ble_stt.service.sys.executable", "/tmp/venv/python"):
                self.assertEqual(
                    service_arguments(["--model", "small"]),
                    ["/tmp/venv/python", "-m", "ble_stt", "run", "--model", "small"],
                )

    def test_frozen_macos_service_launches_through_app_bundle(self):
        app = "/Users/test/Applications/M5StopWatch.app/Contents/MacOS/M5StopWatch"
        with patch.object(sys, "frozen", True, create=True):
            with patch("ble_stt.service.sys.executable", app):
                self.assertEqual(
                    service_arguments([], "darwin"),
                    [app, "run"],
                )

    def test_frozen_macos_service_prefers_fixed_helper_entrypoint(self):
        app = (
            "/Applications/M5StopWatch.app/Contents/Resources/resources/ble-stt-helper/"
            "M5StopWatch"
        )
        with patch.object(sys, "frozen", True, create=True):
            with patch("ble_stt.service.sys.executable", app):
                with patch.dict(
                    "ble_stt.service.os.environ",
                    {
                        "BLE_STT_SERVICE_HELPER": app,
                        "BLE_STT_SERVICE_APP_BUNDLE": "/Applications/M5StopWatch.app",
                    },
                ):
                    self.assertEqual(
                        service_arguments(["--model", "small"], "darwin"),
                        [app, "run", "--model", "small"],
                    )

    def test_frozen_macos_service_prefers_product_runner(self):
        runner = "/Applications/M5StopWatch.app/Contents/MacOS/m5stopwatch"
        helper = (
            "/Applications/M5StopWatch.app/Contents/Resources/resources/ble-stt-helper/"
            "M5StopWatch.app/Contents/MacOS/M5StopWatch"
        )
        with patch.object(sys, "frozen", True, create=True):
            with patch.dict(
                "ble_stt.service.os.environ",
                {
                    "BLE_STT_SERVICE_RUNNER": runner,
                    "BLE_STT_SERVICE_HELPER": helper,
                },
                clear=True,
            ):
                self.assertEqual(
                    service_arguments(["--model", "small"], "darwin"),
                    [runner, "service-run", "--model", "small"],
                )

    def test_frozen_macos_service_can_still_use_product_app_bundle(self):
        app = "/Applications/M5StopWatch.app/Contents/MacOS/m5stopwatch"
        with patch.object(sys, "frozen", True, create=True):
            with patch("ble_stt.service.sys.executable", app):
                with patch.dict(
                    "ble_stt.service.os.environ",
                    {"BLE_STT_SERVICE_APP_BUNDLE": "/Applications/M5StopWatch.app"},
                    clear=True,
                ):
                    self.assertEqual(
                        service_arguments([], "darwin"),
                        [app, "run"],
                    )

    def test_frozen_inner_helper_without_product_bundle_uses_executable(self):
        app = (
            "/Applications/M5StopWatch.app/Contents/Resources/resources/ble-stt-helper/"
            "M5StopWatch"
        )
        with patch.object(sys, "frozen", True, create=True):
            with patch("ble_stt.service.sys.executable", app):
                self.assertEqual(
                    service_arguments(["--model", "small"], "darwin"),
                    [app, "run", "--model", "small"],
                )

    def test_frozen_non_app_service_uses_executable(self):
        app = "/tmp/M5StopWatch"
        with patch.object(sys, "frozen", True, create=True):
            with patch("ble_stt.service.sys.executable", app):
                self.assertEqual(service_arguments([], "darwin"), [app, "run"])

    def test_systemd_unit_uses_explicit_interpreter(self):
        value = render_systemd_unit(
            ["/tmp/venv/python", "-m", "ble_stt", "run"], Path("/tmp/out"), Path("/tmp/err")
        )
        self.assertIn('ExecStart="/tmp/venv/python" "-m" "ble_stt" "run"', value)
        self.assertNotIn("Desktop/github", value)

    def test_launch_agent(self):
        value = plistlib.loads(
            render_launch_agent(
                ["/tmp/python", "-m", "ble_stt"],
                Path("/tmp/out"),
                Path("/tmp/err"),
            )
        )
        self.assertEqual(value["Label"], SERVICE_LABEL)
        self.assertTrue(value["RunAtLoad"])
        self.assertEqual(value["LimitLoadToSessionType"], "Aqua")

    def test_launch_agent_redirects_open_launched_helper_output(self):
        value = plistlib.loads(
            render_launch_agent(
                ["/usr/bin/open", "-W", "-g", "-j", "/tmp/M5StopWatch.app", "--args", "run"],
                Path("/tmp/out"),
                Path("/tmp/err"),
            )
        )
        self.assertEqual(
            value["ProgramArguments"],
            [
                "/usr/bin/open",
                "-W",
                "-g",
                "-j",
                "--stdout",
                "/tmp/out",
                "--stderr",
                "/tmp/err",
                "/tmp/M5StopWatch.app",
                "--args",
                "run",
            ],
        )

    @patch("ble_stt.service.subprocess.run")
    def test_macos_loaded_but_stopped_service_is_not_active(self, run: Mock):
        from ble_stt.service import ServiceManager

        manager = ServiceManager("darwin")
        with patch("ble_stt.service.os.getuid", return_value=501, create=True):
            with patch.object(manager, "is_installed", return_value=True):
                run.return_value = Mock(returncode=0, stdout="state = exited\n", stderr="")
                self.assertFalse(manager.is_active())
                run.return_value = Mock(returncode=0, stdout="state = running\n", stderr="")
                self.assertTrue(manager.is_active())

    def test_windows_action_quotes_paths(self):
        value = windows_task_action(["C:\\Program Files\\Python\\python.exe", "-m", "ble_stt"])
        self.assertIn('"C:\\Program Files\\Python\\python.exe"', value)


if __name__ == "__main__":
    unittest.main()
