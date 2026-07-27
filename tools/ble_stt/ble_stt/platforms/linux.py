from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from ..protocol import AUDIO_UUID, DEVICE_NAME
from .base import PlatformAdapter

HID_TO_WTYPE_KEY = {
    **{0x04 + index: chr(ord("a") + index) for index in range(26)},
    0x28: "Return",
    0x29: "Escape",
    0x2A: "BackSpace",
    0x2B: "Tab",
    0x2C: "space",
    0x4A: "Home",
    0x4B: "Prior",
    0x4C: "Delete",
    0x4D: "End",
    0x4E: "Next",
    0x4F: "Right",
    0x50: "Left",
    0x51: "Down",
    0x52: "Up",
    **{0x3A + index: f"F{index + 1}" for index in range(12)},
}
MODIFIER_TO_WTYPE = ((0x01, "ctrl"), (0x02, "shift"), (0x04, "alt"), (0x08, "logo"))
class LinuxTextInjector:
    def __init__(self) -> None:
        self._warned_no_focus = False

    @staticmethod
    def active_window() -> str | None:
        try:
            result = subprocess.run(
                ["hyprctl", "activewindow", "-j"], check=True, capture_output=True, text=True, timeout=2
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        try:
            value = json.loads(result.stdout).get("address")
        except (json.JSONDecodeError, AttributeError):
            return None
        return str(value) if value else None

    def type_text(self, text: str, expected_window: object | None) -> bool:
        if not text:
            return True
        current = self.active_window()
        if expected_window and current != expected_window:
            print("[focus] active window changed; suppressing text injection")
            return False
        if expected_window is None and not self._warned_no_focus:
            print("[focus] unable to read Hyprland active window; typing into the current focus")
            self._warned_no_focus = True
        try:
            subprocess.run(["wtype", "--", text], check=True, env=os.environ.copy())
        except FileNotFoundError:
            raise RuntimeError("wtype is not installed") from None
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"wtype failed with exit code {exc.returncode}") from exc
        return True

    def tap_key(self, key_code: int, modifiers: int, expected_window: object | None) -> bool:
        current = self.active_window()
        if expected_window and current != expected_window:
            print("[focus] active window changed; suppressing key action")
            return False
        key_name = HID_TO_WTYPE_KEY.get(key_code)
        if key_name is None:
            raise RuntimeError(f"unsupported HID key code for Linux fallback: 0x{key_code:02x}")
        command = ["wtype"]
        active_modifiers = [name for bit, name in MODIFIER_TO_WTYPE if modifiers & bit]
        for name in active_modifiers:
            command.extend(["-M", name])
        command.extend(["-k", key_name])
        for name in reversed(active_modifiers):
            command.extend(["-m", name])
        try:
            subprocess.run(command, check=True, env=os.environ.copy())
        except FileNotFoundError:
            raise RuntimeError("wtype is not installed") from None
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"wtype failed with exit code {exc.returncode}") from exc
        return True


class LinuxPlatform(PlatformAdapter):
    name = "linux"

    def create_text_injector(self) -> LinuxTextInjector:
        return LinuxTextInjector()

    def validate_runtime(self) -> None:
        missing = [command for command in ("bluetoothctl", "hyprctl", "wtype") if shutil.which(command) is None]
        if missing:
            raise RuntimeError(f"missing Linux command(s): {', '.join(missing)}")

    def check_input_permission(self, prompt: bool = False) -> tuple[bool, str]:
        missing = [command for command in ("hyprctl", "wtype") if shutil.which(command) is None]
        if missing:
            return False, f"missing command(s): {', '.join(missing)}"
        return True, "Hyprland focus detection and wtype are available"

    async def paired_identifier(self) -> str | None:
        if shutil.which("bluetoothctl") is not None:
            try:
                result = subprocess.run(
                    ["bluetoothctl", "devices", "Paired"], check=True, capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.splitlines():
                    parts = line.split(maxsplit=2)
                    if len(parts) == 3 and parts[0] == "Device" and parts[2] == DEVICE_NAME:
                        return parts[1]
            except subprocess.SubprocessError:
                pass
        return await super().paired_identifier()

    async def find_connected_device(self, explicit_identifier: str | None):
        if shutil.which("bluetoothctl") is None:
            return None
        candidates: list[str] = []
        if explicit_identifier:
            candidates.append(explicit_identifier)
        cached = await super().paired_identifier()
        if cached and cached not in candidates:
            candidates.append(cached)
        try:
            paired = subprocess.run(
                ["bluetoothctl", "devices", "Paired"], check=False, capture_output=True, text=True, timeout=5
            )
        except subprocess.SubprocessError:
            return None
        for line in paired.stdout.splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) == 3 and parts[0] == "Device" and parts[2] == DEVICE_NAME and parts[1] not in candidates:
                candidates.append(parts[1])
        for identifier in candidates:
            try:
                result = subprocess.run(
                    ["bluetoothctl", "info", identifier],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except subprocess.SubprocessError:
                continue
            properties = {
                key.strip().casefold(): value.strip().casefold()
                for line in result.stdout.splitlines()
                if ":" in line
                for key, value in [line.strip().split(":", 1)]
            }
            if properties.get("paired") == "yes" and properties.get("connected") == "yes":
                self.config.set("device_id", identifier)
                return identifier
        return None

    async def prepare_client(self, client: Any, device: Any) -> None:
        if not isinstance(device, str):
            return
        backend = getattr(client, "_backend", None)
        get_path = getattr(backend, "_get_device_path", None)
        if get_path is not None:
            backend._device_path = await get_path()

    async def acquire_mtu(self, client: Any) -> int:
        backend = getattr(client, "_backend", None)
        if backend is None:
            return int(client.mtu_size)

        from bleak.backends.bluezdbus import defs
        from bleak.backends.bluezdbus.utils import assert_reply
        from dbus_fast.message import Message

        characteristic = client.services.get_characteristic(AUDIO_UUID)
        if characteristic is None:
            raise RuntimeError("speech audio characteristic is missing")
        reply = await backend._bus.call(
            Message(
                destination=defs.BLUEZ_SERVICE,
                path=characteristic.obj[0],
                interface=defs.GATT_CHARACTERISTIC_INTERFACE,
                member="AcquireNotify",
                signature="a{sv}",
                body=[{}],
            )
        )
        assert_reply(reply)
        os.close(reply.unix_fds[0])
        backend._mtu_size = int(reply.body[1])
        return int(client.mtu_size)
