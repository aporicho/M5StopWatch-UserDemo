import tempfile
import unittest
from pathlib import Path

from ble_stt.performance import (
    ClockSynchronizer,
    PerformanceTrace,
    append_performance,
    clear_performance,
    percentile,
    read_performance,
)


class FakeClock:
    def __init__(self):
        self.ns = 1_000_000_000
        self.wall = 100.0

    def monotonic_ns(self):
        return self.ns

    def wall_time(self):
        return self.wall

    def advance_ms(self, value):
        self.ns += int(value * 1_000_000)
        self.wall += value / 1000.0


class PerformanceTests(unittest.TestCase):
    def test_trace_uses_monotonic_time_and_separates_aggregates(self):
        clock = FakeClock()
        trace = PerformanceTrace("session", session_id=7, monotonic_ns=clock.monotonic_ns, wall_time=clock.wall_time)
        trace.mark("start")
        clock.advance_ms(12.5)
        trace.mark("end")
        trace.add_span_between("work", "start", "end", lane="host", category="work")
        trace.observe("decode", 0.2, lane="ble")
        trace.observe("decode", 0.4, lane="ble")
        record = trace.finish("success")

        self.assertEqual(record["duration_ms"], 12.5)
        self.assertEqual(record["spans"][0]["duration_ms"], 12.5)
        aggregate = record["spans"][1]
        self.assertEqual(aggregate["count"], 2)
        self.assertEqual(aggregate["mean_ms"], 0.3)
        self.assertNotIn("_start_ns", record["spans"][0])

    def test_nearest_rank_percentiles(self):
        self.assertEqual(percentile([1, 2, 3, 4], 0.5), 2)
        self.assertEqual(percentile([1, 2, 3, 4], 0.95), 4)
        self.assertIsNone(percentile([], 0.95))

    def test_storage_retains_bounded_private_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "performance.json"
            for index in range(205):
                append_performance({"kind": "session", "trace_id": str(index)}, path)
            for index in range(25):
                append_performance({"kind": "lifecycle", "trace_id": f"l{index}"}, path)
            payload = read_performance(path)

            self.assertEqual(len(payload["sessions"]), 200)
            self.assertEqual(payload["sessions"][0]["trace_id"], "5")
            self.assertEqual(len(payload["lifecycles"]), 20)
            cleared = clear_performance(path)
            self.assertEqual(cleared["sessions"], [])
            self.assertGreater(cleared["revision"], payload["revision"])

    def test_clock_sync_selects_lowest_rtt_and_maps_device_clock(self):
        sync = ClockSynchronizer()
        sync.begin(1, 1_000_000_000)
        sync.complete(1, 100_000, 100_100, 1_020_000_000)
        sync.begin(2, 2_000_000_000)
        sync.complete(2, 200_000, 200_100, 2_004_000_000)

        self.assertAlmostEqual(float(sync.payload()["rtt_ms"]), 3.9)
        self.assertIsNotNone(sync.device_to_host_ns(200_050))
        self.assertTrue(sync.payload()["merged"])

    def test_clock_sync_refuses_cross_device_conversion_when_uncertain(self):
        sync = ClockSynchronizer()
        sync.begin(1, 10_000_000)
        sync.complete(1, 1_000, 1_000, 40_000_000)

        self.assertEqual(sync.payload(), {"rtt_ms": 30.0, "uncertainty_ms": 15.0, "merged": False})
        self.assertIsNone(sync.device_to_host_ns(1_020))

    def test_corrupt_history_falls_back_to_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "performance.json"
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(read_performance(path)["sessions"], [])


if __name__ == "__main__":
    unittest.main()
