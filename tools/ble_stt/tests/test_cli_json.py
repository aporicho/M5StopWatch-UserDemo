import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ble_stt import cli
from ble_stt.config import UserConfig


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

    def test_logs_json_structures_event_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_log = root / "ble-stt-events.log"
            service_log = root / "ble-stt.log"
            error_log = root / "ble-stt-error.log"
            event_log.write_text(
                "2026-07-26 11:02:59.140 INFO [47617:asyncio_0] "
                "ble_stt: stdout: [model] MLX ready\n",
                encoding="utf-8",
            )
            with patch("ble_stt.cli.event_log_paths", return_value=(event_log, service_log, error_log)):
                with patch("ble_stt.cli.log_dir", return_value=root):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = cli.show_logs(["--json", "--lines", "5"])

        payload = json.loads(output.getvalue())
        entry = payload["logs"]["entries"][0]

        self.assertEqual(code, 0)
        self.assertEqual(entry["time"], "2026-07-26 11:02:59.140")
        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["component"], "stdout")
        self.assertEqual(entry["context"], "47617:asyncio_0")
        self.assertEqual(entry["message"], "[model] MLX ready")

    def test_logs_json_keeps_carriage_return_progress_as_one_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_log = root / "ble-stt-events.log"
            service_log = root / "ble-stt.log"
            error_log = root / "ble-stt-error.log"
            event_log.write_text(
                "2026-07-26 11:02:58.932 ERROR [47617:asyncio_0] "
                "ble_stt: stderr: \rFetching 4 files: 25%\rFetching 4 files: 100%\n",
                encoding="utf-8",
            )
            with patch("ble_stt.cli.event_log_paths", return_value=(event_log, service_log, error_log)):
                with patch("ble_stt.cli.log_dir", return_value=root):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = cli.show_logs(["--json", "--lines", "5"])

        payload = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(len(payload["logs"]["entries"]), 1)
        self.assertEqual(payload["logs"]["entries"][0]["component"], "stderr")
        self.assertEqual(payload["logs"]["entries"][0]["message"], "Fetching 4 files: 25% Fetching 4 files: 100%")

    def test_telemetry_json_reports_runtime_payload(self):
        with patch("ble_stt.cli.read_telemetry", return_value={"schema": 1, "stage": "listening"}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli.show_telemetry(["--json"])

        payload = json.loads(output.getvalue())

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["telemetry"]["stage"], "listening")

    def test_mappings_json_reports_default_event_map(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "ble-stt.json"
            with patch("ble_stt.cli.UserConfig", return_value=UserConfig(config_path)):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    with self.assertRaises(SystemExit) as raised:
                        cli.main(["mappings", "status", "--json"])

        payload = json.loads(output.getvalue())

        self.assertEqual(raised.exception.code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mapping"]["entries"][0]["event"], "button.left.tap")
        self.assertEqual(payload["events"][-1]["id"], "button.both.hold")

    def test_commands_json_reports_default_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "ble-stt.json"
            with patch("ble_stt.cli.UserConfig", return_value=UserConfig(config_path)):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    with self.assertRaises(SystemExit) as raised:
                        cli.main(["commands", "status", "--json"])

        payload = json.loads(output.getvalue())

        self.assertEqual(raised.exception.code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["commands"]["entries"][0]["phrase"], "清空")
        self.assertTrue(any(action["id"] == "hid.keyboard.tap" for action in payload["actions"]))


if __name__ == "__main__":
    unittest.main()
