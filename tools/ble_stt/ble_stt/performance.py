from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import log_dir


PERFORMANCE_FILE_NAME = "ble-stt-performance.json"
PERFORMANCE_SCHEMA = 1
SESSION_RETENTION = 200
LIFECYCLE_RETENTION = 20


def performance_path(platform_name: str | None = None) -> Path:
    return log_dir(platform_name) / PERFORMANCE_FILE_NAME


def _round_ms(value: float) -> float:
    return round(max(0.0, value), 3)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values if math.isfinite(value))
    if not ordered:
        return None
    rank = max(1, math.ceil(len(ordered) * fraction))
    return _round_ms(ordered[min(rank - 1, len(ordered) - 1)])


@dataclass
class SpanAggregate:
    name: str
    lane: str
    category: str
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0

    def observe(self, duration_ms: float) -> None:
        value = max(0.0, float(duration_ms))
        self.count += 1
        self.total_ms += value
        self.max_ms = max(self.max_ms, value)

    def to_dict(self) -> dict[str, object]:
        mean = self.total_ms / self.count if self.count else 0.0
        return {
            "name": self.name,
            "lane": self.lane,
            "category": self.category,
            "start_ms": None,
            "duration_ms": _round_ms(self.total_ms),
            "count": self.count,
            "mean_ms": _round_ms(mean),
            "max_ms": _round_ms(self.max_ms),
        }


@dataclass
class PerformanceTrace:
    kind: str
    session_id: int | None = None
    mode: str | None = None
    configuration: dict[str, object] = field(default_factory=dict)
    monotonic_ns: Callable[[], int] = time.monotonic_ns
    wall_time: Callable[[], float] = time.time
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(init=False)
    origin_ns: int = field(init=False)
    milestones: dict[str, int] = field(default_factory=dict)
    spans: list[dict[str, object]] = field(default_factory=list)
    aggregates: dict[tuple[str, str, str], SpanAggregate] = field(default_factory=dict)
    metrics: dict[str, float | int | str | None] = field(default_factory=dict)
    clock_sync: dict[str, object] | None = None
    _finished: bool = False

    def __post_init__(self) -> None:
        self.started_at = self.wall_time()
        self.origin_ns = self.monotonic_ns()
        self.milestones["trace_started"] = self.origin_ns

    @property
    def finished(self) -> bool:
        return self._finished

    def mark(self, name: str, at_ns: int | None = None) -> int:
        value = self.monotonic_ns() if at_ns is None else int(at_ns)
        self.milestones[name] = value
        return value

    def add_span_ns(
        self,
        name: str,
        started_ns: int,
        ended_ns: int,
        *,
        lane: str = "host",
        category: str = "work",
    ) -> None:
        start = int(started_ns)
        end = max(start, int(ended_ns))
        self.spans.append(
            {
                "name": name,
                "lane": lane,
                "category": category,
                "_start_ns": start,
                "duration_ms": _round_ms((end - start) / 1_000_000.0),
            }
        )

    def add_span_between(
        self,
        name: str,
        start_mark: str,
        end_mark: str,
        *,
        lane: str = "host",
        category: str = "work",
    ) -> bool:
        start = self.milestones.get(start_mark)
        end = self.milestones.get(end_mark)
        if start is None or end is None or end < start:
            return False
        self.add_span_ns(name, start, end, lane=lane, category=category)
        return True

    def observe(
        self,
        name: str,
        duration_ms: float,
        *,
        lane: str = "host",
        category: str = "work",
    ) -> None:
        key = (name, lane, category)
        aggregate = self.aggregates.get(key)
        if aggregate is None:
            aggregate = SpanAggregate(name, lane, category)
            self.aggregates[key] = aggregate
        aggregate.observe(duration_ms)

    def set_metric_between(self, name: str, start_mark: str, end_mark: str) -> None:
        start = self.milestones.get(start_mark)
        end = self.milestones.get(end_mark)
        self.metrics[name] = None if start is None or end is None or end < start else _round_ms((end - start) / 1_000_000.0)

    def current_payload(self) -> dict[str, object]:
        now = self.monotonic_ns()
        return {
            "trace_id": self.trace_id,
            "kind": self.kind,
            "session_id": self.session_id,
            "mode": self.mode,
            "phase": next(reversed(self.milestones), "starting"),
            "elapsed_ms": _round_ms((now - self.origin_ns) / 1_000_000.0),
        }

    def finish(self, outcome: str, *, error_code: str | None = None) -> dict[str, object]:
        if self._finished:
            raise RuntimeError("performance trace is already finished")
        self._finished = True
        finished_ns = self.mark("trace_finished")
        all_starts = [self.origin_ns]
        all_starts.extend(
            int(span["_start_ns"])
            for span in self.spans
            if isinstance(span.get("_start_ns"), int)
        )
        display_origin = min(all_starts)
        rendered_spans: list[dict[str, object]] = []
        for span in self.spans:
            item = {key: value for key, value in span.items() if key != "_start_ns"}
            start_ns = span.get("_start_ns")
            item["start_ms"] = (
                _round_ms((int(start_ns) - display_origin) / 1_000_000.0)
                if isinstance(start_ns, int)
                else None
            )
            rendered_spans.append(item)
        rendered_spans.extend(aggregate.to_dict() for aggregate in self.aggregates.values())
        return {
            "schema": PERFORMANCE_SCHEMA,
            "trace_id": self.trace_id,
            "kind": self.kind,
            "session_id": self.session_id,
            "mode": self.mode,
            "outcome": outcome,
            "error_code": error_code,
            "configuration": self.configuration,
            "started_at": self.started_at,
            "completed_at": self.wall_time(),
            "duration_ms": _round_ms((finished_ns - display_origin) / 1_000_000.0),
            "clock_sync": self.clock_sync,
            "spans": rendered_spans,
            "metrics": self.metrics,
        }


