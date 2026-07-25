from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .config import log_dir
from .diagnostics import EVENT_LOG_NAME, event_log_paths
from .service import ServiceManager


START_RE = re.compile(r"speech session started session=(\d+)")
FINAL_RE = re.compile(
    r"speech session finalized session=(\d+) elapsed=([0-9.]+)s "
    r"text_inserted=(True|False) injection_enabled=(True|False)"
)
READY_RE = re.compile(r"(connected, MTU|\[device\] speech input ready|watch status ready)")
ERROR_LEVEL_RE = re.compile(r"\s(?:ERROR|CRITICAL)\s")
ERROR_TEXT_MARKERS = (
    "unhandled exception",
    "runtime exiting with exception",
    "Traceback ",
)


def _is_error_line(line: str) -> bool:
    return bool(ERROR_LEVEL_RE.search(line)) or any(marker in line for marker in ERROR_TEXT_MARKERS)


@dataclass
class JourneySession:
    session_id: int
    elapsed_seconds: float
    text_inserted: bool
    injection_enabled: bool


@dataclass
class JourneyLogSummary:
    ready_events: int = 0
    started_sessions: int = 0
    finalized_sessions: list[JourneySession] = field(default_factory=list)
    error_lines: list[str] = field(default_factory=list)
    ignored_setup_error_lines: list[str] = field(default_factory=list)

    @property
    def inserted_sessions(self) -> int:
        return sum(1 for session in self.finalized_sessions if session.text_inserted)

    @property
    def failed_sessions(self) -> int:
        return sum(1 for session in self.finalized_sessions if not session.text_inserted)

    @property
    def has_errors(self) -> bool:
        return bool(self.error_lines)


def scan_journey_lines(lines: Iterable[str]) -> JourneyLogSummary:
    summary = JourneyLogSummary()
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if READY_RE.search(line):
            summary.ready_events += 1
        if START_RE.search(line):
            summary.started_sessions += 1
        final_match = FINAL_RE.search(line)
        if final_match:
            summary.finalized_sessions.append(
                JourneySession(
                    session_id=int(final_match.group(1)),
                    elapsed_seconds=float(final_match.group(2)),
                    text_inserted=final_match.group(3) == "True",
                    injection_enabled=final_match.group(4) == "True",
                )
            )
        if _is_error_line(line):
            summary.error_lines.append(line)
    return summary


class LogTail:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.position = path.stat().st_size if path.exists() else 0

    def read_new_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        size = self.path.stat().st_size
        if size < self.position:
            self.position = 0
        with self.path.open("rb") as stream:
            stream.seek(self.position)
            data = stream.read()
            self.position = stream.tell()
        if not data:
            return []
        return data.decode("utf-8", errors="replace").splitlines()


def _wait_for_service(manager: ServiceManager, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if manager.is_active():
            return True
        time.sleep(2.0)
    return False


def _write_report(
    artifact_dir: Path,
    summary: JourneyLogSummary,
    passed: bool,
    args: argparse.Namespace,
    service_restarted: bool,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "passed": passed,
        "rounds_required": args.rounds,
        "duration_seconds": args.duration,
        "assertion": args.assertion,
        "service_restarted": service_restarted,
        "summary": asdict(summary),
    }
    (artifact_dir / "journey-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for path in event_log_paths():
        if path.exists():
            shutil.copy2(path, artifact_dir / path.name)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ble-stt journey-test", description="Run the end-to-end user journey test")
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--duration", type=float, default=1800.0, help="maximum monitor time in seconds")
    parser.add_argument("--assert", dest="assertion", choices=("non-empty", "link-only"), default="non-empty")
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--restart-timeout", type=float, default=120.0)
    parser.add_argument("--no-restart-check", action="store_true")
    return parser.parse_args(argv)


def run(argv: Sequence[str] | None = None, manager: ServiceManager | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    if args.rounds <= 0:
        raise RuntimeError("--rounds must be greater than 0")
    if args.duration <= 0:
        raise RuntimeError("--duration must be greater than 0")
    if args.poll_interval <= 0:
        raise RuntimeError("--poll-interval must be greater than 0")

    manager = manager or ServiceManager()
    if not manager.is_active():
        raise RuntimeError("the login service is not running; run 'ble-stt restart' or reinstall the service")

    artifact_dir = args.artifact_dir or Path.cwd() / "test-artifacts" / datetime.now().strftime("%Y%m%d-%H%M%S")
    tail = LogTail(log_dir() / EVENT_LOG_NAME)
    summary = JourneyLogSummary()
    deadline = time.monotonic() + args.duration
    last_inserted = 0
    strict_errors = False
    print(f"Journey test started. Artifacts: {artifact_dir}")
    print("Open BLE Remote, focus a blank text document, then complete the prompted push-to-talk rounds.")
    print("Waiting for the watch connection or first speech session before strict error checks.")

    try:
        while time.monotonic() < deadline:
            lines = tail.read_new_lines()
            if lines:
                next_summary = scan_journey_lines(lines)
                if (
                    next_summary.ready_events
                    or next_summary.started_sessions
                    or next_summary.finalized_sessions
                ):
                    strict_errors = True
                if strict_errors:
                    summary.error_lines.extend(next_summary.error_lines)
                else:
                    summary.ignored_setup_error_lines.extend(next_summary.error_lines)
                summary.ready_events += next_summary.ready_events
                summary.started_sessions += next_summary.started_sessions
                summary.finalized_sessions.extend(next_summary.finalized_sessions)
            if summary.has_errors:
                print("[fail] Error found in service logs.")
                break
            if summary.inserted_sessions != last_inserted:
                last_inserted = summary.inserted_sessions
                print(f"[progress] inserted sessions: {summary.inserted_sessions}/{args.rounds}")
            if args.assertion == "non-empty" and summary.inserted_sessions >= args.rounds:
                break
            if args.assertion == "link-only" and len(summary.finalized_sessions) >= args.rounds:
                break
            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        _write_report(artifact_dir, summary, False, args, False)
        return 130

    passed = not summary.has_errors
    if args.assertion == "non-empty":
        passed = passed and summary.inserted_sessions >= args.rounds and summary.failed_sessions == 0
    else:
        passed = passed and len(summary.finalized_sessions) >= args.rounds

    service_restarted = False
    if passed and not args.no_restart_check:
        print("Restarting service for recovery check...")
        manager.restart()
        service_restarted = _wait_for_service(manager, args.restart_timeout)
        passed = passed and service_restarted
        if not service_restarted:
            print("[fail] Service did not recover after restart.")

    _write_report(artifact_dir, summary, passed, args, service_restarted)
    print(
        f"Journey result: {'PASS' if passed else 'FAIL'} "
        f"inserted={summary.inserted_sessions} finalized={len(summary.finalized_sessions)} "
        f"errors={len(summary.error_lines)}"
    )
    return 0 if passed else 1
