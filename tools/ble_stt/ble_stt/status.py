from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import UserConfig, log_dir
from .diagnostics import event_log_paths
from .models import ModelStatus, model_status
from .platforms import create_platform
from .service import ServiceManager
from .telemetry import TELEMETRY_FILE_NAME, read_telemetry


@dataclass(frozen=True)
class PermissionStatus:
    ok: bool
    message: str


@dataclass(frozen=True)
class StatusLine:
    ok: bool
    label: str
    detail: str


@dataclass(frozen=True)
class RuntimeStatus:
    ok: bool
    message: str


@dataclass(frozen=True)
class StatusSnapshot:
    service_installed: bool
    service_running: bool
    service_error: str | None
    runtime: RuntimeStatus
    watch_id: str | None
    engine: str
    model: str
    model_state: ModelStatus
    input_permission: PermissionStatus
    bluetooth_permission: PermissionStatus
    log_directory: Path
    log_paths: tuple[Path, ...]
    latest_event: str | None

    @property
    def effective_input_permission(self) -> PermissionStatus:
        if "accessibility permission" in self.runtime.message.lower() and not self.runtime.ok:
            return PermissionStatus(False, self.runtime.message)
        return self.input_permission

    @property
    def effective_bluetooth_permission(self) -> PermissionStatus:
        if "bluetooth permission" in self.runtime.message.lower() and not self.runtime.ok:
            return PermissionStatus(False, self.runtime.message)
        return self.bluetooth_permission

    @property
    def ready_for_voice(self) -> bool:
        return all(
            (
                self.service_installed,
                self.service_running,
                self.runtime.ok,
                self.watch_id,
                self.model_state.ready,
                self.effective_input_permission.ok,
                self.effective_bluetooth_permission.ok,
            )
        )


def overall_state(snapshot: StatusSnapshot) -> tuple[str, str, bool]:
    if snapshot.service_error:
        return "error", "Service error", False
    if not snapshot.service_installed:
        return "service_stopped", "Service not installed", False
    if not snapshot.service_running:
        return "service_stopped", "Service stopped", False
    if not snapshot.effective_bluetooth_permission.ok:
        return "bluetooth_blocked", "Bluetooth blocked", False
    if not snapshot.effective_input_permission.ok:
        return "input_blocked", "Input blocked", False
    if not snapshot.model_state.ready:
        if snapshot.model_state.state == "error":
            return "model_error", "Model error", False
        return "model_missing", "Model missing", False
    if snapshot.runtime.ok and snapshot.watch_id:
        latest = (snapshot.latest_event or "").lower()
        if "speech session started" in latest or "] listening" in latest:
            return "listening", "Listening", True
        return "voice_ready", "Voice ready", True
    runtime = snapshot.runtime.message.lower()
    latest = (snapshot.latest_event or "").lower()
    if not snapshot.watch_id or "watch was not found" in runtime or " was not found" in latest:
        return "waiting_for_watch", "Waiting for watch", False
    if "connecting" in runtime or "connecting" in latest:
        return "connecting", "Connecting watch", False
    if "connected" in runtime or "connected, mtu" in latest:
        return "watch_connected", "Watch connected", False
    if "model" in runtime:
        return "model_loading", "Model loading", False
    return "voice_not_ready", "Voice not ready", False


