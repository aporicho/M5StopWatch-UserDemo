from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from .config import log_dir


TELEMETRY_FILE_NAME = "ble-stt-runtime.json"
TELEMETRY_SCHEMA = 1
TELEMETRY_STALE_SECONDS = 8.0


def telemetry_path(platform_name: str | None = None) -> Path:
    return log_dir(platform_name) / TELEMETRY_FILE_NAME


def clamp01(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def audio_metrics(pcm: list[int] | tuple[int, ...]) -> dict[str, float]:
    if not pcm:
        return {"level": 0.0, "peak": 0.0}

    peak = max(abs(sample) for sample in pcm) / 32768.0
    rms = math.sqrt(sum(float(sample) * float(sample) for sample in pcm) / len(pcm)) / 32768.0
    # Human-facing meters need a little lift at quiet levels without clipping
    # speech peaks into a permanently full bar.
    level = math.sqrt(clamp01(rms * 3.2))
    return {
        "level": round(clamp01(level), 4),
        "peak": round(clamp01(peak), 4),
    }


def default_telemetry(stage: str = "offline") -> dict[str, Any]:
    return {
        "schema": TELEMETRY_SCHEMA,
        "stage": stage,
        "session_id": None,
        "audio": {
            "level": 0.0,
            "peak": 0.0,
            "seconds": 0.0,
            "frames": 0,
        },
        "recognition": {
            "busy": False,
            "mode": "idle",
        },
        "last_text": None,
        "error": None,
        "updated_at": time.time(),
        "stale": True,
        "age_seconds": None,
    }


def make_telemetry(
    *,
    stage: str,
    session_id: int | None = None,
    audio: dict[str, float | int] | None = None,
    recognition_busy: bool = False,
    recognition_mode: str = "idle",
    last_text: dict[str, Any] | None = None,
    error: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    timestamp = time.time() if now is None else now
    payload = default_telemetry(stage)
    payload.update(
        {
            "stage": stage,
            "session_id": session_id,
            "recognition": {
                "busy": bool(recognition_busy),
                "mode": recognition_mode,
            },
            "last_text": last_text,
            "error": error,
            "updated_at": timestamp,
            "stale": False,
            "age_seconds": 0.0,
        }
    )
    if audio:
        merged_audio = dict(payload["audio"])
        merged_audio.update(audio)
        payload["audio"] = merged_audio
    return payload


def write_telemetry(payload: dict[str, Any], path: Path | None = None) -> None:
    destination = path or telemetry_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(destination)


def read_telemetry(path: Path | None = None, now: float | None = None) -> dict[str, Any]:
    source = path or telemetry_path()
    timestamp = time.time() if now is None else now
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("telemetry payload is not an object")
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return default_telemetry()

    updated_at = payload.get("updated_at")
    if isinstance(updated_at, (int, float)):
        age = max(0.0, timestamp - float(updated_at))
    else:
        try:
            age = max(0.0, timestamp - source.stat().st_mtime)
        except OSError:
            age = None

    payload.setdefault("schema", TELEMETRY_SCHEMA)
    payload.setdefault("stage", "offline")
    payload.setdefault("session_id", None)
    payload.setdefault("audio", default_telemetry()["audio"])
    payload.setdefault("recognition", default_telemetry()["recognition"])
    payload.setdefault("last_text", None)
    payload.setdefault("error", None)
    payload["age_seconds"] = round(age, 3) if age is not None else None
    payload["stale"] = age is None or age > TELEMETRY_STALE_SECONDS
    return payload
