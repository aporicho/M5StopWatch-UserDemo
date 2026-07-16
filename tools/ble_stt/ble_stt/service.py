from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .config import log_dir

SERVICE_LABEL = "com.aporicho.m5stopwatch-ble-stt"
WINDOWS_TASK_NAME = "M5StopWatch BLE STT"


def service_arguments(extra_args: list[str] | None = None) -> list[str]:
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
        arguments = service_arguments(extra_args)
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
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(render_launch_agent(arguments, self.stdout_path, self.stderr_path))
            domain = f"gui/{os.getuid()}"
            self._run(["launchctl", "bootout", domain, str(path)], check=False)
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
            self._run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], check=False)
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
            command = ["launchctl", "bootout", f"gui/{os.getuid()}", str(path)]
        elif self.platform_name == "win32":
            command = ["schtasks", "/End", "/TN", WINDOWS_TASK_NAME]
        else:
            raise RuntimeError(f"unsupported platform: {self.platform_name}")
        subprocess.run(command, text=True, capture_output=True)

    def start(self) -> None:
        if not self.is_installed():
            return
        if self.platform_name == "linux":
            command = ["systemctl", "--user", "start", "m5stopwatch-ble-stt.service"]
        elif self.platform_name == "darwin":
            path = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
            command = ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)]
        elif self.platform_name == "win32":
            command = ["schtasks", "/Run", "/TN", WINDOWS_TASK_NAME]
        else:
            raise RuntimeError(f"unsupported platform: {self.platform_name}")
        subprocess.run(command, check=True, text=True)

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


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage the M5StopWatch STT login service")
    parser.add_argument("action", choices=("install", "status", "uninstall"))
    parser.add_argument("service_args", nargs=argparse.REMAINDER, help="arguments passed to ble-stt after --")
    args = parser.parse_args(argv)
    manager = ServiceManager()
    service_args = args.service_args[1:] if args.service_args[:1] == ["--"] else args.service_args
    if args.action == "install":
        path = manager.install(service_args)
        location = f" at {path}" if path else ""
        print(f"service installed{location}")
    elif args.action == "uninstall":
        manager.uninstall()
        print("service uninstalled")
    else:
        raise SystemExit(manager.status())


if __name__ == "__main__":
    main()
