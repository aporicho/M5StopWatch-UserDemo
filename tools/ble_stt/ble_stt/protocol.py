from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

PROTOCOL_VERSION = 1
PERFORMANCE_WIRE_VERSION = 1
SERVICE_UUID = "7f3a1000-6b2e-4c6d-a7c0-5e0d8b1f9a01"
CONTROL_SERVICE_UUID = "7f3a1100-6b2e-4c6d-a7c0-5e0d8b1f9a01"
STATUS_UUID = "7f3a1001-6b2e-4c6d-a7c0-5e0d8b1f9a01"
AUDIO_UUID = "7f3a1002-6b2e-4c6d-a7c0-5e0d8b1f9a01"
HOST_STATUS_UUID = "7f3a1003-6b2e-4c6d-a7c0-5e0d8b1f9a01"
MAPPING_CONFIG_UUID = "7f3a1004-6b2e-4c6d-a7c0-5e0d8b1f9a01"
USER_EVENT_UUID = "7f3a1005-6b2e-4c6d-a7c0-5e0d8b1f9a01"
ACTION_EXEC_UUID = "7f3a1006-6b2e-4c6d-a7c0-5e0d8b1f9a01"
PERFORMANCE_UUID = "7f3a1007-6b2e-4c6d-a7c0-5e0d8b1f9a01"

SESSION_TIMING_NAMES = (
    "button_down",
    "hold_triggered",
    "speech_scheduled",
    "speech_start_call",
    "status_start_sent",
    "worker_started",
    "first_capture_done",
    "first_resample_done",
    "first_encode_done",
    "first_audio_sent",
    "release_detected",
    "stop_requested",
    "worker_exited",
    "status_end_sent",
)
DEVICE_AGGREGATE_NAMES = ("capture", "resample", "encode", "notify")
SESSION_TIMING_FORMAT = "<BBHHHH" + "Q" * len(SESSION_TIMING_NAMES) + "II" * len(DEVICE_AGGREGATE_NAMES)
CONNECTION_TIMING_NAMES = (
    "remote_started",
    "advertising_started",
    "link_connected",
    "encryption_ready",
    "mtu_ready",
    "speech_status_subscribed",
    "speech_audio_subscribed",
    "performance_subscribed",
)
CONNECTION_TIMING_FORMAT = "<BBH" + "Q" * len(CONNECTION_TIMING_NAMES)
DEVICE_NAME = "M5StopWatch HID"

STEP_TABLE = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
    143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
    1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
    4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
    27086, 29794, 32767,
)
INDEX_TABLE = (-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8)


class ProtocolError(ValueError):
    pass


class StatusEvent(IntEnum):
    READY = 0
    START = 1
    END = 2
    ABORT = 3
    ERROR = 4


class HostStatus(IntEnum):
    """Lifecycle state written by the desktop helper to compatible firmware."""

    WAITING = 0
    PREPARING = 1
    READY = 2
    RECOGNIZING = 3
    PERMISSION_ERROR = 4
    MODEL_ERROR = 5
    HOST_ERROR = 6


class PerformancePacketType(IntEnum):
    CAPABILITIES = 0
    SYNC_REQUEST = 1
    SYNC_RESPONSE = 2
    SESSION_SUMMARY = 3
    CONNECTION_SUMMARY = 4


@dataclass(frozen=True)
class PerformanceSyncRequest:
    sequence: int

    def build(self) -> bytes:
        return struct.pack("<BBH", PERFORMANCE_WIRE_VERSION, PerformancePacketType.SYNC_REQUEST, self.sequence & 0xFFFF)


@dataclass(frozen=True)
class PerformanceSyncResponse:
    sequence: int
    device_receive_us: int
    device_send_us: int


@dataclass(frozen=True)
class PerformanceSessionSummary:
    session_id: int
    flags: int
    frame_count: int
    notify_failures: int
    timestamps_us: dict[str, int | None]
    aggregates_us: dict[str, dict[str, int]]


@dataclass(frozen=True)
class PerformanceConnectionSummary:
    timestamps_us: dict[str, int | None]


