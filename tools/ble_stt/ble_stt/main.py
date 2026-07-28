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
from .correction import ConservativeCorrector, graphemes, normalize_transcript
from .diagnostics import runtime_logging
from .lexicon import merge_prompt_terms
from .mapping import encode_mapping, parse_user_event_packet, read_mapping
from .models import DEFAULT_ENGINE, DEFAULT_MODEL, model_status, record_model_ready, runtime_model_name
from .platforms import PlatformAdapter, create_platform
from .protocol import (
    AUDIO_UUID,
    ACTION_EXEC_UUID,
    CONTROL_SERVICE_UUID,
    HOST_STATUS_UUID,
    MAPPING_CONFIG_UUID,
    PERFORMANCE_UUID,
    SERVICE_UUID,
    STATUS_UUID,
    USER_EVENT_UUID,
    AudioFrame,
    HostStatus,
    HostStatusPacket,
    ProtocolError,
    StatusEvent,
    StatusPacket,
    PerformanceConnectionSummary,
    PerformanceSessionSummary,
    PerformanceSyncRequest,
    PerformanceSyncResponse,
    parse_performance_packet,
)
from .performance import ClockSynchronizer, PerformanceTrace, append_performance, read_performance
from .recognizers import FasterWhisperRecognizer, create_recognizer
from .telemetry import audio_metrics, make_telemetry, write_telemetry
from .preferences import VoicePreferences, read_voice_preferences
from .typing_output import AnimatedTextWriter
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
    preferences: VoicePreferences | None = None
    output_writer: AnimatedTextWriter | None = None
    performance: PerformanceTrace | None = None


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


def common_grapheme_prefix(left: str, right: str) -> str:
    result: list[str] = []
    for left_value, right_value in zip(graphemes(left), graphemes(right)):
        if left_value != right_value:
            break
        result.append(left_value)
    return "".join(result)


