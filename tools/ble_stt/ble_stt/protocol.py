from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

PROTOCOL_VERSION = 1
SERVICE_UUID = "7f3a1000-6b2e-4c6d-a7c0-5e0d8b1f9a01"
STATUS_UUID = "7f3a1001-6b2e-4c6d-a7c0-5e0d8b1f9a01"
AUDIO_UUID = "7f3a1002-6b2e-4c6d-a7c0-5e0d8b1f9a01"
HOST_STATUS_UUID = "7f3a1003-6b2e-4c6d-a7c0-5e0d8b1f9a01"
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
