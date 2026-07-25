import unittest

from ble_stt.journey import scan_journey_lines


class JourneyLogTests(unittest.TestCase):
    def test_counts_inserted_sessions(self):
        summary = scan_journey_lines(
            [
                "2026 INFO ble_stt.runtime: speech session started session=1",
                "2026 INFO ble_stt.runtime: speech session finalized session=1 elapsed=2.5s "
                "text_inserted=True injection_enabled=True",
                "2026 INFO ble_stt.runtime: speech session started session=2",
                "2026 INFO ble_stt.runtime: speech session finalized session=2 elapsed=1.2s "
                "text_inserted=True injection_enabled=True",
            ]
        )

        self.assertEqual(summary.started_sessions, 2)
        self.assertEqual(summary.ready_events, 0)
        self.assertEqual(len(summary.finalized_sessions), 2)
        self.assertEqual(summary.inserted_sessions, 2)
        self.assertEqual(summary.failed_sessions, 0)
        self.assertFalse(summary.has_errors)

    def test_counts_reused_session_ids_after_restart(self):
        summary = scan_journey_lines(
            [
                "speech session finalized session=1 elapsed=1.0s text_inserted=True injection_enabled=True",
                "speech session finalized session=1 elapsed=1.1s text_inserted=True injection_enabled=True",
            ]
        )

        self.assertEqual(summary.inserted_sessions, 2)

    def test_detects_failed_insertion(self):
        summary = scan_journey_lines(
            ["speech session finalized session=3 elapsed=1.0s text_inserted=False injection_enabled=True"]
        )

        self.assertEqual(summary.inserted_sessions, 0)
        self.assertEqual(summary.failed_sessions, 1)

    def test_detects_error_lines(self):
        summary = scan_journey_lines(
            [
                "2026 ERROR ble_stt.runtime: model preparation failed",
                "2026 INFO ble_stt.runtime: host status sent status=MODEL_ERROR error=1",
            ]
        )

        self.assertTrue(summary.has_errors)
        self.assertEqual(len(summary.error_lines), 1)

    def test_ignores_host_status_error_names(self):
        summary = scan_journey_lines(
            [
                "2026 DEBUG ble_stt.runtime: host status sent status=PERMISSION_ERROR error=1",
                "2026 DEBUG ble_stt.runtime: host status sent status=HOST_ERROR error=1",
            ]
        )

        self.assertFalse(summary.has_errors)

    def test_detects_ready_lines(self):
        summary = scan_journey_lines(
            [
                "2026 INFO ble_stt: stdout: [ble] connected, MTU 247",
                "2026 INFO ble_stt: stdout: [device] speech input ready; hold the right button to talk",
            ]
        )

        self.assertEqual(summary.ready_events, 2)


if __name__ == "__main__":
    unittest.main()
