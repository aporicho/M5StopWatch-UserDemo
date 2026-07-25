import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ble_stt import cli


class CliJsonTests(unittest.TestCase):
    def test_logs_json_reports_empty_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = (root / "ble-stt-events.log", root / "ble-stt.log", root / "ble-stt-error.log")
            with patch("ble_stt.cli.event_log_paths", return_value=paths):
                with patch("ble_stt.cli.log_dir", return_value=root):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = cli.show_logs(["--json", "--lines", "20"])

        payload = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["logs"]["directory"], str(root))
        self.assertEqual(len(payload["logs"]["files"]), 3)
        self.assertFalse(payload["logs"]["files"][0]["exists"])

    def test_logs_json_tails_each_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_log = root / "ble-stt-events.log"
            service_log = root / "ble-stt.log"
            error_log = root / "ble-stt-error.log"
            event_log.write_text("a\nb\nc\n", encoding="utf-8")
            service_log.write_text("service\n", encoding="utf-8")
            with patch("ble_stt.cli.event_log_paths", return_value=(event_log, service_log, error_log)):
                with patch("ble_stt.cli.log_dir", return_value=root):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = cli.show_logs(["--json", "--lines", "2"])

        payload = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(payload["logs"]["files"][0]["lines"], ["b", "c"])
        self.assertEqual(
            [entry["source"] for entry in payload["logs"]["entries"]],
            ["ble-stt-events.log", "ble-stt-events.log", "ble-stt.log"],
        )


if __name__ == "__main__":
    unittest.main()
