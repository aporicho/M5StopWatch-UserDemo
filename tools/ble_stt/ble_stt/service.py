from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .config import log_dir

SERVICE_LABEL = "com.aporicho.m5stopwatch-ble-stt"
WINDOWS_TASK_NAME = "M5StopWatch BLE STT"


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def service_arguments(extra_args: list[str] | None = None, platform_name: str | None = None) -> list[str]:
    platform = platform_name or sys.platform
    if platform == "darwin":
        service_runner = os.environ.get("BLE_STT_SERVICE_RUNNER")
        if service_runner:
            return [service_runner, "service-run", *(extra_args or [])]
        service_helper = os.environ.get("BLE_STT_SERVICE_HELPER")
        if service_helper:
            return [service_helper, "run", *(extra_args or [])]
    if platform == "darwin" and getattr(sys, "frozen", False):
        return [sys.executable, "run", *(extra_args or [])]

    arguments = [sys.executable]
    if not getattr(sys, "frozen", False):
        arguments.extend(("-m", "ble_stt"))
    return [*arguments, "run", *(extra_args or [])]


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_systemd_unit(arguments: list[str], stdout_path: Path, stderr_path: Path) -> str:
    command = " ".join(_systemd_quote(value) for value in arguments)
    return f"""[Unit]
Description=M5StopWatch BLE push-to-talk speech input
After=bluetooth.target graphical-session.target
Wants=bluetooth.target

[Service]
Type=simple
ExecStart={command}
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:{stdout_path}
StandardError=append:{stderr_path}

[Install]
WantedBy=default.target
"""