def snapshot_to_dict(snapshot: StatusSnapshot) -> dict[str, Any]:
    code, label, ready = overall_state(snapshot)
    lines = status_lines(snapshot)
    input_permission = snapshot.effective_input_permission
    bluetooth_permission = snapshot.effective_bluetooth_permission
    return {
        "schema": 1,
        "overall": {
            "code": code,
            "label": label,
            "ready": ready,
        },
        "service": {
            "installed": snapshot.service_installed,
            "running": snapshot.service_running,
            "error": snapshot.service_error,
        },
        "voice": {
            "ready": snapshot.ready_for_voice,
            "runtime_ok": snapshot.runtime.ok,
            "message": snapshot.runtime.message,
        },
        "watch": {
            "paired": bool(snapshot.watch_id),
            "id": snapshot.watch_id,
            "label": "Paired" if snapshot.watch_id else "Not paired",
        },
        "recognition": {
            "engine": snapshot.engine,
            "model": snapshot.model,
        },
        "model": snapshot.model_state.to_dict(),
        "permissions": {
            "input": {
                "ok": input_permission.ok,
                "message": input_permission.message,
            },
            "bluetooth": {
                "ok": bluetooth_permission.ok,
                "message": bluetooth_permission.message,
            },
        },
        "logs": {
            "directory": str(snapshot.log_directory),
            "latest_event": snapshot.latest_event,
            "files": [
                {
                    "name": path.name,
                    "path": str(path),
                    "exists": path.exists(),
                }
                for path in snapshot.log_paths
            ],
        },
        "lines": [
            {
                "ok": line.ok,
                "label": line.label,
                "detail": line.detail,
            }
            for line in lines
        ],
    }


def latest_log_line(paths: tuple[Path, ...], max_length: int = 220) -> str | None:
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            value = line.strip()
            if not value:
                continue
            if path.name == "ble-stt-events.log" and not _looks_like_log_record(value):
                continue
            if path.name == "ble-stt-events.log" and _is_low_signal_log_record(value):
                continue
            if len(value) <= max_length:
                return value
            return f"{value[: max(0, max_length - 3)]}..."
    return None


def _looks_like_log_record(value: str) -> bool:
    return len(value) >= 19 and value[4:5] == "-" and value[7:8] == "-" and value[10:11] == " "


def _is_low_signal_log_record(value: str) -> bool:
    return "host status sent status=permission_error" in value.lower()


def _permission_status(checker: object, method_name: str) -> PermissionStatus:
    try:
        method = getattr(checker, method_name)
        ok, message = method(False)
        return PermissionStatus(bool(ok), str(message))
    except Exception as exc:
        return PermissionStatus(False, str(exc))


def _service_state(manager: ServiceManager) -> tuple[bool, bool, str | None]:
    try:
        installed = manager.is_installed()
        running = manager.is_active() if installed else False
        return bool(installed), bool(running), None
    except Exception as exc:
        return False, False, str(exc)


def _runtime_status_from_telemetry(telemetry: dict[str, Any] | None) -> RuntimeStatus | None:
    if not telemetry or telemetry.get("stale"):
        return None

    stage = str(telemetry.get("stage") or "").lower()
    error = telemetry.get("error")
    if stage == "error":
        return RuntimeStatus(False, str(error) if error else "runtime error")
    if stage in {"ready", "inserted"}:
        return RuntimeStatus(True, "ready")
    if stage in {"listening", "recognizing"}:
        return RuntimeStatus(True, stage)
    if stage == "offline":
        return RuntimeStatus(False, "service is offline")
    if stage:
        return RuntimeStatus(False, stage.replace("_", " "))
    return None


def _runtime_status(
    service_running: bool,
    latest_event: str | None,
    telemetry: dict[str, Any] | None = None,
) -> RuntimeStatus:
    if not service_running:
        return RuntimeStatus(False, "service is not running")
    telemetry_status = _runtime_status_from_telemetry(telemetry)
    if telemetry_status is not None:
        return telemetry_status
    if not latest_event:
        return RuntimeStatus(False, "waiting for service log")

    value = latest_event.lower()
    if "host status sent status=ready" in value or "speech input ready" in value:
        return RuntimeStatus(True, "ready")
    if "speech session finalized" in value or "] finished (" in value:
        return RuntimeStatus(True, "ready")
    if "connected, mtu" in value or "connected mtu=" in value:
        return RuntimeStatus(False, "connected, waiting for model")
    if "model] loading" in value or "preparing" in value:
        return RuntimeStatus(False, "model loading")
    if "bluetooth permission not ready" in value or "bluetooth permission has not been granted" in value:
        return RuntimeStatus(False, "Bluetooth permission is not granted to the service")
    if "accessibility permission is required" in value:
        return RuntimeStatus(False, "Accessibility permission is not granted to the service")
    if "runtime requirement not ready" in value:
        return RuntimeStatus(False, "host permission is not ready")
    if " was not found" in value or "device name scan timed out" in value:
        return RuntimeStatus(False, "watch was not found")
    if (
        "ble connect timed out" in value
        or "failed to discover services" in value
        or "the specified device is not connected" in value
    ):
        return RuntimeStatus(False, "BLE connection is not ready")
    if "startup component=run" in value or "runtime options" in value:
        return RuntimeStatus(False, "starting")
    if "[ble] connecting" in value or "connecting to device=" in value:
        return RuntimeStatus(False, "connecting")
    return RuntimeStatus(False, "waiting for voice service")


