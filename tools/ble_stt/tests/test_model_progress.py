import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ble_stt.model_progress import PROGRESS_PREFIX, ModelProgressReporter


class ModelProgressReporterTests(unittest.TestCase):
    def test_environment_requires_complete_operation_identity(self):
        with patch.dict(
            "os.environ",
            {
                "BLE_STT_MODEL_PROGRESS": "1",
                "BLE_STT_MODEL_OPERATION_ID": "operation-1",
                "BLE_STT_MODEL_KIND": "speech",
                "BLE_STT_MODEL_ACTION": "install",
                "BLE_STT_MODEL_NAME": "medium",
            },
            clear=True,
        ):
            reporter = ModelProgressReporter.from_environment()

        self.assertIsNotNone(reporter)
        self.assertEqual(reporter.model, "medium")

    def test_download_monitor_emits_real_bytes_and_percentage(self):
        reporter = ModelProgressReporter(
            "operation-1",
            "speech",
            "install",
            "medium",
            interval=0.01,
        )
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch("sys.stderr", output):
            cache = Path(directory)
            with reporter.monitor_download((cache,), 10, component="model"):
                (cache / "weights.incomplete").write_bytes(b"12345")

        records = [
            json.loads(line.removeprefix(PROGRESS_PREFIX))
            for line in output.getvalue().splitlines()
        ]
        self.assertEqual(records[-1]["downloaded_bytes"], 5)
        self.assertEqual(records[-1]["percent"], 50.0)
        self.assertTrue(records[-1]["cancellable"])


if __name__ == "__main__":
    unittest.main()
