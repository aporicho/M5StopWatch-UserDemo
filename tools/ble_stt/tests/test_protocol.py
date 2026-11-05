import struct
import unittest

from ble_stt.agreement import common_prefix, stable_extension
from ble_stt.protocol import (
    AudioFrame,
    CONNECTION_TIMING_FORMAT,
    HostStatus,
    HostStatusPacket,
    PerformanceConnectionSummary,
    PerformanceSessionSummary,
    PerformanceSyncRequest,
    PerformanceSyncResponse,
    ProtocolError,
    SESSION_TIMING_FORMAT,
    StatusEvent,
    StatusPacket,
    parse_performance_packet,
)
from ble_stt.main import TranscriptSegment, output_text


class ProtocolTests(unittest.TestCase):
    def test_status_packet(self):
        packet = StatusPacket.parse(struct.pack("<BBHHHBBH", 1, 1, 7, 16000, 320, 1, 1, 0))
        self.assertEqual(packet.event, StatusEvent.START)
        self.assertEqual(packet.session_id, 7)
        self.assertTrue(packet.active)

    def test_host_status_packet(self):
        value = HostStatusPacket(HostStatus.RECOGNIZING, 17)
        self.assertEqual(HostStatusPacket.parse(value.build()), value)

    def test_invalid_host_status_packet(self):
        with self.assertRaises(ProtocolError):
            HostStatusPacket.parse(bytes((1, 99, 0, 0)))

    def test_zero_adpcm_block(self):
        header = struct.pack("<BBHHH", 1, 1, 3, 9, 320)
        block = struct.pack("<hBB", 0, 0, 0) + bytes(160)
        decoded = AudioFrame.parse(header + block).decode()
        self.assertEqual(len(decoded), 320)
        self.assertEqual(set(decoded), {0})

    def test_invalid_packet_length(self):
        with self.assertRaises(ProtocolError):
            AudioFrame.parse(bytes(20))

    def test_performance_sync_packets(self):
        self.assertEqual(PerformanceSyncRequest(9).build(), struct.pack("<BBH", 1, 1, 9))
        response = parse_performance_packet(struct.pack("<BBHQQ", 1, 2, 9, 100, 110))
        self.assertEqual(response, PerformanceSyncResponse(9, 100, 110))

    def test_performance_session_summary(self):
        values = [1, 3, 7, (1 << 14) - 1, 12, 0]
        values.extend(range(100, 114))
        values.extend((1000, 40, 2000, 50, 3000, 60, 4000, 70))
        packet = struct.pack(SESSION_TIMING_FORMAT, *values)
        summary = parse_performance_packet(packet)

        self.assertIsInstance(summary, PerformanceSessionSummary)
        self.assertEqual(summary.session_id, 7)
        self.assertEqual(summary.timestamps_us["button_down"], 100)
        self.assertEqual(summary.aggregates_us["notify"]["max"], 70)

    def test_performance_connection_summary(self):
        packet = struct.pack(CONNECTION_TIMING_FORMAT, 1, 4, 0xFF, *range(10, 18))
        summary = parse_performance_packet(packet)
        self.assertIsInstance(summary, PerformanceConnectionSummary)
        self.assertEqual(summary.timestamps_us["performance_subscribed"], 17)

    def test_local_agreement(self):
        self.assertEqual(common_prefix("你好 world", "你好 work"), "你好 wor")
        delta, committed = stable_extension("你好 world", "你好 world!", "")
        self.assertEqual(delta, "你好 ")
        self.assertEqual(committed, "你好 ")

    def test_segment_spacing(self):
        chinese = [TranscriptSegment(0, 1, " 你好")]
        english = [TranscriptSegment(1, 2, " world")]
        self.assertEqual(output_text(chinese, False), "你好")
        self.assertEqual(output_text(chinese, True), "你好")
        self.assertEqual(output_text(english, True), " world")


if __name__ == "__main__":
    unittest.main()
