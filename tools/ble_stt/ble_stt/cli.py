from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import UserConfig, install_dir, log_dir
from .diagnostics import event_log_paths
from .platforms import create_platform
from .recognizers import prepare_recognizer
from .service import ServiceManager
from .status import collect_status, snapshot_to_dict, status_lines


COMMANDS = {
    "run",
    "status",
    "doctor",
    "test",
    "journey-test",
    "logs",
    "restart",
    "service",
    "upgrade",
    "uninstall",
    "prepare",
    "permissions",
    "help",
}


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
    parser.add_argument("--engine", choices=("auto", "faster-whisper", "mlx"), default="auto")
    parser.add_argument("--model", default="medium")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--cpu-threads", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    args = parser.parse_args(argv)
    resolved = prepare_recognizer(args.engine, args.model, args.device, args.cpu_threads)
    config = UserConfig()
    config.set("engine", args.engine)
    config.set("model", args.model)
    config.set("prepared_model", resolved)
    return 0


def _read_log_bundle(lines: int) -> dict[str, object]:
    limit = max(0, lines)
    files: list[dict[str, object]] = []
    entries: list[dict[str, str]] = []
    for path in event_log_paths():
        if not path.exists() or not path.is_file():
            files.append({"name": path.name, "path": str(path), "exists": False, "lines": []})
            continue
        try:
            values = path.read_text(encoding="utf-8", errors="replace").splitlines()
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
        entries.extend({"source": path.name, "line": line} for line in tail)
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
  logs         Show or follow background service logs
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
        elif command == "logs":
            code = show_logs(values)
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