class SpeechController:
    def __init__(
        self,
        recognizer: Recognizer | None,
        injector: TextInjector,
        interval: float,
        stable_lag: float,
        once: bool = False,
        config: UserConfig | None = None,
        corrector: ConservativeCorrector | None = None,
    ) -> None:
        self.recognizer = recognizer
        self.interval = interval
        self.stable_lag = stable_lag
        self.injector = injector
        self.session: SpeechSession | None = None
        self.once = once
        self.config = config or UserConfig()
        self.corrector = corrector or ConservativeCorrector()
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
        self._pending_performance: PerformanceTrace | None = None
        self._performance_by_session: dict[int, PerformanceTrace] = {}
        self._active_lifecycle: PerformanceTrace | None = None
        self._pending_connection_summary: PerformanceConnectionSummary | None = None
        self._clock_sync = ClockSynchronizer()
        self._performance_sync_attempted = False
        self._performance_revision = int(read_performance().get("revision", 0))
        self._latest_performance: dict[str, object] | None = None
        self._link_ready = False

    def start(self) -> None:
        self._rolling_task = asyncio.create_task(self._rolling_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def set_host_status_writer(self, writer: Callable[[HostStatus, int], Awaitable[None]] | None) -> None:
        self._host_status_writer = writer

    def set_action_writer(self, writer: Callable[[dict[str, Any]], Awaitable[None]] | None) -> None:
        self._action_writer = writer

    def _performance_configuration(self) -> dict[str, object]:
        preferences = read_voice_preferences(self.config)
        return {
            "engine": str(self.config.get("engine", DEFAULT_ENGINE)),
            "stt_model": str(self.config.get("model", DEFAULT_MODEL)),
            "correction_enabled": preferences.correction.enabled,
            "correction_model": preferences.correction.model if preferences.correction.enabled else None,
            "typing_enabled": preferences.typing.enabled,
            "typing_characters_per_second": preferences.typing.characters_per_second,
        }

    def _new_performance_trace(self, kind: str, *, mode: str | None = None) -> PerformanceTrace:
        return PerformanceTrace(kind, mode=mode, configuration=self._performance_configuration())

    def _finish_performance(
        self,
        trace: PerformanceTrace | None,
        outcome: str,
        *,
        error_code: str | None = None,
    ) -> dict[str, object] | None:
        if trace is None or trace.finished:
            return None
        for name, start, end, lane, category in (
            ("button_event_to_start", "user_event_received", "status_start_received", "ble", "io"),
            ("start_to_first_audio", "status_start_received", "first_audio_received", "ble", "io"),
            ("last_audio_to_end", "last_audio_received", "status_end_received", "ble", "io"),
            ("final_pipeline", "status_end_received", "result_ready", "host", "work"),
            ("typing_animation", "result_ready", "typing_complete", "output", "intentional"),
        ):
            trace.add_span_between(name, start, end, lane=lane, category=category)
        for name, start, end in (
            ("press_to_listening_ms", "device_button_down", "status_start_received"),
            ("press_to_first_audio_ms", "device_button_down", "first_audio_received"),
            ("start_to_first_character_ms", "status_start_received", "first_text_visible"),
            ("release_to_result_ready_ms", "device_release_detected", "result_ready"),
            ("release_to_typing_complete_ms", "device_release_detected", "typing_complete"),
            ("host_release_to_result_ready_ms", "release_event_received", "result_ready"),
            ("host_release_to_typing_complete_ms", "release_event_received", "typing_complete"),
            ("command_release_to_action_ms", "release_event_received", "command_action_complete"),
        ):
            trace.set_metric_between(name, start, end)
        record = trace.finish(outcome, error_code=error_code)
        try:
            payload = append_performance(record)
            self._performance_revision = int(payload.get("revision", self._performance_revision + 1))
        except Exception:
            LOGGER.debug("could not persist performance trace", exc_info=True)
        self._latest_performance = {
            "trace_id": record["trace_id"],
            "kind": record["kind"],
            "session_id": record["session_id"],
            "mode": record["mode"],
            "outcome": record["outcome"],
            "duration_ms": record["duration_ms"],
            "metrics": record["metrics"],
        }
        if trace.session_id is not None:
            self._performance_by_session.pop(trace.session_id, None)
        if self._active_lifecycle is trace:
            self._active_lifecycle = None
        return record

    def begin_clock_sync(self, sequence: int, host_send_ns: int | None = None) -> int:
        return self._clock_sync.begin(sequence, host_send_ns)

    def begin_lifecycle_performance(self, trace: PerformanceTrace) -> None:
        self._active_lifecycle = trace
        self._pending_connection_summary = None
        self._clock_sync = ClockSynchronizer()
        self._performance_sync_attempted = False

    def complete_performance_sync_batch(self) -> None:
        self._performance_sync_attempted = True
        trace = self._active_lifecycle
        if trace is not None:
            trace.clock_sync = self._clock_sync.payload()
        if self._pending_connection_summary is not None:
            self._attach_connection_summary(self._pending_connection_summary)
        if trace is not None and "host_ready" in trace.milestones:
            self._finish_performance(trace, "ready")

    def mark_lifecycle_ready(self, trace: PerformanceTrace, *, performance_supported: bool) -> None:
        trace.mark("host_ready")
        if not performance_supported or self._performance_sync_attempted:
            self._finish_performance(trace, "ready")

    def clock_sync_payload(self) -> dict[str, object]:
        return self._clock_sync.payload()

    def _attach_device_summary(self, summary: PerformanceSessionSummary) -> None:
        trace = self._performance_by_session.get(summary.session_id)
        if trace is None:
            return
        trace.clock_sync = self._clock_sync.payload()
        converted: dict[str, int] = {}
        for name, timestamp_us in summary.timestamps_us.items():
            if timestamp_us is None:
                continue
            host_ns = self._clock_sync.device_to_host_ns(timestamp_us)
            if host_ns is not None:
                converted[name] = host_ns
                trace.mark(f"device_{name}", host_ns)
        device_spans = (
            ("hold_threshold", "button_down", "hold_triggered", "wait"),
            ("vibration_guard", "speech_scheduled", "speech_start_call", "intentional"),
            ("speech_start_setup", "speech_start_call", "status_start_sent", "work"),
            ("worker_dispatch", "status_start_sent", "worker_started", "work"),
            ("first_capture", "worker_started", "first_capture_done", "io"),
            ("first_resample", "first_capture_done", "first_resample_done", "work"),
            ("first_encode", "first_resample_done", "first_encode_done", "work"),
            ("first_ble_enqueue", "first_encode_done", "first_audio_sent", "io"),
            ("release_to_stop", "release_detected", "stop_requested", "work"),
            ("stop_to_worker_exit", "stop_requested", "worker_exited", "io"),
            ("end_status_enqueue", "worker_exited", "status_end_sent", "io"),
        )
        for span_name, start_name, end_name, category in device_spans:
            start = converted.get(start_name)
            end = converted.get(end_name)
            if start is not None and end is not None and end >= start:
                trace.add_span_ns(span_name, start, end, lane="device", category=category)
                continue
            raw_start = summary.timestamps_us.get(start_name)
            raw_end = summary.timestamps_us.get(end_name)
            if raw_start is not None and raw_end is not None and raw_end >= raw_start:
                trace.observe(
                    span_name,
                    (raw_end - raw_start) / 1000.0,
                    lane="device",
                    category=category,
                )
        count = max(1, summary.frame_count)
        for name, values in summary.aggregates_us.items():
            trace.observe(
                f"device_{name}",
                values["total"] / 1000.0,
                lane="device",
                category="io" if name in {"capture", "notify"} else "work",
            )
            trace.metrics[f"device_{name}_mean_ms"] = round(values["total"] / count / 1000.0, 3)
            trace.metrics[f"device_{name}_max_ms"] = round(values["max"] / 1000.0, 3)
        trace.metrics["device_frame_count"] = summary.frame_count
        trace.metrics["device_notify_failures"] = summary.notify_failures

    def receive_performance(self, raw: bytes) -> object | None:
        received_ns = time.monotonic_ns()
        try:
            packet = parse_performance_packet(raw)
        except ProtocolError as exc:
            LOGGER.warning("invalid performance packet: %s", exc)
            return None
        if isinstance(packet, PerformanceSyncResponse):
            self._clock_sync.complete(
                packet.sequence,
                packet.device_receive_us,
                packet.device_send_us,
                received_ns,
            )
            if self._pending_connection_summary is not None:
                self._attach_connection_summary(self._pending_connection_summary)
        elif isinstance(packet, PerformanceSessionSummary):
            self._attach_device_summary(packet)
        elif isinstance(packet, PerformanceConnectionSummary):
            self._pending_connection_summary = packet
            self._attach_connection_summary(packet)
            LOGGER.debug("received device connection timing summary fields=%s", len(packet.timestamps_us))
        return packet

    def _attach_connection_summary(self, packet: PerformanceConnectionSummary) -> None:
        trace = self._active_lifecycle
        if trace is None or self._clock_sync.best is None:
            return
        converted: dict[str, int] = {}
        for name, timestamp_us in packet.timestamps_us.items():
            if timestamp_us is None:
                continue
            host_ns = self._clock_sync.device_to_host_ns(timestamp_us)
            if host_ns is not None:
                converted[name] = host_ns
        for name, start, end, category in (
            ("device_advertising_setup", "remote_started", "advertising_started", "work"),
            ("device_connection_wait", "advertising_started", "link_connected", "wait"),
            ("device_security", "link_connected", "encryption_ready", "io"),
            ("device_mtu", "encryption_ready", "mtu_ready", "io"),
            ("device_subscriptions", "mtu_ready", "performance_subscribed", "io"),
        ):
            started = converted.get(start)
            ended = converted.get(end)
            if started is not None and ended is not None and ended >= started:
                trace.add_span_ns(name, started, ended, lane="device", category=category)
                continue
            raw_started = packet.timestamps_us.get(start)
            raw_ended = packet.timestamps_us.get(end)
            if raw_started is not None and raw_ended is not None and raw_ended >= raw_started:
                trace.observe(
                    name,
                    (raw_ended - raw_started) / 1000.0,
                    lane="device",
                    category=category,
                )
        trace.clock_sync = self._clock_sync.payload()
        self._pending_connection_summary = None

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
            self._pending_performance = self._new_performance_trace("session", mode="command")
            self._pending_performance.mark("user_event_received")
        elif packet["action"] == "voice.hold.start":
            self._set_pending_speech_mode("dictation")
            self._pending_performance = self._new_performance_trace("session", mode="dictation")
            self._pending_performance.mark("user_event_received")
        elif packet["action"] in {"voice.command.stop", "voice.hold.stop"}:
            session = self.session
            if session is not None and session.performance is not None:
                session.performance.mark("release_event_received")
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
        current_trace = self.session.performance if self.session is not None else None
        if current_trace is None:
            current_trace = next(
                (trace for trace in reversed(tuple(self._performance_by_session.values())) if not trace.finished),
                None,
            )
        performance = {
            "revision": self._performance_revision,
            "current": current_trace.current_payload() if current_trace is not None and not current_trace.finished else None,
            "latest": self._latest_performance,
        }
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
                    performance=performance,
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
        session = self.session
        self.abort("helper stopped")
        if session is not None and session.output_writer is not None:
            await session.output_writer.close(cancel=True)

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
            trace = self._pending_performance or self._new_performance_trace("session", mode=mode)
            self._pending_performance = None
            trace.session_id = status.session_id
            trace.mode = mode
            trace.mark("status_start_received")
            self._performance_by_session[status.session_id] = trace
            preferences = read_voice_preferences(self.config)
            focus_window = self.injector.active_window()

            def record_typing(_: str, started_ns: int, ended_ns: int) -> None:
                trace.observe("text_inject", (ended_ns - started_ns) / 1_000_000.0, lane="output", category="work")
                if "first_text_visible" not in trace.milestones:
                    trace.mark("first_text_visible", ended_ns)

            writer = (
                AnimatedTextWriter(self.injector, focus_window, preferences.typing, on_timing=record_typing)
                if mode != "command"
                else None
            )
            self.session = SpeechSession(
                status.session_id,
                focus_window,
                mode=mode,
                injection_enabled=mode != "command",
                preferences=preferences,
                output_writer=writer,
                performance=trace,
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
                if session.performance is not None:
                    session.performance.mark("status_end_received")
                    session.performance.mark("finalize_scheduled")
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
        parse_started_ns = time.monotonic_ns()
        try:
            frame = AudioFrame.parse(raw)
            parse_ended_ns = time.monotonic_ns()
            if frame.session_id != session.session_id:
                return
            missing = (frame.sequence - session.expected_sequence) & 0xFFFF
            if missing:
                if session.performance is not None:
                    session.performance.metrics["missing_audio_frames"] = int(
                        session.performance.metrics.get("missing_audio_frames", 0) or 0
                    ) + missing
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
            decode_started_ns = time.monotonic_ns()
            decoded = frame.decode()
            decode_ended_ns = time.monotonic_ns()
            if session.performance is not None:
                session.performance.observe("audio_parse", (parse_ended_ns - parse_started_ns) / 1_000_000.0, lane="ble", category="work")
                session.performance.observe("audio_decode", (decode_ended_ns - decode_started_ns) / 1_000_000.0, lane="ble", category="work")
                if "first_audio_received" not in session.performance.milestones:
                    session.performance.mark("first_audio_received", parse_started_ns)
                session.performance.mark("last_audio_received", parse_started_ns)
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
            writer = self.session.output_writer
            trace = self.session.performance
            if trace is not None:
                trace.mark("aborted")
            LOGGER.warning("speech session aborted session=%s reason=%s", self.session.session_id, reason)
            print(f"[speech {self.session.session_id}] aborted: {reason}")
            self._publish_telemetry(
                stage="error",
                session_id=self.session.session_id,
                audio=self._session_audio_payload(self.session),
                error=reason,
            )
            self.session = None
            self._finish_performance(trace, "aborted", error_code="session_aborted")
            if writer is not None:
                asyncio.create_task(writer.close(cancel=True))

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
            preferences = session.preferences or read_voice_preferences(self.config)
            packs = (
                preferences.correction.lexicon_packs
                if preferences.correction.standard_lexicon_enabled
                else ()
            )
            terms = merge_prompt_terms(preferences.correction.glossary, packs)
            return RecognitionContext(mode="dictation", prompt_terms=terms)
        commands = read_commands(self.config).get("entries", [])
        phrases: list[str] = []
        for command in commands:
            phrases.append(str(command.get("phrase", "")))
            phrases.extend(str(alias) for alias in command.get("aliases", []))
        return RecognitionContext(mode="command", command_phrases=tuple(phrase for phrase in phrases if phrase))

    async def _recognize(
        self,
        pcm: list[int],
        context: RecognitionContext | None = None,
        *,
        trace: PerformanceTrace | None = None,
        span_name: str = "stt",
    ) -> list[TranscriptSegment]:
        if self.recognizer is None:
            raise RuntimeError("speech model is not ready")
        queued_ns = time.monotonic_ns()
        async with self.inference_lock:
            started_ns = time.monotonic_ns()
            if trace is not None:
                trace.observe(f"{span_name}_queue", (started_ns - queued_ns) / 1_000_000.0, lane="recognition", category="wait")
                trace.mark(f"{span_name}_started", started_ns)
            try:
                return await asyncio.to_thread(self.recognizer.transcribe, pcm, context)
            finally:
                ended_ns = time.monotonic_ns()
                if trace is not None:
                    trace.observe(span_name, (ended_ns - started_ns) / 1_000_000.0, lane="recognition", category="work")
                    trace.mark(f"{span_name}_ended", ended_ns)

    async def _recognize_stable(self, session: SpeechSession) -> None:
        try:
            if self.session is not session:
                return
            snapshot = session.audio[session.audio_cursor :]
            segments = await self._recognize(
                snapshot,
                self._recognition_context(session),
                trace=session.performance,
                span_name="rolling_stt",
            )
            if self.session is not session:
                return
            duration = len(snapshot) / 16000.0
            agreement_started_ns = time.monotonic_ns()
            stable = [segment for segment in segments if segment.end <= duration - self.stable_lag]
            if not stable:
                if session.performance is not None:
                    session.performance.observe("stable_agreement", (time.monotonic_ns() - agreement_started_ns) / 1_000_000.0, lane="recognition", category="work")
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
                if session.performance is not None:
                    session.performance.observe("stable_agreement", (time.monotonic_ns() - agreement_started_ns) / 1_000_000.0, lane="recognition", category="work")
                session.previous_segments = stable
                return

            committed_segments = stable[:commit_count]
            text = output_text(committed_segments, session.has_output)
            if session.performance is not None:
                session.performance.observe("stable_agreement", (time.monotonic_ns() - agreement_started_ns) / 1_000_000.0, lane="recognition", category="work")
            if session.injection_enabled and text:
                if session.output_writer is not None:
                    if session.performance is not None and "typing_enqueued" not in session.performance.milestones:
                        session.performance.mark("typing_enqueued")
                    session.injection_enabled = session.output_writer.enqueue(text)
                else:
                    inject_started_ns = time.monotonic_ns()
                    session.injection_enabled = self.injector.type_text(text, session.focus_window)
                    inject_ended_ns = time.monotonic_ns()
                    if session.performance is not None:
                        session.performance.observe("text_inject", (inject_ended_ns - inject_started_ns) / 1_000_000.0, lane="output", category="work")
                        if session.injection_enabled and "first_text_visible" not in session.performance.milestones:
                            session.performance.mark("first_text_visible", inject_ended_ns)
                if session.injection_enabled:
                    print(f"[text] {text}")
                    self._last_text = {
                        "text": (
                            session.output_writer.emitted_text + session.output_writer.pending_text
                            if session.output_writer is not None
                            else text
                        ),
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
        trace = session.performance
        if trace is not None:
            trace.mark("finalize_started")
        tail_snapshot = session.audio[session.audio_cursor :]
        snapshot = tail_snapshot if session.mode == "command" else session.audio
        if session.output_writer is not None:
            cancel_started_ns = time.monotonic_ns()
            await session.output_writer.cancel_pending()
            if trace is not None:
                trace.observe("cancel_pending_typing", (time.monotonic_ns() - cancel_started_ns) / 1_000_000.0, lane="output", category="work")
        succeeded = (
            bool(session.output_writer.emitted_text)
            if session.output_writer is not None
            else session.has_output
        )
        self._publish_telemetry(
            stage="recognizing",
            session_id=session.session_id,
            audio=self._session_audio_payload(session),
            recognition_busy=True,
            recognition_mode="final",
        )
        try:
            segments = await self._recognize(
                snapshot,
                self._recognition_context(session),
                trace=session.performance,
                span_name="final_stt",
            )
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
            if trace is not None:
                trace.mark("result_ready")
                trace.mark("typing_complete")
            self._finish_performance(trace, "error", error_code="final_recognition_failed")
            if not self.once:
                asyncio.create_task(self._restore_ready())
        else:
            if session.mode == "command":
                text = output_text(segments, False)
                commands = read_commands(self.config).get("entries", [])
                command_match_started_ns = time.monotonic_ns()
                result = match_command(text, commands)
                if trace is not None:
                    trace.observe("command_match", (time.monotonic_ns() - command_match_started_ns) / 1_000_000.0, lane="command", category="work")
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
                        action_started_ns = time.monotonic_ns()
                        await self._action_writer(result.command)
                        action_ended_ns = time.monotonic_ns()
                        if trace is not None:
                            trace.observe("command_dispatch", (action_ended_ns - action_started_ns) / 1_000_000.0, lane="command", category="io")
                            trace.mark("command_action_complete", action_ended_ns)
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
                        action_started_ns = time.monotonic_ns()
                        succeeded = self._execute_local_action(result.command, session)
                        action_ended_ns = time.monotonic_ns()
                        if trace is not None:
                            trace.observe("command_dispatch", (action_ended_ns - action_started_ns) / 1_000_000.0, lane="command", category="work")
                            trace.mark("command_action_complete", action_ended_ns)
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
                if trace is not None:
                    trace.mark("result_ready")
                    trace.mark("typing_complete")
                self._finish_performance(trace, "success" if succeeded else "unmatched")
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

            normalize_started_ns = time.monotonic_ns()
            raw_text = normalize_transcript(output_text(segments, False))
            if trace is not None:
                trace.observe("normalize", (time.monotonic_ns() - normalize_started_ns) / 1_000_000.0, lane="correction", category="work")
            preferences = session.preferences or read_voice_preferences(self.config)
            correction_started_ns = time.monotonic_ns()
            correction = await asyncio.to_thread(
                self.corrector.correct,
                raw_text,
                preferences.correction,
            )
            if trace is not None:
                trace.observe("correction", (time.monotonic_ns() - correction_started_ns) / 1_000_000.0, lane="correction", category="work")
                trace.metrics["correction_reported_ms"] = correction.latency_ms
                trace.mark("result_ready")
            text = correction.text
            writer = session.output_writer
            emitted = writer.emitted_text if writer is not None else ""
            replacement_reason = "not_needed"
            inserted_text = emitted
            if session.injection_enabled and text:
                try:
                    if writer is None:
                        inject_started_ns = time.monotonic_ns()
                        session.injection_enabled = self.injector.type_text(text, session.focus_window)
                        inject_ended_ns = time.monotonic_ns()
                        if trace is not None:
                            trace.observe("text_inject", (inject_ended_ns - inject_started_ns) / 1_000_000.0, lane="output", category="work")
                            if session.injection_enabled and "first_text_visible" not in trace.milestones:
                                trace.mark("first_text_visible", inject_ended_ns)
                        inserted_text = text if session.injection_enabled else ""
                    elif text.startswith(emitted):
                        if trace is not None and "typing_enqueued" not in trace.milestones:
                            trace.mark("typing_enqueued")
                        writer.enqueue(text[len(emitted) :])
                        session.injection_enabled = await writer.drain()
                        inserted_text = writer.emitted_text
                    else:
                        prefix = common_grapheme_prefix(emitted, text)
                        expected_suffix = emitted[len(prefix) :]
                        replacement = text[len(prefix) :]
                        replace_suffix = getattr(self.injector, "replace_verified_suffix", None)
                        replacement_started_ns = time.monotonic_ns()
                        result = (
                            replace_suffix(expected_suffix, replacement, session.focus_window)
                            if expected_suffix and callable(replace_suffix)
                            else None
                        )
                        if trace is not None:
                            trace.observe("suffix_replace", (time.monotonic_ns() - replacement_started_ns) / 1_000_000.0, lane="output", category="work")
                        if result is not None and result.replaced:
                            inserted_text = text
                            replacement_reason = result.reason
                        else:
                            replacement_reason = result.reason if result is not None else "unsupported"
                            if replacement_reason in {"unsupported", "text_mismatch", "selection_changed"}:
                                # Never delete text unless the platform verified the exact
                                # suffix. On unsupported fields, append only audio that was
                                # not already committed by rolling recognition.
                                tail_segments = (
                                    await self._recognize(
                                        tail_snapshot,
                                        self._recognition_context(session),
                                        trace=session.performance,
                                        span_name="tail_stt",
                                    )
                                    if tail_snapshot
                                    else []
                                )
                                tail_text = output_text(tail_segments, bool(emitted))
                                writer.enqueue(tail_text)
                                session.injection_enabled = await writer.drain()
                                inserted_text = writer.emitted_text
                            else:
                                # A focus or insertion failure may have happened after a
                                # suffix was selected. Do not send any more keystrokes.
                                session.injection_enabled = False
                    if session.injection_enabled and inserted_text:
                        print(f"[text final] {inserted_text}")
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
            if writer is not None:
                await writer.close(cancel=not session.injection_enabled)
            if trace is not None:
                trace.mark("typing_complete")
            self._last_text = {
                "text": inserted_text,
                "raw_text": correction.raw_text,
                "corrected_text": text,
                "final": True,
                "correction": correction.to_dict(),
                "replacement": replacement_reason,
                "time": time.time(),
            }
            elapsed = len(session.audio) / 16000.0
            LOGGER.info(
                "speech session finalized session=%s elapsed=%.1fs text_inserted=%s injection_enabled=%s",
                session.session_id,
                elapsed,
                succeeded,
                session.injection_enabled,
            )
            self._finish_performance(
                trace,
                "success" if succeeded else ("insertion_failed" if not session.injection_enabled else "empty"),
                error_code=None if session.injection_enabled else "text_insertion_failed",
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


async def _performance_sync_loop(client: Any, characteristic: Any, controller: SpeechController) -> None:
    sequence = 0
    first = True
    while client.is_connected:
        try:
            if controller.session is None:
                for _ in range(5):
                    sequence = (sequence + 1) & 0xFFFF
                    controller.begin_clock_sync(sequence)
                    await client.write_gatt_char(
                        characteristic,
                        PerformanceSyncRequest(sequence).build(),
                        response=True,
                    )
                    await asyncio.sleep(0.04)
                if first:
                    LOGGER.info("performance clock synchronized sample=%s", controller.clock_sync_payload())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("optional performance clock synchronization failed: %s", exc)
        finally:
            if first:
                controller.complete_performance_sync_batch()
                first = False
        await asyncio.sleep(300.0)


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
        lifecycle = controller._new_performance_trace("lifecycle")
        controller.begin_lifecycle_performance(lifecycle)
        try:
            permission_started_ns = time.monotonic_ns()
            _ensure_bluetooth_permission(adapter)
            lifecycle.add_span_ns("bluetooth_permission", permission_started_ns, time.monotonic_ns(), lane="lifecycle", category="work")
            LOGGER.info("waiting for operating-system HID connection")
            controller.mark_waiting_for_system_connection()
            lifecycle.mark("system_hid_wait_started")
            device = await adapter.wait_for_system_connection(identifier)
            lifecycle.mark("system_hid_wait_ended")
            lifecycle.add_span_between("system_hid_wait", "system_hid_wait_started", "system_hid_wait_ended", lane="lifecycle", category="wait")
            LOGGER.info("attaching speech GATT client to system-connected device=%r", device)
            print(f"[ble] attaching voice service to {device}")
            client = BleakClient(device, disconnected_callback=lambda _: disconnect_event.set(), timeout=60)
            prepare_started_ns = time.monotonic_ns()
            await adapter.prepare_client(client, device)
            lifecycle.add_span_ns("client_prepare", prepare_started_ns, time.monotonic_ns(), lane="lifecycle", category="io")
            attach_started_ns = time.monotonic_ns()
            async with client:
                lifecycle.add_span_ns("gatt_attach", attach_started_ns, time.monotonic_ns(), lane="lifecycle", category="io")
                service_started_ns = time.monotonic_ns()
                service_uuids = {str(service.uuid).lower() for service in client.services}
                lifecycle.add_span_ns("service_discovery", service_started_ns, time.monotonic_ns(), lane="lifecycle", category="io")
                if SERVICE_UUID not in service_uuids:
                    LOGGER.warning("speech service missing services=%s", sorted(service_uuids))
                    raise RuntimeError(
                        "Speech GATT service is missing. Forget the device on both sides, reopen BLE Remote, "
                        "and pair again."
                    )
                control_service_present = CONTROL_SERVICE_UUID in service_uuids
                # Reading the encrypted status characteristic restores or initiates pairing.
                secure_read_started_ns = time.monotonic_ns()
                await client.read_gatt_char(STATUS_UUID)
                lifecycle.add_span_ns("secure_status_read", secure_read_started_ns, time.monotonic_ns(), lane="lifecycle", category="io")
                mtu_started_ns = time.monotonic_ns()
                mtu = await adapter.acquire_mtu(client)
                lifecycle.add_span_ns("mtu_acquire", mtu_started_ns, time.monotonic_ns(), lane="lifecycle", category="io")
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
                subscribe_started_ns = time.monotonic_ns()
                await client.start_notify(STATUS_UUID, lambda _, data: controller.receive_status(bytes(data)))
                await client.start_notify(AUDIO_UUID, lambda _, data: controller.receive_audio(bytes(data)))
                host_characteristic = client.services.get_characteristic(HOST_STATUS_UUID)
                mapping_characteristic = client.services.get_characteristic(MAPPING_CONFIG_UUID)
                user_event_characteristic = client.services.get_characteristic(USER_EVENT_UUID)
                action_characteristic = client.services.get_characteristic(ACTION_EXEC_UUID)
                performance_characteristic = client.services.get_characteristic(PERFORMANCE_UUID)

                if user_event_characteristic is not None:
                    def receive_user_event(_: Any, data: bytearray) -> None:
                        controller.receive_user_event(bytes(data))

                    await client.start_notify(USER_EVENT_UUID, receive_user_event)

                if performance_characteristic is not None:
                    await client.start_notify(
                        PERFORMANCE_UUID,
                        lambda _, data: controller.receive_performance(bytes(data)),
                    )
                lifecycle.add_span_ns("subscriptions", subscribe_started_ns, time.monotonic_ns(), lane="lifecycle", category="io")

                mapping_task: asyncio.Task[None] | None = None
                if mapping_characteristic is not None:
                    mapping_task = asyncio.create_task(_mapping_sync_loop(client, mapping_characteristic))
                else:
                    LOGGER.info(
                        "watch firmware does not expose mapping config characteristic control_service=%s",
                        control_service_present,
                    )
                performance_sync_task: asyncio.Task[None] | None = None
                if performance_characteristic is not None:
                    performance_sync_task = asyncio.create_task(
                        _performance_sync_loop(client, performance_characteristic, controller)
                    )
                else:
                    LOGGER.info("watch firmware does not expose performance telemetry")

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
                        validation_started_ns = time.monotonic_ns()
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
                        lifecycle.add_span_ns("runtime_validation", validation_started_ns, time.monotonic_ns(), lane="lifecycle", category="wait")
                    if controller.recognizer is None:
                        model_started_ns = time.monotonic_ns()
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
                        lifecycle.add_span_ns("model_load", model_started_ns, time.monotonic_ns(), lane="lifecycle", category="work")
                    await write_host_status(HostStatus.READY)
                    controller.mark_lifecycle_ready(
                        lifecycle,
                        performance_supported=performance_characteristic is not None,
                    )
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
                    if performance_sync_task is not None:
                        performance_sync_task.cancel()
                        try:
                            await performance_sync_task
                        except asyncio.CancelledError:
                            pass
                        controller.complete_performance_sync_batch()
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
            controller._finish_performance(lifecycle, "error", error_code="lifecycle_failed")
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
            config=config,
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