def default_performance() -> dict[str, Any]:
    return {
        "schema": PERFORMANCE_SCHEMA,
        "revision": 0,
        "updated_at": None,
        "sessions": [],
        "lifecycles": [],
    }


def read_performance(path: Path | None = None) -> dict[str, Any]:
    source = path or performance_path()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("performance payload is not an object")
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return default_performance()
    payload.setdefault("schema", PERFORMANCE_SCHEMA)
    payload.setdefault("revision", 0)
    payload.setdefault("updated_at", None)
    payload.setdefault("sessions", [])
    payload.setdefault("lifecycles", [])
    if not isinstance(payload["sessions"], list):
        payload["sessions"] = []
    if not isinstance(payload["lifecycles"], list):
        payload["lifecycles"] = []
    return payload


def _write_performance(payload: dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(destination)


def append_performance(record: dict[str, object], path: Path | None = None) -> dict[str, Any]:
    destination = path or performance_path()
    payload = read_performance(destination)
    key = "lifecycles" if record.get("kind") == "lifecycle" else "sessions"
    limit = LIFECYCLE_RETENTION if key == "lifecycles" else SESSION_RETENTION
    values = [value for value in payload[key] if isinstance(value, dict)]
    values.append(record)
    payload[key] = values[-limit:]
    payload["revision"] = int(payload.get("revision", 0)) + 1
    payload["updated_at"] = time.time()
    _write_performance(payload, destination)
    return payload


def clear_performance(path: Path | None = None) -> dict[str, Any]:
    destination = path or performance_path()
    previous = read_performance(destination)
    payload = default_performance()
    payload["revision"] = int(previous.get("revision", 0)) + 1
    payload["updated_at"] = time.time()
    _write_performance(payload, destination)
    return payload


class ClockSynchronizer:
    def __init__(self) -> None:
        self.pending: dict[int, int] = {}
        self.best: dict[str, float | int] | None = None

    def begin(self, sequence: int, host_send_ns: int | None = None) -> int:
        started = time.monotonic_ns() if host_send_ns is None else int(host_send_ns)
        self.pending[int(sequence) & 0xFFFF] = started
        return started

    def complete(
        self,
        sequence: int,
        device_receive_us: int,
        device_send_us: int,
        host_receive_ns: int | None = None,
    ) -> dict[str, float | int] | None:
        host_start = self.pending.pop(int(sequence) & 0xFFFF, None)
        if host_start is None:
            return None
        host_end = time.monotonic_ns() if host_receive_ns is None else int(host_receive_ns)
        device_processing_ns = max(0, int(device_send_us) - int(device_receive_us)) * 1000
        rtt_ns = max(0, host_end - host_start - device_processing_ns)
        host_midpoint = (host_start + host_end) // 2
        device_midpoint_ns = ((int(device_receive_us) + int(device_send_us)) * 1000) // 2
        sample: dict[str, float | int] = {
            "offset_ns": host_midpoint - device_midpoint_ns,
            "rtt_ms": _round_ms(rtt_ns / 1_000_000.0),
            "uncertainty_ms": _round_ms(rtt_ns / 2_000_000.0),
        }
        if self.best is None or float(sample["rtt_ms"]) < float(self.best["rtt_ms"]):
            self.best = sample
        return sample

    def device_to_host_ns(self, device_us: int) -> int | None:
        if self.best is None or float(self.best["uncertainty_ms"]) > 10.0:
            return None
        return int(device_us) * 1000 + int(self.best["offset_ns"])

    def payload(self) -> dict[str, object] | None:
        if self.best is None:
            return None
        uncertainty = float(self.best["uncertainty_ms"])
        return {
            "rtt_ms": self.best["rtt_ms"],
            "uncertainty_ms": uncertainty,
            "merged": uncertainty <= 10.0,
        }
