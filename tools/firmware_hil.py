#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


RESPONSE_PREFIX = "@@M5TEST "
CENTER_ICON_X = 233
CENTER_ICON_Y = 218
ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT / "build-test"
TEST_SDKCONFIG = BUILD_DIR / "sdkconfig"
REQUIRED_TEST_CONFIG = (
    "CONFIG_M5_TEST_CONTROL=y",
    "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y",
    "CONFIG_BT_NIMBLE_SVC_HID_MAX_RPTS=4",
)


class HilError(RuntimeError):
    pass


class FirmwareControl:
    def __init__(self, port: str, baud: int = 115200) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise HilError("pyserial is required for firmware HIL tests: python -m pip install pyserial") from exc
        self._serial = serial.Serial(port, baudrate=baud, timeout=0.1, write_timeout=2)

    def close(self) -> None:
        self._serial.close()

    def request(self, payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        expected = payload.get("cmd")
        line = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\r\n"
        self._serial.write(line)
        self._serial.flush()
        deadline = time.monotonic() + timeout
        last_line = ""
        while time.monotonic() < deadline:
            raw = self._serial.readline()
            if not raw:
                continue
            decoded = raw.decode("utf-8", errors="replace").strip()
            last_line = decoded
            if not decoded.startswith(RESPONSE_PREFIX):
                continue
            response = json.loads(decoded[len(RESPONSE_PREFIX) :])
            if expected is None or response.get("cmd") == expected:
                if not response.get("ok", False):
                    raise HilError(response.get("message", "firmware command failed"))
                return response
        raise HilError(f"timed out waiting for {expected!r}; last serial line: {last_line}")

    def ping(self, timeout: float = 10.0) -> dict[str, Any]:
        return self.request({"cmd": "ping"}, timeout=timeout)

    def state(self) -> dict[str, Any]:
        return self.request({"cmd": "state"})

    def apps(self) -> dict[str, Any]:
        return self.request({"cmd": "apps"})

    def ble_state(self) -> dict[str, Any]:
        return self.request({"cmd": "ble_state"})

    def button(self, button: str, state: str) -> None:
        self.request({"cmd": "button", "button": button, "state": state})

    def touch(self, state: str, x: int | None = None, y: int | None = None) -> None:
        payload: dict[str, Any] = {"cmd": "touch", "state": state}
        if x is not None:
            payload["x"] = x
        if y is not None:
            payload["y"] = y
        self.request(payload)

    def clear_input(self) -> None:
        self.request({"cmd": "clear_input"})

    def button_tap(self, button: str, down_seconds: float = 0.08) -> None:
        self.button(button, "down")
        time.sleep(down_seconds)
        self.button(button, "up")
        time.sleep(0.16)
        self.clear_input()
        time.sleep(0.05)

    def button_hold(self, button: str, hold_seconds: float = 0.75) -> None:
        self.button(button, "down")
        time.sleep(hold_seconds)

    def button_release(self, button: str) -> None:
        self.button(button, "up")
        time.sleep(0.16)
        self.clear_input()

    def tap(self, x: int, y: int, down_seconds: float = 0.12) -> None:
        self.touch("down", x, y)
        time.sleep(down_seconds)
        self.touch("up")
        time.sleep(0.18)
        self.clear_input()

    def swipe(self, start: tuple[int, int], end: tuple[int, int], steps: int = 6) -> None:
        self.touch("down", *start)
        for index in range(1, steps + 1):
            x = start[0] + (end[0] - start[0]) * index // steps
            y = start[1] + (end[1] - start[1]) * index // steps
            time.sleep(0.04)
            self.touch("move", x, y)
        self.touch("up")
        time.sleep(0.18)
        self.clear_input()


def detect_port() -> str:
    candidates: list[str] = []
    for pattern in (
        "/dev/cu.usbmodem*",
        "/dev/cu.usbserial*",
        "/dev/cu.SLAB*",
        "/dev/cu.wchusbserial*",
        "/dev/ttyACM*",
        "/dev/ttyUSB*",
        "COM*",
    ):
        candidates.extend(sorted(glob.glob(pattern)))
    if not candidates:
        raise HilError("serial port was not provided and no USB serial device was found")
    return candidates[0]


def app_names_for_launcher(apps_response: dict[str, Any]) -> list[str]:
    return [item["name"] for item in apps_response.get("apps", []) if item.get("name") != "Launcher"]


def wait_for(
    label: str,
    read: Callable[[], dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
    timeout: float,
    interval: float = 0.25,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = read()
        if predicate(last):
            return last
        time.sleep(interval)
    raise HilError(f"timed out waiting for {label}; last={json.dumps(last, ensure_ascii=False)}")


def wait_for_serial_port(port: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if Path(port).exists():
            return
        time.sleep(0.25)
    raise HilError(f"serial port did not reappear after flashing: {port}")


def wait_for_test_control(control: FirmwareControl, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return control.ping(timeout=2.0)
        except HilError as exc:
            last_error = exc
            time.sleep(0.5)
    raise HilError(f"test control did not become ready: {last_error}")


def open_app_by_name(control: FirmwareControl, name: str) -> None:
    apps = control.apps()
    if any(
        item.get("name") == name and item.get("state") in ("opening", "running")
        for item in apps.get("apps", [])
    ):
        return

    names = app_names_for_launcher(apps)
    if name not in names:
        raise HilError(f"{name!r} is not installed; apps={names}")
    target = names.index(name)

    state = wait_for(
        "launcher selected index",
        control.apps,
        lambda value: isinstance(value.get("launcher_selected_index"), int)
        and value.get("launcher_selected_index") >= 0,
        timeout=8,
    )
    selected = int(state["launcher_selected_index"])
    count = len(names)
    forward = (target - selected) % count
    backward = (selected - target) % count

    if forward <= backward:
        for _ in range(forward):
            control.button_tap("right")
            time.sleep(0.35)
    else:
        for _ in range(backward):
            control.button_tap("left")
            time.sleep(0.35)

    wait_for(
        f"launcher selecting {name}",
        control.apps,
        lambda value: value.get("launcher_selected_index") == target,
        timeout=8,
    )
    control.tap(CENTER_ICON_X, CENTER_ICON_Y)
    wait_for(
        f"{name} running",
        control.apps,
        lambda value: any(
            item.get("name") == name and item.get("state") in ("opening", "running")
            for item in value.get("apps", [])
        ),
        timeout=8,
    )


def wait_for_ble_remote_open(control: FirmwareControl) -> dict[str, Any]:
    def ready_or_terminal(value: dict[str, Any]) -> bool:
        remote = value.get("ble_remote", {})
        state = remote.get("state")
        if state == "Bluetooth error":
            raise HilError(f"BLE Remote failed: {json.dumps(remote, ensure_ascii=False)}")
        return state in (
            "Waiting for pairing",
            "Reconnecting (directed)",
            "Reconnecting (filtered)",
            "Securing",
            "Connected",
            "Bonded idle",
            "Unpaired idle",
        )

    return wait_for(
        "BLE Remote advertising or connected",
        control.ble_state,
        ready_or_terminal,
        timeout=20,
    )


def run_flash(port: str) -> None:
    cache = BUILD_DIR / "CMakeCache.txt"
    sdkconfig = TEST_SDKCONFIG
    if sdkconfig.exists():
        sdkconfig_text = sdkconfig.read_text(errors="ignore")
        if any(required not in sdkconfig_text for required in REQUIRED_TEST_CONFIG):
            shutil.rmtree(BUILD_DIR)
            cache = BUILD_DIR / "CMakeCache.txt"

    if cache.exists():
        cache_text = cache.read_text(errors="ignore")
        if "SDKCONFIG:FILEPATH=" in cache_text and str(TEST_SDKCONFIG) not in cache_text:
            shutil.rmtree(BUILD_DIR)

    command = [
        "idf.py",
        "-B",
        str(BUILD_DIR),
        "-D",
        f"SDKCONFIG={TEST_SDKCONFIG}",
        "-D",
        "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.defaults.test",
        "-p",
        port,
        "build",
        "flash",
    ]
    subprocess.run(command, check=True, cwd=ROOT)


async def run_ble_check() -> None:
    sys.path.insert(0, str(ROOT / "tools" / "ble_stt"))
    from ble_stt.check import check

    await check(None)


def journey_smoke(args: argparse.Namespace) -> None:
    if args.flash:
        run_flash(args.port)
        wait_for_serial_port(args.port)
        time.sleep(1.5)
    control = FirmwareControl(args.port, args.baud)
    try:
        print("[hil] ping")
        print(json.dumps(wait_for_test_control(control), ensure_ascii=False))
        print("[hil] opening BLE Remote through launcher user input")
        open_app_by_name(control, "BLE Remote")
        print("[hil] waiting for BLE Remote state")
        print(json.dumps(wait_for_ble_remote_open(control), ensure_ascii=False))
        if not args.skip_ble_check:
            print("[hil] running BLE service check")
            asyncio.run(run_ble_check())
        print("[ok] smoke-user-path passed")
    finally:
        control.close()


def journey_voice_link(args: argparse.Namespace) -> None:
    control = FirmwareControl(args.port, args.baud)
    try:
        open_app_by_name(control, "BLE Remote")
        wait_for_ble_remote_open(control)
        control.button_hold("right", 0.75)
        time.sleep(1.0)
        control.button_release("right")
        print(json.dumps(control.ble_state(), ensure_ascii=False))
        print("[ok] voice-link user input sequence completed")
    finally:
        control.close()


def journey_diagnose(args: argparse.Namespace) -> None:
    control = FirmwareControl(args.port, args.baud)
    try:
        print(json.dumps(control.apps(), ensure_ascii=False))
        print(json.dumps(control.ble_state(), ensure_ascii=False))
        print("[hil] opening BLE Remote through user input")
        open_app_by_name(control, "BLE Remote")
        print(json.dumps(wait_for_ble_remote_open(control), ensure_ascii=False))
    finally:
        control.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M5StopWatch firmware user-path HIL automation")
    parser.add_argument("journey", choices=("smoke", "voice-link", "diagnose-not-found"))
    parser.add_argument("--port", default=None, help="serial port, e.g. /dev/cu.usbmodem101")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--flash", action="store_true", help="build and flash the test firmware first")
    parser.add_argument("--skip-ble-check", action="store_true", help="skip desktop BLE scan/connect check")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.port is None:
        args.port = detect_port()
    try:
        if args.journey == "smoke":
            journey_smoke(args)
        elif args.journey == "voice-link":
            journey_voice_link(args)
        else:
            journey_diagnose(args)
    except KeyboardInterrupt:
        return 130
    except (HilError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