def render_launch_agent(arguments: list[str], stdout_path: Path, stderr_path: Path) -> bytes:
    if arguments[:4] == ["/usr/bin/open", "-W", "-g", "-j"]:
        arguments = [
            *arguments[:4],
            "--stdout",
            str(stdout_path),
            "--stderr",
            str(stderr_path),
            *arguments[4:],
        ]
    return plistlib.dumps(
        {
            "Label": SERVICE_LABEL,
            "ProgramArguments": arguments,
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ProcessType": "Interactive",
            "LimitLoadToSessionType": "Aqua",
            "StandardOutPath": str(stdout_path),
            "StandardErrorPath": str(stderr_path),
            "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        },
        fmt=plistlib.FMT_XML,
        sort_keys=False,
    )


def _macos_open_bundle_argument(arguments: Sequence[str]) -> Path | None:
    if not arguments or arguments[0] != "/usr/bin/open":
        return None
    for argument in arguments[1:]:
        if argument == "--args":
            break
        if argument.endswith(".app"):
            return Path(argument)
    return None


def _read_launch_agent_arguments(path: Path) -> list[str]:
    try:
        with path.open("rb") as stream:
            value = plistlib.load(stream).get("ProgramArguments", [])
    except Exception:
        return []
    return [str(argument) for argument in value]


def _macos_bundle_executable_name(app_bundle: Path) -> str | None:
    plist_path = app_bundle / "Contents" / "Info.plist"
    try:
        with plist_path.open("rb") as stream:
            executable = plistlib.load(stream).get("CFBundleExecutable")
    except Exception:
        return None
    return str(executable) if executable else None


def _terminate_macos_open_child(arguments: Sequence[str]) -> None:
    app_bundle = _macos_open_bundle_argument(arguments)
    if app_bundle is None:
        return
    executable = _macos_bundle_executable_name(app_bundle)
    if executable:
        subprocess.run(["pkill", "-x", executable], text=True, capture_output=True)


def windows_task_action(arguments: list[str]) -> str:
    return subprocess.list2cmdline(arguments)


class ServiceManager:
    def __init__(self, platform_name: str | None = None) -> None:
        self.platform_name = platform_name or sys.platform
        self.logs = log_dir(self.platform_name)
        self.stdout_path = self.logs / "ble-stt.log"
        self.stderr_path = self.logs / "ble-stt-error.log"

    def _run(self, command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, check=check, text=True, capture_output=not check)

    def install(self, extra_args: list[str]) -> Path | None:
        self.logs.mkdir(parents=True, exist_ok=True)
        arguments = service_arguments(extra_args, self.platform_name)
        if self.platform_name == "linux":
            runners = (
                Path(sys.executable).parent / "ble-stt-run-service",
                Path(__file__).resolve().parent.parent / "run-service.sh",
            )
            runner = next((value for value in runners if value.exists()), None)
            if runner is not None:
                arguments = [str(runner), *extra_args]
            path = Path.home() / ".config" / "systemd" / "user" / "m5stopwatch-ble-stt.service"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_systemd_unit(arguments, self.stdout_path, self.stderr_path), encoding="utf-8")
            self._run(["systemctl", "--user", "daemon-reload"])
            self._run(["systemctl", "--user", "enable", "--now", path.name])
            return path
        if self.platform_name == "darwin":
            path = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
            previous_arguments = _read_launch_agent_arguments(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(render_launch_agent(arguments, self.stdout_path, self.stderr_path))
            domain = f"gui/{os.getuid()}"
            self._run(["launchctl", "bootout", domain, str(path)], check=False)
            _terminate_macos_open_child(previous_arguments)
            self._run(["launchctl", "bootstrap", domain, str(path)])
            return path
        if self.platform_name == "win32":
            arguments = [sys.executable, "-m", "ble_stt.daemon", *extra_args]
            action = windows_task_action(arguments)
            self._run(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    WINDOWS_TASK_NAME,
                    "/SC",
                    "ONLOGON",
                    "/TR",
                    action,
                    "/RL",
                    "LIMITED",
                    "/IT",
                    "/F",
                ]
            )
            self._run(["schtasks", "/Run", "/TN", WINDOWS_TASK_NAME])
            return None
        raise RuntimeError(f"unsupported platform: {self.platform_name}")

    def uninstall(self) -> None:
        if self.platform_name == "linux":
            path = Path.home() / ".config" / "systemd" / "user" / "m5stopwatch-ble-stt.service"
            self._run(["systemctl", "--user", "disable", "--now", path.name], check=False)
            path.unlink(missing_ok=True)
            self._run(["systemctl", "--user", "daemon-reload"])
            return
        if self.platform_name == "darwin":
            path = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
            arguments = _read_launch_agent_arguments(path)
            self._run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], check=False)
            _terminate_macos_open_child(arguments)
            path.unlink(missing_ok=True)
            return
        if self.platform_name == "win32":
            self._run(["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"], check=False)
            return
        raise RuntimeError(f"unsupported platform: {self.platform_name}")

    def is_installed(self) -> bool:
        if self.platform_name == "linux":
            return (Path.home() / ".config" / "systemd" / "user" / "m5stopwatch-ble-stt.service").exists()
        if self.platform_name == "darwin":
            return (Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist").exists()
        if self.platform_name == "win32":
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME], text=True, capture_output=True
            )
            return result.returncode == 0
        return False

    def is_active(self) -> bool:
        if not self.is_installed():
            return False
        if self.platform_name == "linux":
            command = ["systemctl", "--user", "is-active", "--quiet", "m5stopwatch-ble-stt.service"]
        elif self.platform_name == "darwin":
            command = ["launchctl", "print", f"gui/{os.getuid()}/{SERVICE_LABEL}"]
        elif self.platform_name == "win32":
            expression = (
                f"if ((Get-ScheduledTask -TaskName '{WINDOWS_TASK_NAME}').State -eq 'Running') "
                "{ exit 0 } else { exit 1 }"
            )
            command = ["powershell", "-NoProfile", "-Command", expression]
        else:
            return False
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            return False
        if self.platform_name == "darwin":
            return any(line.strip() == "state = running" for line in result.stdout.splitlines())
        return True

    def stop(self) -> None:
        if not self.is_installed():
            return
        if self.platform_name == "linux":
            command = ["systemctl", "--user", "stop", "m5stopwatch-ble-stt.service"]
        elif self.platform_name == "darwin":
            path = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
            arguments = _read_launch_agent_arguments(path)
            command = ["launchctl", "bootout", f"gui/{os.getuid()}", str(path)]
        elif self.platform_name == "win32":
            command = ["schtasks", "/End", "/TN", WINDOWS_TASK_NAME]
        else:
            raise RuntimeError(f"unsupported platform: {self.platform_name}")
        subprocess.run(command, text=True, capture_output=True)
        if self.platform_name == "darwin":
            _terminate_macos_open_child(arguments)

    def start(self) -> None:
        if not self.is_installed():
            return
        if self.platform_name == "linux":
            command = ["systemctl", "--user", "start", "m5stopwatch-ble-stt.service"]
            subprocess.run(command, check=True, text=True)
            return
        elif self.platform_name == "darwin":
            path = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
            domain = f"gui/{os.getuid()}"
            service = f"{domain}/{SERVICE_LABEL}"
            loaded = subprocess.run(
                ["launchctl", "print", service],
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode == 0
            if loaded:
                subprocess.run(["launchctl", "kickstart", "-k", service], check=True, text=True)
            else:
                subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True, text=True)
            return
        elif self.platform_name == "win32":
            command = ["schtasks", "/Run", "/TN", WINDOWS_TASK_NAME]
            subprocess.run(command, check=True, text=True)
            return
        else:
            raise RuntimeError(f"unsupported platform: {self.platform_name}")

    def restart(self) -> None:
        if not self.is_installed():
            raise RuntimeError("the login service is not installed")
        if self.platform_name == "linux":
            subprocess.run(
                ["systemctl", "--user", "restart", "m5stopwatch-ble-stt.service"], check=True, text=True
            )
            return
        self.stop()
        self.start()

    def status(self) -> int:
        if self.platform_name == "linux":
            command = ["systemctl", "--user", "status", "m5stopwatch-ble-stt.service"]
        elif self.platform_name == "darwin":
            command = ["launchctl", "print", f"gui/{os.getuid()}/{SERVICE_LABEL}"]
        elif self.platform_name == "win32":
            command = ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME, "/V", "/FO", "LIST"]
        else:
            raise RuntimeError(f"unsupported platform: {self.platform_name}")
        result = subprocess.run(command, text=True, capture_output=True)
        output = result.stdout if result.returncode == 0 else result.stderr
        print(output.rstrip())
        if self.platform_name == "darwin" and result.returncode == 0:
            running = any(line.strip() == "state = running" for line in result.stdout.splitlines())
            return 0 if running else 1
        return result.returncode


