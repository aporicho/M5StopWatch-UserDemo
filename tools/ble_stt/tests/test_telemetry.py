import tempfile
import unittest
from pathlib import Path

from ble_stt.telemetry import audio_metrics, make_telemetry, read_telemetry, write_telemetry


class TelemetryTests(unittest.TestCase):
    def test_audio_metrics_normalize_silence(self):
        metrics = audio_metrics([0, 0, 0, 0])

        self.assertEqual(metrics["level"], 0.0)
        self.assertEqual(metrics["peak"], 0.0)

    def test_audio_metrics_report_speech_energy(self):
        metrics = audio_metrics([0, 12000, -12000, 6000, -6000])

        self.assertGreater(metrics["level"], 0.0)
        self.assertGreater(metrics["peak"], 0.0)
        self.assertLessEqual(metrics["level"], 1.0)
        self.assertLessEqual(metrics["peak"], 1.0)

    def test_write_and_read_telemetry_marks_fresh_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            payload = make_telemetry(
                stage="listening",
                session_id=7,
                audio={"level": 0.4, "peak": 0.6, "seconds": 1.25, "frames": 63},
                now=100.0,
            )

            write_telemetry(payload, path)
            result = read_telemetry(path, now=101.0)

        self.assertEqual(result["stage"], "listening")
        self.assertEqual(result["session_id"], 7)
        self.assertEqual(result["audio"]["level"], 0.4)
        self.assertFalse(result["stale"])
        self.assertEqual(result["age_seconds"], 1.0)

    def test_missing_telemetry_returns_stale_offline_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            result = read_telemetry(Path(directory) / "missing.json", now=100.0)

        self.assertEqual(result["stage"], "offline")
        self.assertTrue(result["stale"])


if __name__ == "__main__":
    unittest.main()
