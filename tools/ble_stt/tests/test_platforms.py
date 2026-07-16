import os
import plistlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from ble_stt.config import UserConfig, config_dir, install_dir, model_cache_dir
from ble_stt.platforms import create_platform
from ble_stt.platforms.linux import LinuxTextInjector
from ble_stt.platforms.macos import MacOSPlatform, MacOSTextInjector, MacWindowToken
from ble_stt.platforms.windows import WindowsTextInjector
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
        self.assertEqual(resolve_model("mlx", "organization/custom-model"), "organization/custom-model")
        self.assertEqual(resolve_model("faster-whisper", "medium"), "medium")

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

    def test_frozen_service_uses_stable_app_executable(self):
        app = "/Users/test/Applications/M5StopWatch.app/Contents/MacOS/M5StopWatch"
        with patch.object(sys, "frozen", True, create=True):
            with patch("ble_stt.service.sys.executable", app):
                self.assertEqual(service_arguments([]), [app, "run"])

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