def service_state(manager: ServiceManager) -> dict[str, object]:
    try:
        installed = manager.is_installed()
        running = manager.is_active() if installed else False
        error = None
    except Exception as exc:
        installed = False
        running = False
        error = str(exc)
    return {
        "platform": manager.platform_name,
        "installed": installed,
        "running": running,
        "error": error,
        "stdout": str(manager.stdout_path),
        "stderr": str(manager.stderr_path),
    }


def main(argv: Sequence[str] | None = None) -> None:
    values = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in values
    values = [value for value in values if value != "--json"]
    parser = argparse.ArgumentParser(description="Manage the M5StopWatch STT login service")
    parser.add_argument("action", choices=("install", "status", "uninstall", "start", "stop", "restart"))
    parser.add_argument("service_args", nargs=argparse.REMAINDER, help="arguments passed to ble-stt after --")
    args = parser.parse_args(values)
    manager = ServiceManager()
    service_args = args.service_args[1:] if args.service_args[:1] == ["--"] else args.service_args
    try:
        if args.action == "install":
            path = manager.install(service_args)
            message = f"service installed at {path}" if path else "service installed"
            payload: dict[str, object] = {"ok": True, "action": args.action, "message": message}
            if path:
                payload["path"] = str(path)
            code = 0
        elif args.action == "uninstall":
            manager.uninstall()
            payload = {"ok": True, "action": args.action, "message": "service uninstalled"}
            code = 0
        elif args.action == "start":
            manager.start()
            payload = {"ok": True, "action": args.action, "message": "service started"}
            code = 0
        elif args.action == "stop":
            manager.stop()
            payload = {"ok": True, "action": args.action, "message": "service stopped"}
            code = 0
        elif args.action == "restart":
            manager.restart()
            payload = {"ok": True, "action": args.action, "message": "service restarted"}
            code = 0
        else:
            if json_output:
                payload = {"ok": True, "action": args.action, "service": service_state(manager)}
                code = 0
            else:
                raise SystemExit(manager.status())
    except Exception as exc:
        payload = {"ok": False, "action": args.action, "message": str(exc)}
        code = 1

    if json_output:
        payload["service"] = service_state(manager)
        _print_json(payload)
    else:
        print(str(payload.get("message", "")))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
