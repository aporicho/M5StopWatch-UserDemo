from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import UserConfig, install_dir, log_dir
from .platforms import create_platform
from .recognizers import prepare_recognizer, resolve_engine, resolve_model
from .service import ServiceManager


COMMANDS = {
    "run",
    "status",
    "doctor",
    "test",
    "logs",
    "restart",
    "upgrade",
    "uninstall",
    "prepare",
    "help",
}


def _line(ok: bool, label: str, detail: str) -> None:
    print(f"[{'ok' if ok else 'fail'}] {label}: {detail}")


def show_status() -> int:
    print(f"M5StopWatch BLE STT {__version__}")
    manager = ServiceManager()
    installed = manager.is_installed()
    active = manager.is_active() if installed else False
    _line(installed, "login service", "running" if active else ("stopped" if installed else "not installed"))

    config = UserConfig()
    device = config.get("device_id")
    _line(bool(device), "watch", f"cached as {device}" if device else "not paired yet")
    engine = resolve_engine(str(config.get("engine", "auto")))
    model = resolve_model(engine, str(config.get("model", "medium")))
    _line(True, "recognition", f"{engine} / {model}")

    try:
        allowed, message = create_platform().check_input_permission(False)
    except Exception as exc:
        allowed, message = False, str(exc)
    _line(allowed, "text input", message)
    print(f"Logs: {log_dir()}")
    if not all((installed, active, device, allowed)):
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

        runtime_main(["--once", *argv])
    finally:
        if was_active:
            print("Restarting the background helper...")
            manager.start()
    print("[ok] Speech was recognized and inserted into the focused window.")
    return 0


def show_logs(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ble-stt logs", description="Show recent helper logs")
    parser.add_argument("-n", "--lines", type=int, default=80)
    parser.add_argument("-f", "--follow", action="store_true")
    args = parser.parse_args(argv)
    paths = (log_dir() / "ble-stt.log", log_dir() / "ble-stt-error.log")
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
  logs         Show or follow background service logs
  restart      Restart the login service
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
            code = show_status()
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
        elif command == "prepare":
            code = prepare(values)
        elif command == "logs":
            code = show_logs(values)
        elif command == "restart":
            ServiceManager().restart()
            print("[ok] Background helper restarted.")
            code = 0
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
