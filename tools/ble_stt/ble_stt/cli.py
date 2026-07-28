from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from . import __version__
from .commands import command_payload, read_commands, reset_commands, save_commands
from .config import UserConfig, install_dir, log_dir
from .correction_models import (
    CORRECTION_MODEL_PRESET_MAP,
    correction_model_status,
    delete_correction_model,
    install_correction_model,
    list_correction_models,
    repair_correction_model,
    update_correction_model,
    use_correction_model,
)
from .diagnostics import event_log_paths
from .mapping import mapping_payload, read_mapping, reset_mapping, save_mapping
from .model_progress import operation_reporter
from .models import (
    DEFAULT_ENGINE,
    DEFAULT_MODEL,
    check_updates,
    delete_model,
    install_model,
    list_models,
    model_status,
    repair_model,
    update_model,
    use_model,
)
from .platforms import create_platform
from .preferences import read_voice_preferences, save_voice_preferences
from .recognizers import prepare_recognizer
from .service import ServiceManager
from .status import collect_status, snapshot_to_dict, status_lines
from .telemetry import read_telemetry
from .performance import clear_performance, read_performance


COMMANDS = {
    "run",
    "status",
    "doctor",
    "test",
    "journey-test",
    "logs",
    "telemetry",
    "performance",
    "restart",
    "service",
    "upgrade",
    "uninstall",
    "prepare",
    "models",
    "mappings",
    "commands",
    "voice-settings",
    "permissions",
    "help",
}

LOG_RECORD_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+"
    r"(?P<level>[A-Z]+)\s+\[(?P<context>[^\]]+)\]\s+"
    r"(?P<component>[^:]+):\s*(?P<message>.*)$"
)


