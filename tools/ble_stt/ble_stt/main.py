from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from .agreement import TextInjector, common_prefix
from .protocol import (
    AUDIO_UUID,
    DEVICE_NAME,
    SERVICE_UUID,
    STATUS_UUID,
    AudioFrame,
    ProtocolError,
    StatusEvent,
    StatusPacket,
)


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class SpeechSession:
    session_id: int
    focus_window: str | None
    audio: list[int] = field(default_factory=list)
    audio_cursor: int = 0
    expected_sequence: int = 0
    previous_segments: list[TranscriptSegment] = field(default_factory=list)
    last_inference_size: int = 0
    has_output: bool = False
    injection_enabled: bool = True
    inference_pending: bool = False


class LocalRecognizer:
    def __init__(self, model_name: str, device: str, cpu_threads: int) -> None:
        from faster_whisper import WhisperModel
        from opencc import OpenCC

        self.simplifier = OpenCC("tw2sp")
        kwargs: dict[str, Any] = {"cpu_threads": cpu_threads, "num_workers": 1}
        if device == "auto":
            import ctranslate2

            cuda_available = ctranslate2.get_cuda_device_count() > 0
            if cuda_available:
                try:
                    print(f"[model] loading {model_name} on CUDA")
                    self.model = WhisperModel(model_name, device="cuda", compute_type="float16", **kwargs)
                    self.device = "cuda"
                except Exception as exc:  # Driver/runtime failures use several exception types.
                    print(f"[model] CUDA initialization failed ({exc}); falling back to CPU INT8")
                    self.model = WhisperModel(model_name, device="cpu", compute_type="int8", **kwargs)
                    self.device = "cpu"
            else:
                print("[model] CUDA unavailable; using CPU INT8")
                self.model = WhisperModel(model_name, device="cpu", compute_type="int8", **kwargs)
                self.device = "cpu"
        else:
            compute_type = "float16" if device == "cuda" else "int8"
            print(f"[model] loading {model_name} on {device} ({compute_type})")
            self.model = WhisperModel(model_name, device=device, compute_type=compute_type, **kwargs)
            self.device = device
        print(f"[model] ready on {self.device}")

    def transcribe(self, pcm: list[int]) -> list[TranscriptSegment]:
        import numpy as np

        if not pcm:
            return []
        audio = np.asarray(pcm, dtype=np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio,
            language=None,
            task="transcribe",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return [
            TranscriptSegment(float(item.start), float(item.end), self.simplifier.convert(item.text))
            for item in segments
        ]


def canonical_text(segments: list[TranscriptSegment]) -> str:
    return "".join(segment.text for segment in segments).strip()


def output_text(segments: list[TranscriptSegment], has_output: bool) -> str:
    value = "".join(segment.text for segment in segments).rstrip()
    stripped = value.lstrip()
    if not has_output or not stripped:
        return stripped
    # Whisper commonly prefixes English segments with a space, while Chinese
    # segments should normally be joined without one.
    if value != stripped and stripped[0].isascii() and stripped[0].isalnum():
        return " " + stripped
    return stripped


class SpeechController:
    def __init__(self, recognizer: LocalRecognizer, interval: float, stable_lag: float) -> None:
        self.recognizer = recognizer
        self.interval = interval
        self.stable_lag = stable_lag
        self.injector = TextInjector()
        self.session: SpeechSession | None = None
        self.inference_lock = asyncio.Lock()
        self._rolling_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._rolling_task = asyncio.create_task(self._rolling_loop())

    async def close(self) -> None:
        if self._rolling_task:
            self._rolling_task.cancel()
            try:
                await self._rolling_task
            except asyncio.CancelledError:
                pass
        self.abort("helper stopped")

    def receive_status(self, raw: bytes) -> None:
        try:
            status = StatusPacket.parse(raw)
        except ProtocolError as exc:
            print(f"[protocol] {exc}")
            return
        if status.event == StatusEvent.READY:
            print("[device] speech input ready; hold the right button to talk")
        elif status.event == StatusEvent.START:
            if self.session is not None:
                self.abort("new speech session started")
            self.session = SpeechSession(status.session_id, self.injector.active_window())
            print(f"[speech {status.session_id}] listening")
        elif status.event == StatusEvent.END:
            session = self.session
            if session and session.session_id == status.session_id:
                self.session = None
                asyncio.create_task(self._finalize(session))
        elif status.event == StatusEvent.ABORT:
            self.abort("device aborted the session")
        elif status.event == StatusEvent.ERROR:
            self.abort(f"device error {status.error}")

    def receive_audio(self, raw: bytes) -> None:
        session = self.session
        if session is None:
            return
        try:
            frame = AudioFrame.parse(raw)
            if frame.session_id != session.session_id:
                return
            missing = (frame.sequence - session.expected_sequence) & 0xFFFF
            if missing:
                if missing <= 2:
                    session.audio.extend([0] * (missing * frame.sample_count))
                    print(f"[speech {session.session_id}] filled {missing} missing frame(s) with silence")
                else:
                    self.abort(f"lost {missing} consecutive audio frames")
                    return
            session.audio.extend(frame.decode())
            session.expected_sequence = (frame.sequence + 1) & 0xFFFF
        except ProtocolError as exc:
            self.abort(str(exc))

    def abort(self, reason: str) -> None:
        if self.session is not None:
            print(f"[speech {self.session.session_id}] aborted: {reason}")
            self.session = None

    async def _rolling_loop(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            session = self.session
            if session is None:
                continue
            if session.inference_pending:
                continue
            available = len(session.audio) - session.audio_cursor
            growth = len(session.audio) - session.last_inference_size
            if available < 16000 or growth < int(self.interval * 16000):
                continue
            session.last_inference_size = len(session.audio)
            session.inference_pending = True
            asyncio.create_task(self._recognize_stable(session))

    async def _recognize(self, pcm: list[int]) -> list[TranscriptSegment]:
        async with self.inference_lock:
            return await asyncio.to_thread(self.recognizer.transcribe, pcm)

    async def _recognize_stable(self, session: SpeechSession) -> None:
        try:
            if self.session is not session:
                return
            snapshot = session.audio[session.audio_cursor:]
            segments = await self._recognize(snapshot)
            if self.session is not session:
                return
            duration = len(snapshot) / 16000.0
            stable = [segment for segment in segments if segment.end <= duration - self.stable_lag]
            if not stable:
                session.previous_segments = segments
                return

            previous_text = canonical_text(session.previous_segments)
            current_text = canonical_text(stable)
            agreement = common_prefix(previous_text, current_text)
            commit_count = 0
            for index in range(1, len(stable) + 1):
                prefix = canonical_text(stable[:index])
                if len(prefix) <= len(agreement) and agreement.startswith(prefix):
                    commit_count = index
            if commit_count == 0:
                session.previous_segments = stable
                return

            committed_segments = stable[:commit_count]
            text = output_text(committed_segments, session.has_output)
            if session.injection_enabled and text:
                session.injection_enabled = self.injector.type_text(text, session.focus_window)
                if session.injection_enabled:
                    print(f"[text] {text}")
                    session.has_output = True
            advance = min(len(snapshot), max(1, int(committed_segments[-1].end * 16000)))
            session.audio_cursor += advance
            session.previous_segments = []
            session.last_inference_size = session.audio_cursor
        except Exception as exc:
            if self.session is session:
                self.abort(f"recognition failed: {exc}")
        finally:
            session.inference_pending = False

    async def _finalize(self, session: SpeechSession) -> None:
        snapshot = session.audio[session.audio_cursor:]
        try:
            segments = await self._recognize(snapshot)
        except Exception as exc:
            print(f"[speech {session.session_id}] final recognition failed: {exc}")
            return
        text = output_text(segments, session.has_output)
        if session.injection_enabled and text:
            session.injection_enabled = self.injector.type_text(text, session.focus_window)
            if session.injection_enabled:
                print(f"[text final] {text}")
        elapsed = len(session.audio) / 16000.0
        print(f"[speech {session.session_id}] finished ({elapsed:.1f}s)")


def paired_address() -> str | None:
    if shutil.which("bluetoothctl") is None:
        return None
    try:
        result = subprocess.run(
            ["bluetoothctl", "devices", "Paired"], check=True, capture_output=True, text=True, timeout=5
        )
    except subprocess.SubprocessError:
        return None
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0] == "Device" and parts[2] == DEVICE_NAME:
            return parts[1]
    return None


async def find_device(address: str | None):
    from bleak import BleakScanner

    if address:
        device = await BleakScanner.find_device_by_address(address, timeout=5)
        return device or address
    paired = paired_address()
    if paired:
        print(f"[ble] using paired device {paired}")
        device = await BleakScanner.find_device_by_address(paired, timeout=3)
        return device or paired
    print(f"[ble] scanning for {DEVICE_NAME}")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
    if device is None:
        raise RuntimeError(f"{DEVICE_NAME} was not found; open BLE Remote and pair it first")
    return device


async def acquire_mtu(client: Any) -> int:
    """Ask BlueZ for the negotiated MTU instead of its default value of 23."""
    backend = getattr(client, "_backend", None)
    if sys.platform == "linux" and backend is not None:
        # Bleak's generic BlueZ helper selects the first notifying
        # characteristic. On a HID composite device that characteristic is
        # already owned by BlueZ's input plugin, so target our audio stream.
        from bleak.backends.bluezdbus import defs
        from bleak.backends.bluezdbus.utils import assert_reply
        from dbus_fast.message import Message

        characteristic = client.services.get_characteristic(AUDIO_UUID)
        if characteristic is None:
            raise RuntimeError("speech audio characteristic is missing")
        reply = await backend._bus.call(
            Message(
                destination=defs.BLUEZ_SERVICE,
                path=characteristic.obj[0],
                interface=defs.GATT_CHARACTERISTIC_INTERFACE,
                member="AcquireNotify",
                signature="a{sv}",
                body=[{}],
            )
        )
        assert_reply(reply)
        os.close(reply.unix_fds[0])
        backend._mtu_size = int(reply.body[1])
    else:
        acquire = getattr(backend, "_acquire_mtu", None)
        if acquire is not None:
            await acquire()
    return int(client.mtu_size)


async def use_cached_bluez_device(client: Any, device: Any) -> None:
    """Let Bleak attach to an already-connected paired device on Linux.

    A HID host normally reconnects before the peripheral can advertise again,
    so a fresh scan cannot rediscover it. BlueZ still has the stable D-Bus
    device path and Bleak can safely attach to that cached object.
    """
    if sys.platform != "linux" or not isinstance(device, str):
        return
    backend = getattr(client, "_backend", None)
    get_path = getattr(backend, "_get_device_path", None)
    if get_path is not None:
        backend._device_path = await get_path()


async def run_ble(controller: SpeechController, address: str | None) -> None:
    from bleak import BleakClient

    delay = 1.0
    while True:
        disconnect_event = asyncio.Event()
        try:
            device = await find_device(address)
            print(f"[ble] connecting to {device}")
            client = BleakClient(device, disconnected_callback=lambda _: disconnect_event.set())
            await use_cached_bluez_device(client, device)
            async with client:
                service_uuids = {str(service.uuid).lower() for service in client.services}
                if SERVICE_UUID not in service_uuids:
                    raise RuntimeError(
                        "Speech GATT service is missing. Reopen BLE Remote; if BlueZ cached the old firmware, "
                        "forget the device on both sides and pair again."
                    )
                # Accessing an encrypted characteristic makes BlueZ restore the
                # bond and encrypt the link before AcquireNotify negotiates MTU.
                await client.read_gatt_char(STATUS_UUID)
                mtu = await acquire_mtu(client)
                if mtu < 185:
                    raise RuntimeError(f"negotiated MTU {mtu} is too small for speech audio (need 185)")
                print(f"[ble] connected, MTU {mtu}")
                await client.start_notify(STATUS_UUID, lambda _, data: controller.receive_status(bytes(data)))
                await client.start_notify(AUDIO_UUID, lambda _, data: controller.receive_audio(bytes(data)))
                delay = 1.0
                await disconnect_event.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[ble] {exc}; retrying in {delay:.0f}s")
            controller.abort("Bluetooth disconnected")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M5StopWatch BLE push-to-talk helper")
    parser.add_argument("--address", help="Bluetooth address; normally detected from bluetoothctl")
    parser.add_argument("--model", default="medium", help="faster-whisper model name (default: medium)")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--cpu-threads", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    parser.add_argument("--interval", type=float, default=1.0, help="minimum seconds of new audio per pass")
    parser.add_argument("--stable-lag", type=float, default=0.8, help="uncommitted audio tail in seconds")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> None:
    if shutil.which("wtype") is None:
        raise RuntimeError("wtype is required for Wayland text injection")
    recognizer = await asyncio.to_thread(LocalRecognizer, args.model, args.device, args.cpu_threads)
    controller = SpeechController(recognizer, args.interval, args.stable_lag)
    controller.start()
    try:
        await run_ble(controller, args.address)
    finally:
        await controller.close()


def main() -> None:
    try:
        asyncio.run(async_main(parse_args()))
    except KeyboardInterrupt:
        print("\nStopped")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