def parse_performance_packet(
    data: bytes,
) -> PerformanceSyncResponse | PerformanceSessionSummary | PerformanceConnectionSummary | dict[str, int]:
    if len(data) < 2 or data[0] != PERFORMANCE_WIRE_VERSION:
        raise ProtocolError(f"performance packet has invalid version/shape: {len(data)} bytes")
    try:
        packet_type = PerformancePacketType(data[1])
    except ValueError as exc:
        raise ProtocolError(f"unknown performance packet type {data[1]}") from exc
    if packet_type == PerformancePacketType.CAPABILITIES:
        if len(data) != 4:
            raise ProtocolError(f"capabilities packet has {len(data)} bytes, expected 4")
        return {"capabilities": struct.unpack("<BBH", data)[2]}
    if packet_type == PerformancePacketType.SYNC_RESPONSE:
        if len(data) != struct.calcsize("<BBHQQ"):
            raise ProtocolError(f"sync response has {len(data)} bytes")
        _, _, sequence, received, sent = struct.unpack("<BBHQQ", data)
        return PerformanceSyncResponse(sequence, received, sent)
    if packet_type == PerformancePacketType.SESSION_SUMMARY:
        expected = struct.calcsize(SESSION_TIMING_FORMAT)
        if len(data) != expected:
            raise ProtocolError(f"session timing packet has {len(data)} bytes, expected {expected}")
        values = struct.unpack(SESSION_TIMING_FORMAT, data)
        _, _, session_id, flags, frame_count, failures = values[:6]
        offset = 6
        timestamps: dict[str, int | None] = {}
        for index, name in enumerate(SESSION_TIMING_NAMES):
            value = int(values[offset + index])
            timestamps[name] = value if flags & (1 << index) else None
        offset += len(SESSION_TIMING_NAMES)
        aggregates: dict[str, dict[str, int]] = {}
        for index, name in enumerate(DEVICE_AGGREGATE_NAMES):
            total = int(values[offset + index * 2])
            maximum = int(values[offset + index * 2 + 1])
            aggregates[name] = {"total": total, "max": maximum}
        return PerformanceSessionSummary(session_id, flags, frame_count, failures, timestamps, aggregates)
    if packet_type == PerformancePacketType.CONNECTION_SUMMARY:
        expected = struct.calcsize(CONNECTION_TIMING_FORMAT)
        if len(data) != expected:
            raise ProtocolError(f"connection timing packet has {len(data)} bytes, expected {expected}")
        values = struct.unpack(CONNECTION_TIMING_FORMAT, data)
        flags = int(values[2])
        timestamps = {
            name: int(values[index + 3]) if flags & (1 << index) else None
            for index, name in enumerate(CONNECTION_TIMING_NAMES)
        }
        return PerformanceConnectionSummary(timestamps)
    raise ProtocolError(f"unsupported performance packet type {packet_type}")


@dataclass(frozen=True)
class HostStatusPacket:
    status: HostStatus
    error: int = 0

    def build(self) -> bytes:
        if not 0 <= self.error <= 0xFFFF:
            raise ProtocolError(f"host error code is out of range: {self.error}")
        return struct.pack("<BBH", PROTOCOL_VERSION, int(self.status), self.error)

    @classmethod
    def parse(cls, data: bytes) -> "HostStatusPacket":
        if len(data) != 4:
            raise ProtocolError(f"host status packet has {len(data)} bytes, expected 4")
        version, status, error = struct.unpack("<BBH", data)
        if version != PROTOCOL_VERSION:
            raise ProtocolError(f"unsupported protocol version {version}")
        try:
            value = HostStatus(status)
        except ValueError as exc:
            raise ProtocolError(f"unknown host status {status}") from exc
        return cls(value, error)


@dataclass(frozen=True)
class StatusPacket:
    event: StatusEvent
    session_id: int
    sample_rate: int
    frame_samples: int
    codec: int
    active: bool
    error: int

    @classmethod
    def parse(cls, data: bytes) -> "StatusPacket":
        if len(data) != 12:
            raise ProtocolError(f"status packet has {len(data)} bytes, expected 12")
        version, event, session, rate, samples, codec, active, error = struct.unpack("<BBHHHBBH", data)
        if version != PROTOCOL_VERSION:
            raise ProtocolError(f"unsupported protocol version {version}")
        try:
            status_event = StatusEvent(event)
        except ValueError as exc:
            raise ProtocolError(f"unknown status event {event}") from exc
        if rate != 16000 or samples != 320 or codec != 1:
            raise ProtocolError(f"unsupported audio format: {rate} Hz, {samples} samples, codec {codec}")
        return cls(status_event, session, rate, samples, codec, bool(active), error)


@dataclass(frozen=True)
class AudioFrame:
    session_id: int
    sequence: int
    sample_count: int
    adpcm: bytes

    @classmethod
    def parse(cls, data: bytes) -> "AudioFrame":
        if len(data) != 172:
            raise ProtocolError(f"audio packet has {len(data)} bytes, expected 172")
        version, packet_type, session, sequence, samples = struct.unpack_from("<BBHHH", data)
        if version != PROTOCOL_VERSION or packet_type != 1:
            raise ProtocolError(f"unsupported audio packet version/type {version}/{packet_type}")
        if samples != 320:
            raise ProtocolError(f"unsupported frame size {samples}")
        return cls(session, sequence, samples, data[8:])

    def decode(self) -> list[int]:
        if len(self.adpcm) != 164:
            raise ProtocolError("invalid IMA ADPCM block size")
        predictor = struct.unpack_from("<h", self.adpcm)[0]
        step_index = self.adpcm[2]
        if step_index > 88:
            raise ProtocolError(f"invalid IMA ADPCM step index {step_index}")

        output = [predictor]
        for packed in self.adpcm[4:]:
            for nibble in (packed & 0x0F, packed >> 4):
                if len(output) >= self.sample_count:
                    return output
                step = STEP_TABLE[step_index]
                delta = step >> 3
                if nibble & 0x01:
                    delta += step >> 2
                if nibble & 0x02:
                    delta += step >> 1
                if nibble & 0x04:
                    delta += step
                predictor += -delta if nibble & 0x08 else delta
                predictor = max(-32768, min(32767, predictor))
                step_index = max(0, min(88, step_index + INDEX_TABLE[nibble]))
                output.append(predictor)
        if len(output) != self.sample_count:
            raise ProtocolError(f"decoded {len(output)} samples, expected {self.sample_count}")
        return output