def _line(ok: bool, label: str, detail: str) -> None:
    print(f"[{'ok' if ok else 'fail'}] {label}: {detail}")


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def show_status(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ble-stt status", description="Show helper state")
    parser.add_argument("--json", action="store_true", help="emit machine-readable status")
    args = parser.parse_args(argv)
    snapshot = collect_status()
    if args.json:
        _print_json(
            {
                "ok": True,
                "version": __version__,
                "status": snapshot_to_dict(snapshot),
            }
        )
        return 0

    print(f"M5StopWatch BLE STT {__version__}")
    for line in status_lines(snapshot):
        _line(line.ok, line.label, line.detail)
    print(f"Logs: {snapshot.log_directory}")
    if snapshot.latest_event:
        print(f"Latest: {snapshot.latest_event}")
    if not snapshot.ready_for_voice:
        print("Run 'ble-stt doctor --request-permissions' for guided diagnostics.")
        return 1
    return 0


def prepare(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ble-stt prepare", description="Download and verify the STT model")
    parser.add_argument("--engine", choices=("auto", "faster-whisper", "mlx"), default=DEFAULT_ENGINE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--cpu-threads", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    args = parser.parse_args(argv)
    resolved = prepare_recognizer(args.engine, args.model, args.device, args.cpu_threads)
    config = UserConfig()
    config.set("engine", args.engine)
    config.set("model", args.model)
    config.set("prepared_model", resolved)
    from .models import record_model_ready

    record_model_ready(args.engine, args.model, resolved, config=config, source="downloaded")
    return 0


def manage_models(argv: Sequence[str]) -> int:
    values = [value for value in argv if value != "--json"]
    json_output = len(values) != len(argv)
    parser = argparse.ArgumentParser(prog="ble-stt models", description="Manage speech recognition models")
    subparsers = parser.add_subparsers(dest="action", required=True)

    subparsers.add_parser("status")
    subparsers.add_parser("list")
    subparsers.add_parser("check-updates")

    for action in ("use", "install", "update", "repair", "delete"):
        subparser = subparsers.add_parser(action)
        subparser.add_argument("--engine", choices=("auto", "faster-whisper", "mlx"), default=DEFAULT_ENGINE)
        subparser.add_argument("--model", default=DEFAULT_MODEL)
        if action in {"install", "update", "repair"}:
            subparser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
            subparser.add_argument("--cpu-threads", type=int, default=max(1, (os.cpu_count() or 4) // 2))

    args = parser.parse_args(values)
    config = UserConfig()
    progress = operation_reporter()
    payload: dict[str, object]
    if args.action == "status":
        status = model_status(config)
        payload = {"ok": status.installed, "action": args.action, "model": status.to_dict()}
        code = 0 if status.installed else 1
    elif args.action == "list":
        payload = {"ok": True, "action": args.action, "models": list_models(config)}
        code = 0
    elif args.action == "check-updates":
        status = check_updates(config)
        payload = {"ok": True, "action": args.action, "model": status.to_dict()}
        code = 0
    else:
        try:
            if args.action == "use":
                status = use_model(args.model, args.engine, config)
            elif args.action == "install":
                status = install_model(
                    args.model,
                    args.engine,
                    args.device,
                    args.cpu_threads,
                    config=config,
                    progress=progress,
                )
            elif args.action == "update":
                status = update_model(
                    args.model,
                    args.engine,
                    args.device,
                    args.cpu_threads,
                    config=config,
                    progress=progress,
                )
            elif args.action == "repair":
                status = repair_model(
                    args.model,
                    args.engine,
                    args.device,
                    args.cpu_threads,
                    config=config,
                    progress=progress,
                )
            else:
                status = delete_model(args.model, args.engine, config=config)
            payload = {"ok": True, "action": args.action, "model": status.to_dict()}
            code = 0
        except Exception as exc:
            status = model_status(config, getattr(args, "engine", DEFAULT_ENGINE), getattr(args, "model", DEFAULT_MODEL))
            payload = {
                "ok": False,
                "action": args.action,
                "message": str(exc),
                "model": status.to_dict(),
            }
            code = 1

    if json_output:
        _print_json(payload)
    else:
        if "message" in payload:
            print(str(payload["message"]))
        elif "model" in payload:
            model = payload["model"]
            if isinstance(model, dict):
                print(f"{model.get('selected')}: {model.get('message')}")
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def manage_mappings(argv: Sequence[str]) -> int:
    values = [value for value in argv if value != "--json"]
    json_output = len(values) != len(argv)
    parser = argparse.ArgumentParser(prog="ble-stt mappings", description="Manage watch event mappings")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("status")
    save_parser = subparsers.add_parser("save")
    save_parser.add_argument("--payload", required=True, help="JSON payload with an entries array")
    subparsers.add_parser("reset")

    args = parser.parse_args(values)
    config = UserConfig()
    if args.action == "status":
        payload = {"ok": True, "action": args.action, **mapping_payload(config)}
    elif args.action == "save":
        value = json.loads(args.payload)
        entries = value.get("entries") if isinstance(value, dict) else value
        if not isinstance(entries, list):
            raise ValueError("mapping payload must contain an entries array")
        mapping = save_mapping(entries, config)
        payload = {"ok": True, "action": args.action, "mapping": mapping, **mapping_payload(config)}
    else:
        mapping = reset_mapping(config)
        payload = {"ok": True, "action": args.action, "mapping": mapping, **mapping_payload(config)}

    if json_output:
        _print_json(payload)
    else:
        mapping = read_mapping(config)
        print(f"[ok] {len(mapping['entries'])} mapping record(s), revision {mapping['revision']}")
    return 0


def manage_commands(argv: Sequence[str]) -> int:
    values = [value for value in argv if value != "--json"]
    json_output = len(values) != len(argv)
    parser = argparse.ArgumentParser(prog="ble-stt commands", description="Manage voice command mappings")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("status")
    save_parser = subparsers.add_parser("save")
    save_parser.add_argument("--payload", required=True, help="JSON payload with an entries array")
    subparsers.add_parser("reset")

    args = parser.parse_args(values)
    config = UserConfig()
    if args.action == "status":
        payload = {"ok": True, "action": args.action, **command_payload(config)}
    elif args.action == "save":
        value = json.loads(args.payload)
        entries = value.get("entries") if isinstance(value, dict) else value
        if not isinstance(entries, list):
            raise ValueError("command payload must contain an entries array")
        commands = save_commands(entries, config)
        payload = {"ok": True, "action": args.action, "commands": commands, **command_payload(config)}
    else:
        commands = reset_commands(config)
        payload = {"ok": True, "action": args.action, "commands": commands, **command_payload(config)}

    if json_output:
        _print_json(payload)
    else:
        commands = read_commands(config)
        print(f"[ok] {len(commands['entries'])} command(s), revision {commands['revision']}")
    return 0


def manage_voice_settings(argv: Sequence[str]) -> int:
    values = [value for value in argv if value != "--json"]
    json_output = len(values) != len(argv)
    parser = argparse.ArgumentParser(
        prog="ble-stt voice-settings",
        description="Manage correction, glossary, typing, and correction-model settings",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("status")
    save_parser = subparsers.add_parser("save")
    save_parser.add_argument("--payload", required=True, help="JSON settings payload")
    for action in (
        "use-model",
        "install-model",
        "update-model",
        "repair-model",
        "delete-model",
    ):
        action_parser = subparsers.add_parser(action)
        action_parser.add_argument("--model", choices=tuple(CORRECTION_MODEL_PRESET_MAP))

    args = parser.parse_args(values)
    config = UserConfig()
    progress = operation_reporter()
    try:
        if args.action == "save":
            raw = json.loads(args.payload)
            if not isinstance(raw, dict):
                raise ValueError("settings payload must be an object")
            settings = save_voice_preferences(raw, config)
        else:
            settings = read_voice_preferences(config)

        if args.action == "use-model":
            if not args.model:
                raise ValueError("correction model is required for use-model")
            model = use_correction_model(args.model, config)
            settings = read_voice_preferences(config)
        elif args.action == "install-model":
            model = install_correction_model(config, args.model, progress)
        elif args.action == "update-model":
            model = update_correction_model(config, args.model, progress)
        elif args.action == "repair-model":
            model = repair_correction_model(config, args.model, progress)
        elif args.action == "delete-model":
            model = delete_correction_model(config, args.model)
        else:
            model = correction_model_status(config)
        payload: dict[str, object] = {
            "ok": True,
            "action": args.action,
            "settings": settings.to_dict(),
            "correction_model": model.to_dict(),
            "correction_models": list_correction_models(config),
        }
        code = 0
    except Exception as exc:
        payload = {
            "ok": False,
            "action": args.action,
            "message": str(exc),
            "settings": read_voice_preferences(config).to_dict(),
            "correction_model": correction_model_status(config).to_dict(),
            "correction_models": list_correction_models(config),
        }
        code = 1

    if json_output:
        _print_json(payload)
    else:
        print(str(payload.get("message") or payload["correction_model"]))
    return code


def _display_log_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\r", " ")).strip()


def _read_log_lines(path: Path) -> list[str]:
    # splitlines() treats carriage-return progress updates as new records.
    # The helper logs those as one event; preserve that shape for diagnostics.
    text = path.read_bytes().decode("utf-8", errors="replace")
    values = [line.rstrip("\r") for line in text.split("\n")]
    if values and values[-1] == "":
        values.pop()
    return values


def _structured_log_entry(source: str, line: str) -> dict[str, str]:
    match = LOG_RECORD_RE.match(line)
    if match:
        message = _display_log_text(match.group("message"))
        component = match.group("component")
        for stream in ("stdout", "stderr"):
            prefix = f"{stream}: "
            if message.startswith(prefix):
                component = stream
                message = message[len(prefix) :]
                break
        return {
            "source": source,
            "line": line,
            "time": match.group("time"),
            "level": match.group("level"),
            "component": component,
            "context": match.group("context"),
            "message": message,
        }

    level = "ERROR" if source.endswith("error.log") else "INFO"
    return {
        "source": source,
        "line": line,
        "time": "",
        "level": level,
        "component": source,
        "context": "",
        "message": _display_log_text(line),
    }


def _read_log_bundle(lines: int) -> dict[str, object]:
    limit = max(0, lines)
    files: list[dict[str, object]] = []
    entries: list[dict[str, str]] = []
    ordered_entries: list[tuple[str, int, dict[str, str]]] = []
    sequence = 0
    for path in event_log_paths():
        if not path.exists() or not path.is_file():
            files.append({"name": path.name, "path": str(path), "exists": False, "lines": []})
            continue
        try:
            values = _read_log_lines(path)
        except OSError as exc:
            files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "exists": True,
                    "error": str(exc),
                    "lines": [],
                }
            )
            continue
        tail = values[-limit:] if limit else []
        files.append({"name": path.name, "path": str(path), "exists": True, "lines": tail})
        for line in tail:
            if not line:
                continue
            entry = _structured_log_entry(path.name, line)
            ordered_entries.append((entry["time"], sequence, entry))
            sequence += 1
    entries = [entry for _, _, entry in sorted(ordered_entries, key=lambda item: (item[0], item[1]))]
    return {
        "directory": str(log_dir()),
        "files": files,
        "entries": entries,
    }


def run_test(argv: Sequence[str]) -> int:
    manager = ServiceManager()
    was_active = manager.is_active()
    if was_active:
        print("Temporarily stopping the background helper for the test...")
        manager.stop()
    print("Open a text editor and focus an empty document.")
    print("When the watch says 'Speech input ready', hold its right button, speak, and release.")
    try:
        from .main import main as runtime_main

        try:
            runtime_main(["--once", *argv])
        except SystemExit as exc:
            if exc.code not in (None, 0):
                raise
    except BaseException:
        if was_active:
            print("Restarting the background helper...")
            try:
                manager.start()
            except Exception as exc:
                print(f"[warn] Could not restart the background helper: {exc}", file=sys.stderr)
        raise
    else:
        if was_active:
            print("Restarting the background helper...")
            manager.start()
    print("[ok] Speech was recognized and inserted into the focused window.")
    return 0


def show_logs(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ble-stt logs", description="Show recent helper logs")
    parser.add_argument("-n", "--lines", type=int, default=80)
    parser.add_argument("-f", "--follow", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit machine-readable logs")
    args = parser.parse_args(argv)
    if args.json:
        _print_json({"ok": True, "logs": _read_log_bundle(args.lines)})
        return 0

    paths = event_log_paths()
    existing = [path for path in paths if path.exists()]
    if not existing:
        print(f"No logs yet in {log_dir()}")
        return 1

    positions: dict[Path, int] = {}
    for path in existing:
        values = path.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"== {path.name} ==")
        print("\n".join(values[-max(0, args.lines) :]))
        positions[path] = path.stat().st_size
    if not args.follow:
        return 0
    try:
        while True:
            time.sleep(0.5)
            for path in existing:
                size = path.stat().st_size
                if size < positions[path]:
                    positions[path] = 0
                if size == positions[path]:
                    continue
                with path.open("rb") as stream:
                    stream.seek(positions[path])
                    print(stream.read().decode("utf-8", errors="replace"), end="", flush=True)
                    positions[path] = stream.tell()
    except KeyboardInterrupt:
        return 0


def show_telemetry(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ble-stt telemetry", description="Show live speech runtime telemetry")
    parser.add_argument("--json", action="store_true", help="emit machine-readable telemetry")
    args = parser.parse_args(argv)
    payload = {"ok": True, "telemetry": read_telemetry()}
    if args.json:
        _print_json(payload)
    else:
        telemetry = payload["telemetry"]
        if isinstance(telemetry, dict):
            audio = telemetry.get("audio", {})
            print(f"Stage: {telemetry.get('stage', 'unknown')}")
            if isinstance(audio, dict):
                print(f"Audio: level={audio.get('level', 0)} peak={audio.get('peak', 0)}")
            if telemetry.get("stale"):
                print("Telemetry is stale.")
    return 0


def manage_performance(argv: Sequence[str]) -> int:
    values = [value for value in argv if value != "--json"]
    json_output = len(values) != len(argv)
    parser = argparse.ArgumentParser(prog="ble-stt performance", description="Show or clear local performance traces")
    parser.add_argument("action", nargs="?", choices=("show", "clear"), default="show")
    args = parser.parse_args(values)
    payload = clear_performance() if args.action == "clear" else read_performance()
    envelope = {"ok": True, "performance": payload}
    if json_output:
        _print_json(envelope)
    else:
        print(f"Revision: {payload.get('revision', 0)}")
        print(f"Sessions: {len(payload.get('sessions', []))} / 200")
        print(f"Lifecycles: {len(payload.get('lifecycles', []))} / 20")
    return 0


def manage_permissions(argv: Sequence[str]) -> int:
    values = [value for value in argv if value != "--json"]
    json_output = len(values) != len(argv)
    parser = argparse.ArgumentParser(
        prog="ble-stt permissions",
        description="Open or request platform permission settings",
    )
    parser.add_argument("action", choices=("open", "request"))
    parser.add_argument("kind", choices=("input", "bluetooth"))
    args = parser.parse_args(values)
    platform_adapter = create_platform()
    if args.action == "request":
        if args.kind == "input":
            checker = getattr(platform_adapter, "check_input_permission", None)
            opener = getattr(platform_adapter, "open_input_permission_settings", None)
        else:
            checker = getattr(platform_adapter, "check_bluetooth_permission", None)
            opener = getattr(platform_adapter, "open_bluetooth_permission_settings", None)
        if not callable(checker):
            message = f"{args.kind} permission request is not available on this platform"
            if json_output:
                _print_json({"ok": False, "action": args.action, "kind": args.kind, "message": message})
            else:
                print(message)
            return 1
        passed, message = checker(True)
        if not passed and callable(opener):
            opener()
        if json_output:
            _print_json({"ok": bool(passed), "action": args.action, "kind": args.kind, "message": str(message)})
        else:
            print(str(message))
        return 0 if passed else 1

    if args.kind == "input":
        opener = getattr(platform_adapter, "open_input_permission_settings", None)
    else:
        opener = getattr(platform_adapter, "open_bluetooth_permission_settings", None)
    if not callable(opener):
        message = f"{args.kind} permission settings are not available on this platform"
        if json_output:
            _print_json({"ok": False, "action": args.action, "kind": args.kind, "message": message})
        else:
            print(message)
        return 1
    opener()
    message = f"opened {args.kind} permission settings"
    if json_output:
        _print_json({"ok": True, "action": args.action, "kind": args.kind, "message": message})
    else:
        print(message)
    return 0


def invoke_installer(action: str, purge_models: bool = False) -> int:
    root = install_dir()
    if sys.platform == "win32":
        installer = root / "install.ps1"
        if not installer.exists():
            raise RuntimeError("installer metadata is missing; reinstall with the documented one-line command")
        arguments = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer),
            "-Upgrade" if action == "upgrade" else "-Uninstall",
        ]
        if action == "uninstall":
            if purge_models:
                arguments.append("-PurgeModels")
            arguments.extend(("-WaitForPid", str(os.getpid())))
            subprocess.Popen(arguments)
            print("Uninstall started in the background.")
            return 0
        return subprocess.run(arguments).returncode

    installer = root / "install.sh"
    if not installer.exists():
        raise RuntimeError("installer metadata is missing; reinstall with the documented one-line command")
    if action == "uninstall":
        arguments = ["sh", str(installer), "--uninstall"]
        if purge_models:
            arguments.append("--purge-models")
        os.execv("/bin/sh", tuple(arguments))
    return subprocess.run(["/bin/sh", str(installer), "--upgrade"]).returncode


def print_help() -> None:
    print(
        """M5StopWatch BLE speech input

Usage: ble-stt <command> [options]

Commands:
  status       Show service, watch, model, and permission state (default)
  doctor       Diagnose dependencies, permissions, and optional BLE connectivity
  test         Complete one push-to-talk insertion and exit
  journey-test Run the long end-to-end push-to-talk journey test
  prepare      Download and validate the speech model now
  models       Select, install, update, repair, and delete speech models
  mappings     Configure watch event-to-action mappings
  commands     Configure speech command-to-action mappings
  voice-settings Configure correction, dictionaries, typing, and its local model
  logs         Show or follow background service logs
  telemetry    Show live runtime telemetry for the desktop HUD
  performance  Show or clear local end-to-end performance traces
  restart      Restart the login service
  service      Install, inspect, or remove the login service
  permissions  Open platform permission settings
  upgrade      Install the latest stable release
  uninstall    Remove the service and program (models are kept unless requested)
  run          Run the helper in the foreground (development/troubleshooting)

Run 'ble-stt <command> --help' for command-specific options.
"""
    )


def main(argv: Sequence[str] | None = None) -> None:
    values = list(sys.argv[1:] if argv is None else argv)
    # Keep old foreground invocations working while making bare `ble-stt`
    # a quiet management/status command.
    if values and values[0].startswith("-") and values[0] not in ("-h", "--help", "--version"):
        values.insert(0, "run")
    command = values.pop(0) if values else "status"
    try:
        if command in ("-h", "--help", "help"):
            print_help()
            code = 0
        elif command == "--version":
            print(__version__)
            code = 0
        elif command == "status":
            code = show_status(values)
        elif command == "doctor":
            from .doctor import main as doctor_main

            doctor_main(values)
            return
        elif command == "run":
            from .main import main as runtime_main

            runtime_main(values)
            return
        elif command == "test":
            code = run_test(values)
        elif command == "journey-test":
            from .journey import run as journey_test

            code = journey_test(values)
        elif command == "prepare":
            code = prepare(values)
        elif command == "models":
            code = manage_models(values)
        elif command == "mappings":
            code = manage_mappings(values)
        elif command == "commands":
            code = manage_commands(values)
        elif command == "voice-settings":
            code = manage_voice_settings(values)
        elif command == "logs":
            code = show_logs(values)
        elif command == "telemetry":
            code = show_telemetry(values)
        elif command == "performance":
            code = manage_performance(values)
        elif command == "restart":
            json_output = "--json" in values
            restart_values = [value for value in values if value != "--json"]
            argparse.ArgumentParser(prog="ble-stt restart").parse_args(restart_values)
            ServiceManager().restart()
            if json_output:
                _print_json({"ok": True, "action": "restart", "message": "background helper restarted"})
            else:
                print("[ok] Background helper restarted.")
            code = 0
        elif command == "service":
            from .service import main as service_main

            service_main(values)
            return
        elif command == "permissions":
            code = manage_permissions(values)
        elif command in ("upgrade", "uninstall"):
            if command == "uninstall":
                parser = argparse.ArgumentParser(prog="ble-stt uninstall")
                parser.add_argument("--purge-models", action="store_true")
                uninstall_args = parser.parse_args(values)
                code = invoke_installer(command, uninstall_args.purge_models)
            else:
                argparse.ArgumentParser(prog="ble-stt upgrade").parse_args(values)
                code = invoke_installer(command)
        else:
            print(f"Unknown command: {command}\n", file=sys.stderr)
            print_help()
            code = 2
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        code = 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 1
    raise SystemExit(code)