def collect_status(
    *,
    manager: ServiceManager | None = None,
    config: UserConfig | None = None,
    platform_adapter: object | None = None,
    platform_name: str | None = None,
    log_directory: Path | None = None,
    log_paths: tuple[Path, ...] | None = None,
) -> StatusSnapshot:
    manager = manager or ServiceManager(platform_name)
    config = config or UserConfig()
    installed, running, service_error = _service_state(manager)

    watch_id = config.get("device_id")
    model_state_value = model_status(config)
    engine, model = model_state_value.engine, model_state_value.resolved

    if platform_adapter is None:
        try:
            platform_adapter = create_platform(platform_name, config)
            input_permission = _permission_status(platform_adapter, "check_input_permission")
            bluetooth_permission = _permission_status(platform_adapter, "check_bluetooth_permission")
        except Exception as exc:
            message = str(exc)
            input_permission = PermissionStatus(False, message)
            bluetooth_permission = PermissionStatus(False, message)
    else:
        input_permission = _permission_status(platform_adapter, "check_input_permission")
        bluetooth_permission = _permission_status(platform_adapter, "check_bluetooth_permission")

    resolved_log_directory = log_directory or log_dir(platform_name)
    resolved_log_paths = log_paths or event_log_paths(platform_name)

    latest_event = latest_log_line(resolved_log_paths)
    runtime_telemetry = read_telemetry(resolved_log_directory / TELEMETRY_FILE_NAME)

    return StatusSnapshot(
        service_installed=installed,
        service_running=running,
        service_error=service_error,
        runtime=_runtime_status(running, latest_event, runtime_telemetry),
        watch_id=str(watch_id) if watch_id else None,
        engine=engine,
        model=model,
        model_state=model_state_value,
        input_permission=input_permission,
        bluetooth_permission=bluetooth_permission,
        log_directory=resolved_log_directory,
        log_paths=resolved_log_paths,
        latest_event=latest_event,
    )


def status_lines(snapshot: StatusSnapshot) -> list[StatusLine]:
    if snapshot.service_error:
        service_ok = False
        service_detail = snapshot.service_error
    else:
        service_ok = snapshot.service_installed and snapshot.service_running
        service_detail = (
            "running"
            if snapshot.service_running
            else ("stopped" if snapshot.service_installed else "not installed")
        )

    return [
        StatusLine(service_ok, "login service", service_detail),
        StatusLine(snapshot.runtime.ok, "voice service", snapshot.runtime.message),
        StatusLine(
            bool(snapshot.watch_id),
            "watch",
            f"cached as {snapshot.watch_id}" if snapshot.watch_id else "not paired yet",
        ),
        StatusLine(snapshot.model_state.ready, "model", snapshot.model_state.message),
        StatusLine(
            snapshot.effective_input_permission.ok,
            "text input",
            snapshot.effective_input_permission.message,
        ),
        StatusLine(
            snapshot.effective_bluetooth_permission.ok,
            "Bluetooth",
            snapshot.effective_bluetooth_permission.message,
        ),
    ]
