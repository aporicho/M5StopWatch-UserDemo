import contextlib
import io
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ble_stt.diagnostics import EVENT_LOG_NAME, event_log_paths, runtime_logging


class RuntimeLoggingTests(unittest.TestCase):
    def test_runtime_logging_records_stdout_and_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("ble_stt.diagnostics.log_dir", return_value=root):
                with patch("ble_stt.diagnostics.config_dir", return_value=root / "config"):
                    with patch("ble_stt.diagnostics.model_cache_dir", return_value=root / "cache"):
                        stdout = io.StringIO()
                        with contextlib.redirect_stdout(stdout):
                            with runtime_logging("test", {"flag": True}):
                                print("hello")
                                logging.getLogger("ble_stt.runtime").warning("structured event")

            text = (root / EVENT_LOG_NAME).read_text(encoding="utf-8")

        self.assertIn("startup component=test", text)
        self.assertIn("stdout: hello", text)
        self.assertIn("structured event", text)
        self.assertEqual(stdout.getvalue(), "hello\n")

    def test_event_log_paths_lists_structured_log_first(self):
        paths = event_log_paths("darwin")
        self.assertEqual(paths[0].name, EVENT_LOG_NAME)
        self.assertEqual(paths[1].name, "ble-stt.log")
        self.assertEqual(paths[2].name, "ble-stt-error.log")


if __name__ == "__main__":
    unittest.main()
