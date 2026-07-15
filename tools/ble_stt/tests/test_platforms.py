import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ble_stt.config import UserConfig, config_dir, install_dir, model_cache_dir
from ble_stt.platforms import create_platform
from ble_stt.platforms.linux import LinuxTextInjector
from ble_stt.platforms.macos import MacOSTextInjector, MacWindowToken
from ble_stt.platforms.windows import WindowsTextInjector
from ble_stt.recognizers import create_recognizer, resolve_engine, resolve_model
from ble_stt.service import (
    SERVICE_LABEL,
    render_launch_agent,
    render_systemd_unit,
    service_arguments,
    windows_task_action,
)


class ConfigTests(unittest.TestCase):
    def test_platform_config_paths(self):
        self.assertTrue(str(config_dir("darwin")).endswith("Library/Application Support/M5StopWatch"))
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/test/AppData/Local"}):
            self.assertEqual(config_dir("win32"), Path("C:/Users/test/AppData/Local/M5StopWatch"))
            self.assertEqual(
                install_dir("win32"), Path("C:/Users/test/AppData/Local/M5StopWatch/ble-stt")
            )
        self.assertTrue(str(install_dir("darwin")).endswith("M5StopWatch/ble-stt"))
        self.assertTrue(str(model_cache_dir("darwin")).endswith("Caches/M5StopWatch/ble-stt"))

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

    @patch("ble_stt.recognizers.FasterWhisperRecognizer")
    def test_recognizer_uses_private_model_cache(self, recognizer: Mock):
        with patch("ble_stt.config.sys.platform", "linux"):
            with patch.dict(os.environ, {"HOME": "/tmp/ble-stt-test"}, clear=True):
                create_recognizer("faster-whisper", "small", "cpu", 2)
                self.assertTrue(os.environ["HF_HOME"].endswith(".cache/m5stopwatch/ble-stt"))
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
    kAXTrustedCheckOptionPrompt = "prompt"
    kAXFocusedWindowAttribute = "focused-window"
    kCGEventSourceStateCombinedSessionState = 0
    kCGHIDEventTap = 0

    def __init__(self):
        self.posts = []

    def AXIsProcessTrustedWithOptions(self, options):
        return True

    def AXUIElementCreateApplication(self, pid):
        return pid

    def AXUIElementCopyAttributeValue(self, element, attribute, unused):
        return 0, f"window-{element}"

    def CFEqual(self, left, right):
        return left == right

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
    def test_service_enters_foreground_runtime(self):
        self.assertEqual(service_arguments([])[-1], "run")

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

    def test_windows_action_quotes_paths(self):
        value = windows_task_action(["C:\\Program Files\\Python\\python.exe", "-m", "ble_stt"])
        self.assertIn('"C:\\Program Files\\Python\\python.exe"', value)


if __name__ == "__main__":
    unittest.main()
