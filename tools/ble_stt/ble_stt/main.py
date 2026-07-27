from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from .agreement import common_prefix
from .commands import encode_command_action, match_command, read_commands
from .config import UserConfig
from .diagnostics import runtime_logging
from .mapping import encode_mapping, parse_user_event_packet, read_mapping
from .models import DEFAULT_ENGINE, DEFAULT_MODEL, model_status, record_model_ready, runtime_model_name
from .platforms import PlatformAdapter, create_platform
from .protocol import (
    AUDIO_UUID,
    ACTION_EXEC_UUID,
    CONTROL_SERVICE_UUID,
    HOST_STATUS_UUID,
    MAPPING_CONFIG_UUID,
    SERVICE_UUID,
    STATUS_UUID,
    USER_EVENT_UUID,
    AudioFrame,
    HostStatus,
    HostStatusPacket,
    ProtocolError,
    StatusEvent,
    StatusPacket,
)
from .recognizers import FasterWhisperRecognizer, create_recognizer
from .telemetry import audio_metrics, make_telemetry, write_telemetry
from .types import RecognitionContext, Recognizer, TextInjector, TranscriptSegment

# Compatibility name for code that imported the old recognizer directly.
LocalRecognizer = FasterWhisperRecognizer
LOGGER = logging.getLogger("ble_stt.runtime")
MAPPING_SYNC_INTERVAL = 2.0


