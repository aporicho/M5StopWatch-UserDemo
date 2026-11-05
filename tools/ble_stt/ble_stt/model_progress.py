from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator


PROGRESS_PREFIX = "BLE_STT_MODEL_PROGRESS "


def _directory_bytes(paths: Iterable[Path]) -> int:
    """Return real cached bytes without counting snapshot symlinks twice."""
    sizes: list[int] = []
    for path in paths:
        if path.is_file():
            try:
                sizes.append(path.stat().st_size)
            except OSError:
                pass
            continue
        total = 0
        seen: set[tuple[int, int]] = set()
        if not path.exists():
            sizes.append(0)
            continue
        for root, _, files in os.walk(path):
            for name in files:
                candidate = Path(root) / name
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                identity = (stat.st_dev, stat.st_ino)
                if identity in seen:
                    continue
                seen.add(identity)
                total += stat.st_size
        sizes.append(total)
    # The same payload can be mirrored in a Hub cache and local staging folder.
    # Taking the largest view reports network progress without double-counting it.
    return max(sizes, default=0)


class ModelProgressReporter:
    def __init__(
        self,
        operation_id: str,
        kind: str,
        action: str,
        model: str,
        *,
        enabled: bool = True,
        interval: float = 0.2,
    ) -> None:
        self.operation_id = operation_id
        self.kind = kind
        self.action = action
        self.model = model
        self.enabled = enabled
        self.interval = interval
        self._last_emit = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> ModelProgressReporter | None:
        if os.environ.get("BLE_STT_MODEL_PROGRESS") != "1":
            return None
        operation_id = os.environ.get("BLE_STT_MODEL_OPERATION_ID", "")
        kind = os.environ.get("BLE_STT_MODEL_KIND", "")
        action = os.environ.get("BLE_STT_MODEL_ACTION", "")
        model = os.environ.get("BLE_STT_MODEL_NAME", "")
        if not all((operation_id, kind, action, model)):
            return None
        return cls(operation_id, kind, action, model)

    def emit(
        self,
        phase: str,
        *,
        component: str | None = None,
        downloaded_bytes: int = 0,
        total_bytes: int | None = None,
        cancellable: bool = False,
        force: bool = True,
    ) -> None:
        if not self.enabled:
            return
        now = time.time()
        with self._lock:
            if not force and now - self._last_emit < self.interval:
                return
            self._last_emit = now
            downloaded = max(0, int(downloaded_bytes))
            total = max(0, int(total_bytes)) if total_bytes is not None else None
            if total:
                downloaded = min(downloaded, total)
                percent: float | None = round(downloaded * 100 / total, 1)
            else:
                percent = None
            payload = {
                "schema": 1,
                "id": self.operation_id,
                "kind": self.kind,
                "action": self.action,
                "model": self.model,
                "phase": phase,
                "component": component,
                "downloaded_bytes": downloaded,
                "total_bytes": total,
                "percent": percent,
                "cancellable": cancellable,
                "updated_at": now,
            }
            print(PROGRESS_PREFIX + json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)

    @contextmanager
    def monitor_download(
        self,
        paths: Iterable[Path],
        total_bytes: int | None,
        *,
        component: str,
    ) -> Iterator[None]:
        candidates = tuple(paths)
        stop = threading.Event()

        def report(force: bool = False) -> None:
            self.emit(
                "downloading",
                component=component,
                downloaded_bytes=_directory_bytes(candidates),
                total_bytes=total_bytes,
                cancellable=True,
                force=force,
            )

        def poll() -> None:
            while not stop.wait(self.interval):
                report()

        report(force=True)
        worker = threading.Thread(target=poll, name="model-progress", daemon=True)
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join(timeout=1)
            report(force=True)


def operation_reporter() -> ModelProgressReporter | None:
    return ModelProgressReporter.from_environment()