@dataclass
class SpeechSession:
    session_id: int
    focus_window: object | None
    mode: str = "dictation"
    audio: list[int] = field(default_factory=list)
    audio_cursor: int = 0
    expected_sequence: int = 0
    previous_segments: list[TranscriptSegment] = field(default_factory=list)
    last_inference_size: int = 0
    has_output: bool = False
    injection_enabled: bool = True
    inference_pending: bool = False


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
    def __init__(
        self,
        recognizer: Recognizer | None,
        injector: TextInjector,
        interval: float,
        stable_lag: float,
        once: bool = False,
    ) -> None:
        self.recognizer = recognizer
        self.interval = interval
        self.stable_lag = stable_lag
        self.injector = injector
        self.session: SpeechSession | None = None
        self.once = once
        self.completed = asyncio.Event()
        self.test_succeeded = False
        self._host_status_writer: Callable[[HostStatus, int], Awaitable[None]] | None = None
        self._action_writer: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self.inference_lock = asyncio.Lock()
        self._rolling_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._last_audio_telemetry_at = 0.0
        self._last_text: dict[str, object] | None = None
        self._last_command: dict[str, object] | None = None
        self._last_ready_session_id: int | None = None
        self._pending_speech_mode: tuple[str, float] | None = None
        self._link_ready = False

    def start(self) -> None:
        self._rolling_task = asyncio.create_task(self._rolling_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def set_host_status_writer(self, writer: Callable[[HostStatus, int], Awaitable[None]] | None) -> None:
        self._host_status_writer = writer

    def set_action_writer(self, writer: Callable[[dict[str, Any]], Awaitable[None]] | None) -> None:
        self._action_writer = writer

    def _execute_local_action(self, command: dict[str, Any], session: SpeechSession) -> bool:
        action = str(command.get("action", ""))
        if action != "hid.keyboard.tap":
            LOGGER.info("local command fallback does not support action=%s", action)
            return False
        tap_key = getattr(self.injector, "tap_key", None)
        if not callable(tap_key):
            LOGGER.info("local command fallback is unavailable for this platform")
            return False
        return bool(tap_key(int(command.get("param0", 0)), int(command.get("param1", 0)), session.focus_window))

    def report_host_status(self, status: HostStatus, error: int = 0) -> None:
        if self._host_status_writer is not None:
            asyncio.create_task(self._host_status_writer(status, error))

    def _set_pending_speech_mode(self, mode: str) -> None:
        self._pending_speech_mode = (mode, time.monotonic())

    def _consume_pending_speech_mode(self) -> str:
        pending = self._pending_speech_mode
        self._pending_speech_mode = None
        if pending is None:
            return "dictation"
        mode, created_at = pending
        if time.monotonic() - created_at > 2.0:
            return "dictation"
        return mode

    def receive_user_event(self, raw: bytes) -> dict[str, Any] | None:
        try:
            packet = parse_user_event_packet(raw)
        except ProtocolError as exc:
            LOGGER.warning("invalid user event packet: %s", exc)
            return None
        LOGGER.info(
            "watch event event=%s action=%s handled=%s value=%s sequence=%s",
            packet["event"],
            packet["action"],
            packet["handled"],
            packet["value"],
            packet["sequence"],
        )
        if packet["action"] == "voice.command.start":
            self._set_pending_speech_mode("command")
        elif packet["action"] == "voice.hold.start":
            self._set_pending_speech_mode("dictation")
        return packet

    def _publish_telemetry(
        self,
        *,
        stage: str,
        session_id: int | None = None,
        audio: dict[str, float | int] | None = None,
        recognition_busy: bool = False,
        recognition_mode: str = "idle",
        last_text: dict[str, object] | None = None,
        last_command: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        try:
            write_telemetry(
                make_telemetry(
                    stage=stage,
                    session_id=session_id,
                    audio=audio,
                    recognition_busy=recognition_busy,
                    recognition_mode=recognition_mode,
                    last_text=last_text if last_text is not None else self._last_text,
                    last_command=last_command if last_command is not None else self._last_command,
                    error=error,
                )
            )
        except Exception:
            LOGGER.debug("could not write runtime telemetry", exc_info=True)

    def mark_ready(self, session_id: int | None = None) -> None:
        if session_id is not None:
            self._last_ready_session_id = session_id
        self._link_ready = True
        if self.session is None and self.recognizer is not None:
            self._publish_telemetry(stage="ready", session_id=self._last_ready_session_id)

    def mark_disconnected(self, reason: str) -> None:
        self._link_ready = False
        if self.session is None:
            self._publish_telemetry(stage="error", session_id=self._last_ready_session_id, error=reason)

    def mark_waiting_for_system_connection(self) -> None:
        self._link_ready = False
        if self.session is None:
            self._publish_telemetry(
                stage="waiting_system_connection",
                session_id=self._last_ready_session_id,
            )

    def _session_audio_payload(
        self,
        session: SpeechSession,
        frame_pcm: list[int] | None = None,
    ) -> dict[str, float | int]:
        metrics = audio_metrics(frame_pcm or session.audio[-320:])
        return {
            **metrics,
            "seconds": round(len(session.audio) / 16000.0, 2),
            "frames": len(session.audio) // 320,
        }

    async def _restore_ready(self, delay: float = 5.0) -> None:
        await asyncio.sleep(delay)
        if self.session is None:
            self.report_host_status(HostStatus.READY)

    async def close(self) -> None:
        if self._rolling_task:
            self._rolling_task.cancel()
            try:
                await self._rolling_task
            except asyncio.CancelledError:
                pass
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self.abort("helper stopped")

    def receive_status(self, raw: bytes) -> None:
        try:
            status = StatusPacket.parse(raw)
        except ProtocolError as exc:
            LOGGER.warning("invalid status packet: %s", exc)
            print(f"[protocol] {exc}")
            return
        if status.event == StatusEvent.READY:
            LOGGER.info("watch status ready session=%s error=%s", status.session_id, status.error)
            print("[device] speech input ready; hold the right button to talk")
            if self.session is None:
                self.mark_ready(status.session_id)
        elif status.event == StatusEvent.START:
            if self.session is not None:
                self.abort("new speech session started")
            mode = self._consume_pending_speech_mode()
            self.session = SpeechSession(
                status.session_id,
                self.injector.active_window(),
                mode=mode,
                injection_enabled=mode != "command",
            )
            self._last_audio_telemetry_at = 0.0
            LOGGER.info("speech session started session=%s mode=%s", status.session_id, mode)
            print(f"[speech {status.session_id}] listening ({mode})")
            self._publish_telemetry(
                stage="listening",
                session_id=status.session_id,
                audio=self._session_audio_payload(self.session),
                recognition_mode=mode,
            )
        elif status.event == StatusEvent.END:
            session = self.session
            if session and session.session_id == status.session_id:
                self.session = None
                LOGGER.info(
                    "speech session ended by watch session=%s samples=%s",
                    session.session_id,
                    len(session.audio),
                )
                self.report_host_status(HostStatus.RECOGNIZING)
                self._publish_telemetry(
                    stage="recognizing",
                    session_id=session.session_id,
                    audio=self._session_audio_payload(session),
                    recognition_busy=True,
                    recognition_mode="final",
                )
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
                    LOGGER.warning(
                        "filled missing audio frames session=%s missing=%s sequence=%s",
                        session.session_id,
                        missing,
                        frame.sequence,
                    )
                    print(f"[speech {session.session_id}] filled {missing} missing frame(s) with silence")
                else:
                    self.abort(f"lost {missing} consecutive audio frames")
                    return
            decoded = frame.decode()
            session.audio.extend(decoded)
            session.expected_sequence = (frame.sequence + 1) & 0xFFFF
            now = time.monotonic()
            if now - self._last_audio_telemetry_at >= 0.08:
                self._last_audio_telemetry_at = now
                self._publish_telemetry(
                    stage="listening",
                    session_id=session.session_id,
                    audio=self._session_audio_payload(session, decoded),
                    recognition_busy=session.inference_pending,
                    recognition_mode=session.mode if session.mode == "command" else ("rolling" if session.inference_pending else "idle"),
                )
        except ProtocolError as exc:
            LOGGER.warning("audio protocol error session=%s error=%s", session.session_id, exc)
            self.abort(str(exc))

    def abort(self, reason: str) -> None:
        if self.session is not None:
            LOGGER.warning("speech session aborted session=%s reason=%s", self.session.session_id, reason)
            print(f"[speech {self.session.session_id}] aborted: {reason}")
            self._publish_telemetry(
                stage="error",
                session_id=self.session.session_id,
                audio=self._session_audio_payload(self.session),
                error=reason,
            )
            self.session = None

    async def _rolling_loop(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            session = self.session
            if session is None or session.inference_pending:
                continue
            if session.mode == "command":
                continue
            available = len(session.audio) - session.audio_cursor
            growth = len(session.audio) - session.last_inference_size
            if available < 16000 or growth < int(self.interval * 16000):
                continue
            session.last_inference_size = len(session.audio)
            session.inference_pending = True
            self._publish_telemetry(
                stage="listening",
                session_id=session.session_id,
                audio=self._session_audio_payload(session),
                recognition_busy=True,
                recognition_mode="rolling",
            )
            asyncio.create_task(self._recognize_stable(session))

    def _recognition_context(self, session: SpeechSession) -> RecognitionContext:
        if session.mode != "command":
            return RecognitionContext(mode="dictation")
        commands = read_commands(UserConfig()).get("entries", [])
        phrases: list[str] = []
        for command in commands:
            phrases.append(str(command.get("phrase", "")))
            phrases.extend(str(alias) for alias in command.get("aliases", []))
        return RecognitionContext(mode="command", command_phrases=tuple(phrase for phrase in phrases if phrase))

    async def _recognize(self, pcm: list[int], context: RecognitionContext | None = None) -> list[TranscriptSegment]:
        if self.recognizer is None:
            raise RuntimeError("speech model is not ready")
        async with self.inference_lock:
            return await asyncio.to_thread(self.recognizer.transcribe, pcm, context)

    async def _recognize_stable(self, session: SpeechSession) -> None:
        try:
            if self.session is not session:
                return
            snapshot = session.audio[session.audio_cursor :]
            segments = await self._recognize(snapshot, self._recognition_context(session))
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
                    self._last_text = {
                        "text": text,
                        "final": False,
                        "time": time.time(),
                    }
                    self._publish_telemetry(
                        stage="listening",
                        session_id=session.session_id,
                        audio=self._session_audio_payload(session),
                        recognition_busy=False,
                        recognition_mode="rolling",
                    )
                    session.has_output = True
            advance = min(len(snapshot), max(1, int(committed_segments[-1].end * 16000)))
            session.audio_cursor += advance
            session.previous_segments = []
            session.last_inference_size = session.audio_cursor
        except Exception as exc:
            LOGGER.exception(
                "rolling recognition failed session=%s samples=%s",
                session.session_id,
                len(session.audio),
            )
            if self.session is session:
                self.abort(f"recognition failed: {exc}")
                self.report_host_status(HostStatus.MODEL_ERROR, 1)
                if not self.once:
                    asyncio.create_task(self._restore_ready())
        finally:
            session.inference_pending = False

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(3.0)
            if self._link_ready and self.session is None and self.recognizer is not None:
                self._publish_telemetry(stage="ready", session_id=self._last_ready_session_id)

    async def _finalize(self, session: SpeechSession) -> None:
        snapshot = session.audio[session.audio_cursor :]
        succeeded = session.has_output
        self._publish_telemetry(
            stage="recognizing",
            session_id=session.session_id,
            audio=self._session_audio_payload(session),
            recognition_busy=True,
            recognition_mode="final",
        )
        try:
            segments = await self._recognize(snapshot, self._recognition_context(session))
        except Exception as exc:
            LOGGER.exception(
                "final recognition failed session=%s samples=%s",
                session.session_id,
                len(snapshot),
            )
            print(f"[speech {session.session_id}] final recognition failed: {exc}")
            self._publish_telemetry(
                stage="error",
                session_id=session.session_id,
                audio=self._session_audio_payload(session),
                recognition_busy=False,
                recognition_mode="final",
                error=str(exc),
            )
            self.report_host_status(HostStatus.MODEL_ERROR, 1)
            if not self.once:
                asyncio.create_task(self._restore_ready())
        else:
            if session.mode == "command":
                text = output_text(segments, False)
                commands = read_commands(UserConfig()).get("entries", [])
                result = match_command(text, commands)
                self._last_command = {
                    "text": text,
                    "matched": result.matched,
                    "phrase": result.command.get("phrase") if result.command else None,
                    "action": result.command.get("action") if result.command else None,
                    "score": result.score,
                    "reason": result.reason,
                    "time": time.time(),
                }
                if result.matched and result.command is not None and self._action_writer is not None:
                    try:
                        await self._action_writer(result.command)
                        succeeded = True
                        LOGGER.info(
                            "command executed session=%s phrase=%s action=%s score=%.3f transcript=%s",
                            session.session_id,
                            result.command.get("phrase"),
                            result.command.get("action"),
                            result.score,
                            text,
                        )
                        print(
                            f"[command] {text} -> {result.command.get('phrase')} "
                            f"({result.command.get('action')})"
                        )
                    except Exception as exc:
                        LOGGER.exception("command action failed session=%s", session.session_id)
                        print(f"[command] action failed: {exc}")
                        self._last_command = {**self._last_command, "error": str(exc)}
                elif result.matched and result.command is not None:
                    try:
                        succeeded = self._execute_local_action(result.command, session)
                    except Exception as exc:
                        LOGGER.exception("local command action failed session=%s", session.session_id)
                        print(f"[command] local action failed: {exc}")
                        self._last_command = {**self._last_command, "error": str(exc)}
                    else:
                        if succeeded:
                            LOGGER.info(
                                "command executed locally session=%s phrase=%s action=%s score=%.3f transcript=%s",
                                session.session_id,
                                result.command.get("phrase"),
                                result.command.get("action"),
                                result.score,
                                text,
                            )
                            print(
                                f"[command] {text} -> {result.command.get('phrase')} "
                                f"({result.command.get('action')}, local)"
                            )
                        else:
                            LOGGER.warning("command matched but no action executor is available")
                            print("[command] action execution is unavailable")
                            self._last_command = {**self._last_command, "error": "action executor unavailable"}
                else:
                    LOGGER.info(
                        "command not matched session=%s score=%.3f reason=%s transcript=%s",
                        session.session_id,
                        result.score,
                        result.reason,
                        text,
                    )
                    print(f"[command] no match ({result.reason}): {text}")

                elapsed = len(session.audio) / 16000.0
                print(f"[speech {session.session_id}] finished ({elapsed:.1f}s)")
                self._publish_telemetry(
                    stage="ready",
                    session_id=session.session_id,
                    audio=self._session_audio_payload(session),
                    recognition_busy=False,
                    recognition_mode="command",
                    last_command=self._last_command,
                )
                self.report_host_status(HostStatus.READY)
                if self.once:
                    self.test_succeeded = succeeded
                    self.completed.set()
                return

            text = output_text(segments, session.has_output)
            if session.injection_enabled and text:
                try:
                    session.injection_enabled = self.injector.type_text(text, session.focus_window)
                    if session.injection_enabled:
                        print(f"[text final] {text}")
                        self._last_text = {
                            "text": text,
                            "final": True,
                            "time": time.time(),
                        }
                        succeeded = True
                except Exception as exc:
                    LOGGER.exception("text insertion failed session=%s", session.session_id)
                    print(f"[text] insertion failed: {exc}")
                    session.injection_enabled = False
                    self._publish_telemetry(
                        stage="error",
                        session_id=session.session_id,
                        audio=self._session_audio_payload(session),
                        recognition_busy=False,
                        recognition_mode="inserting",
                        error=str(exc),
                    )
                    status = (
                        HostStatus.PERMISSION_ERROR
                        if "permission" in str(exc).lower()
                        else HostStatus.HOST_ERROR
                    )
                    self.report_host_status(status, 1)
                    if not self.once:
                        asyncio.create_task(self._restore_ready(10.0))
            elapsed = len(session.audio) / 16000.0
            LOGGER.info(
                "speech session finalized session=%s elapsed=%.1fs text_inserted=%s injection_enabled=%s",
                session.session_id,
                elapsed,
                succeeded,
                session.injection_enabled,
            )
            print(f"[speech {session.session_id}] finished ({elapsed:.1f}s)")
            self._publish_telemetry(
                stage="inserted" if succeeded else "ready",
                session_id=session.session_id,
                audio=self._session_audio_payload(session),
                recognition_busy=False,
                recognition_mode="complete",
            )
            if succeeded or not self.once:
                self.report_host_status(HostStatus.READY)
            elif session.injection_enabled:
                self.report_host_status(HostStatus.HOST_ERROR, 1)
        if self.once:
            self.test_succeeded = succeeded
            self.completed.set()


async def find_device(identifier: str | None, adapter: PlatformAdapter | None = None):
    return await (adapter or create_platform()).find_device(identifier)


async def acquire_mtu(client: Any, adapter: PlatformAdapter | None = None) -> int:
    return await (adapter or create_platform()).acquire_mtu(client)


async def use_cached_bluez_device(
    client: Any,
    device: Any,
    adapter: PlatformAdapter | None = None,
) -> None:
    # Compatibility wrapper retained for ble_stt.check and external callers.
    await (adapter or create_platform()).prepare_client(client, device)


def _ensure_bluetooth_permission(adapter: PlatformAdapter) -> None:
    check_permission = getattr(adapter, "check_bluetooth_permission", None)
    if not callable(check_permission):
        return
    passed, message = check_permission(False)
    if not passed:
        raise RuntimeError(str(message))


def _is_bluetooth_permission_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "bluetooth permission" in message or "bluetooth access" in message


async def _mapping_sync_loop(client: Any, characteristic: Any) -> None:
    last_revision: int | None = None
    while client.is_connected:
        try:
            mapping = read_mapping(UserConfig())
            revision = int(mapping.get("revision", 0))
            if revision != last_revision:
                await client.write_gatt_char(characteristic, encode_mapping(mapping), response=True)
                LOGGER.info("mapping synced revision=%s records=%s", revision, len(mapping.get("entries", [])))
                print(f"[mapping] synced revision {revision}")
                last_revision = revision
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("mapping sync failed: %s", exc)
            print(f"[mapping] sync failed: {exc}")
        await asyncio.sleep(MAPPING_SYNC_INTERVAL)


async def run_ble(
    controller: SpeechController,
    identifier: str | None,
    adapter: PlatformAdapter,
    recognizer_factory: Callable[[], Recognizer] | None = None,
    runtime_validator: Callable[[], None] | None = None,
) -> None:
    from bleak import BleakClient

    while True:
        disconnect_event = asyncio.Event()
        device: Any = None
        try:
            _ensure_bluetooth_permission(adapter)
            LOGGER.info("waiting for operating-system HID connection")
            controller.mark_waiting_for_system_connection()
            device = await adapter.wait_for_system_connection(identifier)
            LOGGER.info("attaching speech GATT client to system-connected device=%r", device)
            print(f"[ble] attaching voice service to {device}")
            client = BleakClient(device, disconnected_callback=lambda _: disconnect_event.set(), timeout=60)
            await adapter.prepare_client(client, device)
            async with client:
                service_uuids = {str(service.uuid).lower() for service in client.services}
                if SERVICE_UUID not in service_uuids:
                    LOGGER.warning("speech service missing services=%s", sorted(service_uuids))
                    raise RuntimeError(
                        "Speech GATT service is missing. Forget the device on both sides, reopen BLE Remote, "
                        "and pair again."
                    )
                control_service_present = CONTROL_SERVICE_UUID in service_uuids
                # Reading the encrypted status characteristic restores or initiates pairing.
                await client.read_gatt_char(STATUS_UUID)
                mtu = await adapter.acquire_mtu(client)
                if mtu < 185:
                    raise RuntimeError(f"negotiated MTU {mtu} is too small for speech audio (need 185)")
                await adapter.record_connected(device)
                LOGGER.info(
                    "connected mtu=%s control_service=%s services=%s",
                    mtu,
                    control_service_present,
                    sorted(service_uuids),
                )
                print(f"[ble] connected, MTU {mtu}")
                await client.start_notify(STATUS_UUID, lambda _, data: controller.receive_status(bytes(data)))
                await client.start_notify(AUDIO_UUID, lambda _, data: controller.receive_audio(bytes(data)))
                host_characteristic = client.services.get_characteristic(HOST_STATUS_UUID)
                mapping_characteristic = client.services.get_characteristic(MAPPING_CONFIG_UUID)
                user_event_characteristic = client.services.get_characteristic(USER_EVENT_UUID)
                action_characteristic = client.services.get_characteristic(ACTION_EXEC_UUID)

                if user_event_characteristic is not None:
                    def receive_user_event(_: Any, data: bytearray) -> None:
                        controller.receive_user_event(bytes(data))

                    await client.start_notify(USER_EVENT_UUID, receive_user_event)

                mapping_task: asyncio.Task[None] | None = None
                if mapping_characteristic is not None:
                    mapping_task = asyncio.create_task(_mapping_sync_loop(client, mapping_characteristic))
                else:
                    LOGGER.info(
                        "watch firmware does not expose mapping config characteristic control_service=%s",
                        control_service_present,
                    )

                async def write_host_status(status: HostStatus, error: int = 0) -> None:
                    if host_characteristic is None or not client.is_connected:
                        return
                    try:
                        packet = HostStatusPacket(status, error).build()
                        await client.write_gatt_char(host_characteristic, packet, response=True)
                        LOGGER.debug("host status sent status=%s error=%s", status.name, error)
                    except Exception as exc:
                        LOGGER.exception(
                            "could not update watch status status=%s error=%s",
                            status.name,
                            error,
                        )
                        print(f"[ble] could not update watch status: {exc}")

                async def write_action(command: dict[str, Any]) -> None:
                    if action_characteristic is None or not client.is_connected:
                        raise RuntimeError("watch firmware does not support host command actions")
                    packet = encode_command_action(command)
                    await client.write_gatt_char(action_characteristic, packet, response=True)
                    LOGGER.info("host command action sent action=%s", command.get("action"))

                controller.set_host_status_writer(write_host_status)
                controller.set_action_writer(write_action if action_characteristic is not None else None)
                if action_characteristic is None:
                    LOGGER.info("watch command action characteristic is unavailable; local fallback will be used")
                try:
                    if runtime_validator is not None:
                        while True:
                            try:
                                runtime_validator()
                                break
                            except Exception as exc:
                                LOGGER.warning("runtime requirement not ready: %s", exc)
                                print(f"[host] runtime requirement is not ready: {exc}")
                                message = str(exc).lower()
                                status = (
                                    HostStatus.PERMISSION_ERROR
                                    if "permission" in message or "accessibility" in message
                                    else HostStatus.HOST_ERROR
                                )
                                await write_host_status(status, 1)
                                await asyncio.sleep(10)
                                if not client.is_connected:
                                    raise RuntimeError(
                                        "Bluetooth disconnected while waiting for host requirements"
                                    )
                    if controller.recognizer is None:
                        while controller.recognizer is None:
                            await write_host_status(HostStatus.PREPARING)
                            try:
                                if recognizer_factory is None:
                                    raise RuntimeError("speech recognizer factory is missing")
                                controller.recognizer = await asyncio.to_thread(recognizer_factory)
                            except Exception as exc:
                                LOGGER.exception("model preparation failed")
                                print(f"[model] preparation failed: {exc}; retrying in 10s")
                                await write_host_status(HostStatus.MODEL_ERROR, 1)
                                await asyncio.sleep(10)
                                if not client.is_connected:
                                    raise RuntimeError("Bluetooth disconnected while preparing the model")
                    await write_host_status(HostStatus.READY)
                    controller.mark_ready()
                    if controller.once:
                        disconnect_task = asyncio.create_task(disconnect_event.wait())
                        complete_task = asyncio.create_task(controller.completed.wait())
                        done, pending = await asyncio.wait(
                            (disconnect_task, complete_task), return_when=asyncio.FIRST_COMPLETED
                        )
                        for task in pending:
                            task.cancel()
                        if complete_task in done:
                            return
                    else:
                        await disconnect_event.wait()
                finally:
                    if mapping_task is not None:
                        mapping_task.cancel()
                        try:
                            await mapping_task
                        except asyncio.CancelledError:
                            pass
            controller.abort("Bluetooth disconnected")
            controller.mark_disconnected("Bluetooth disconnected")
            controller.set_host_status_writer(None)
            controller.set_action_writer(None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
            if _is_bluetooth_permission_error(exc):
                LOGGER.warning("Bluetooth permission not ready: %s", detail)
            elif device is None:
                LOGGER.warning("system-connected watch lookup failed: %s", detail)
            else:
                LOGGER.warning("speech GATT attachment ended: %s", detail)
            print(f"[ble] {detail}; returning to system connection wait")
            controller.abort("Bluetooth disconnected")
            controller.mark_disconnected(detail)
            controller.set_host_status_writer(None)
            controller.set_action_writer(None)
            if controller.once and controller.completed.is_set():
                return
            await asyncio.sleep(2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ble-stt run", description="M5StopWatch BLE push-to-talk helper")
    parser.add_argument(
        "--device-id",
        "--address",
        dest="device_id",
        help="cached platform device identifier (Bluetooth address, or CoreBluetooth UUID on macOS)",
    )
    parser.add_argument("--engine", choices=("auto", "faster-whisper", "mlx"), default=None)
    parser.add_argument(
        "--model",
        default=None,
        help="Whisper model name or repository/path (default: configured model, or small)",
    )
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--cpu-threads", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    parser.add_argument("--interval", type=float, default=1.0, help="minimum seconds of new audio per pass")
    parser.add_argument("--stable-lag", type=float, default=0.8, help="uncommitted audio tail in seconds")
    parser.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def apply_runtime_defaults(args: argparse.Namespace, config: UserConfig | None = None) -> argparse.Namespace:
    config = config or UserConfig()
    if args.engine is None:
        args.engine = str(config.get("engine", DEFAULT_ENGINE))
    if args.model is None:
        args.model = str(config.get("model", DEFAULT_MODEL))
    return args


def _create_configured_recognizer(args: argparse.Namespace, config: UserConfig) -> Recognizer:
    status = model_status(config, args.engine, args.model)
    resolved_model = runtime_model_name(args.engine, args.model, config)
    recognizer = create_recognizer(args.engine, resolved_model, args.device, args.cpu_threads)
    resolved_path = Path(resolved_model).expanduser()
    source = status.source
    if source not in {"bundled", "custom", "downloaded"}:
        source = "custom" if resolved_path.exists() else "downloaded"
    cache_path = Path(status.cache_dir).expanduser() if status.cache_dir else None
    record_model_ready(
        args.engine,
        args.model,
        resolved_model,
        config=config,
        source=source,
        cache_path=cache_path,
    )
    return recognizer


async def async_main(args: argparse.Namespace) -> None:
    config = UserConfig()
    args = apply_runtime_defaults(args, config)
    with runtime_logging("run", vars(args)):
        LOGGER.info(
            "runtime options engine=%s model=%s device=%s cpu_threads=%s once=%s",
            args.engine,
            args.model,
            args.device,
            args.cpu_threads,
            args.once,
        )
        adapter = create_platform()
        controller = SpeechController(
            None,
            adapter.create_text_injector(),
            args.interval,
            args.stable_lag,
            once=args.once,
        )
        controller.start()
        try:
            await run_ble(
                controller,
                args.device_id,
                adapter,
                lambda: _create_configured_recognizer(args, config),
                adapter.validate_runtime,
            )
            if args.once and not controller.test_succeeded:
                raise RuntimeError("test speech was not recognized or could not be inserted")
        finally:
            await controller.close()


def main(argv: Sequence[str] | None = None) -> None:
    try:
        asyncio.run(async_main(parse_args(argv)))
    except KeyboardInterrupt:
        print("\nStopped", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
