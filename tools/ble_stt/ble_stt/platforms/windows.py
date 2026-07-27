from __future__ import annotations

import base64
import subprocess
from typing import Any

from ..protocol import DEVICE_NAME
from ..types import TextReplacementResult
from .base import PlatformAdapter

HID_TO_WINDOWS_VK = {
    **{0x04 + index: 0x41 + index for index in range(26)},
    0x28: 0x0D,
    0x29: 0x1B,
    0x2A: 0x08,
    0x2B: 0x09,
    0x2C: 0x20,
    0x4A: 0x24,
    0x4B: 0x21,
    0x4C: 0x2E,
    0x4D: 0x23,
    0x4E: 0x22,
    0x4F: 0x27,
    0x50: 0x25,
    0x51: 0x28,
    0x52: 0x26,
    **{0x3A + index: 0x70 + index for index in range(12)},
}
MODIFIER_TO_WINDOWS_VK = ((0x01, 0x11), (0x02, 0x10), (0x04, 0x12), (0x08, 0x5B))


class _WindowsAPI:
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    INPUT_KEYBOARD = 1

    def __init__(self) -> None:
        import ctypes

        self.ctypes = ctypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p

    def foreground_window(self) -> int | None:
        value = self.user32.GetForegroundWindow()
        return int(value) if value else None

    def send_unicode(self, text: str) -> None:
        ctypes = self.ctypes
        from ctypes import wintypes

        ulong_ptr = wintypes.WPARAM

        class KeyboardInput(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class HardwareInput(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [("mi", MouseInput), ("ki", KeyboardInput), ("hi", HardwareInput)]

        class Input(ctypes.Structure):
            _anonymous_ = ("value",)
            _fields_ = [("type", wintypes.DWORD), ("value", InputUnion)]

        encoded = text.encode("utf-16-le")
        units = [
            int.from_bytes(encoded[index : index + 2], "little")
            for index in range(0, len(encoded), 2)
        ]
        events = []
        for unit in units:
            events.append(
                Input(
                    type=self.INPUT_KEYBOARD,
                    value=InputUnion(ki=KeyboardInput(0, unit, self.KEYEVENTF_UNICODE, 0, 0)),
                )
            )
            events.append(
                Input(
                    type=self.INPUT_KEYBOARD,
                    value=InputUnion(
                        ki=KeyboardInput(0, unit, self.KEYEVENTF_UNICODE | self.KEYEVENTF_KEYUP, 0, 0)
                    ),
                )
            )
        array = (Input * len(events))(*events)
        self.user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
        self.user32.SendInput.restype = wintypes.UINT
        sent = int(self.user32.SendInput(len(events), array, ctypes.sizeof(Input)))
        if sent != len(events):
            raise RuntimeError(
                "Windows SendInput was blocked; elevated applications cannot receive input from a normal user process"
            )

    def tap_virtual_key(self, vk: int, modifiers: int) -> None:
        active_modifiers = [modifier_vk for bit, modifier_vk in MODIFIER_TO_WINDOWS_VK if modifiers & bit]
        for modifier_vk in active_modifiers:
            self.user32.keybd_event(modifier_vk, 0, 0, 0)
        self.user32.keybd_event(vk, 0, 0, 0)
        self.user32.keybd_event(vk, 0, self.KEYEVENTF_KEYUP, 0)
        for modifier_vk in reversed(active_modifiers):
            self.user32.keybd_event(modifier_vk, 0, self.KEYEVENTF_KEYUP, 0)


class WindowsTextInjector:
    def __init__(self, api: Any | None = None, selector: Any | None = None) -> None:
        self.api = api or _WindowsAPI()
        self.selector = selector or self._select_verified_suffix

    def active_window(self) -> int | None:
        return self.api.foreground_window()

    def type_text(self, text: str, expected_window: object | None) -> bool:
        if not text:
            return True
        current = self.active_window()
        if expected_window is not None and current != expected_window:
            print("[focus] active window changed; suppressing text injection")
            return False
        for offset in range(0, len(text), 64):
            self.api.send_unicode(text[offset : offset + 64])
        return True

    @staticmethod
    def _select_verified_suffix(expected_suffix: str) -> str:
        encoded_expected = base64.b64encode(expected_suffix.encode("utf-8")).decode("ascii")
        script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
$expected = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_expected}'))
$focused = [System.Windows.Automation.AutomationElement]::FocusedElement
if ($null -eq $focused) {{ Write-Output 'unsupported'; exit 0 }}
$pattern = $null
if (-not $focused.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$pattern)) {{
  Write-Output 'unsupported'; exit 0
}}
$selections = $pattern.GetSelection()
if ($selections.Count -ne 1 -or $selections[0].GetText(-1).Length -ne 0) {{
  Write-Output 'selection_changed'; exit 0
}}
$range = $selections[0].Clone()
$moved = $range.MoveEndpointByUnit(
  [System.Windows.Automation.TextPatternRangeEndpoint]::Start,
  [System.Windows.Automation.TextUnit]::Character,
  -$expected.Length
)
if ($moved -ne -$expected.Length -or $range.GetText(-1) -cne $expected) {{
  Write-Output 'text_mismatch'; exit 0
}}
$range.Select()
Write-Output 'selected'
"""
        encoded_script = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return "unsupported"
        values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return values[-1] if values else "unsupported"

    def replace_verified_suffix(
        self,
        expected_suffix: str,
        replacement: str,
        expected_window: object | None,
    ) -> TextReplacementResult:
        if not expected_suffix:
            return TextReplacementResult(False, "empty_suffix")
        current = self.active_window()
        if expected_window is not None and current != expected_window:
            return TextReplacementResult(False, "focus_changed")
        reason = str(self.selector(expected_suffix))
        if reason != "selected":
            return TextReplacementResult(False, reason)
        if expected_window is not None and self.active_window() != expected_window:
            return TextReplacementResult(False, "focus_changed")
        try:
            self.api.send_unicode(replacement)
        except Exception:
            return TextReplacementResult(False, "insertion_failed")
        return TextReplacementResult(True, "replaced")

    def tap_key(self, key_code: int, modifiers: int, expected_window: object | None) -> bool:
        current = self.active_window()
        if expected_window is not None and current != expected_window:
            print("[focus] active window changed; suppressing key action")
            return False
        vk = HID_TO_WINDOWS_VK.get(key_code)
        if vk is None:
            raise RuntimeError(f"unsupported HID key code for Windows fallback: 0x{key_code:02x}")
        self.api.tap_virtual_key(vk, modifiers)
        return True


class WindowsPlatform(PlatformAdapter):
    name = "windows"

    def create_text_injector(self) -> WindowsTextInjector:
        return WindowsTextInjector()

    def validate_runtime(self) -> None:
        self.create_text_injector()

    def check_input_permission(self, prompt: bool = False) -> tuple[bool, str]:
        try:
            self.create_text_injector().active_window()
        except Exception as exc:
            return False, f"Win32 input API is unavailable: {exc}"
        return True, "Win32 Unicode input is available for non-elevated applications"

    async def paired_identifier(self) -> str | None:
        cached = await super().paired_identifier()
        if cached:
            return cached
        try:
            from winrt.windows.devices.bluetooth import BluetoothLEDevice
            from winrt.windows.devices.enumeration import DeviceInformation

            selector = BluetoothLEDevice.get_device_selector_from_pairing_state(True)
            devices = await DeviceInformation.find_all_async(selector)
            for info in devices:
                if str(info.name) != DEVICE_NAME:
                    continue
                device = await BluetoothLEDevice.from_id_async(info.id)
                if device is None:
                    continue
                try:
                    raw_address = int(device.bluetooth_address)
                    identifier = ":".join(
                        f"{value:02X}" for value in raw_address.to_bytes(6, byteorder="big")
                    )
                    self.config.set("device_id", identifier)
                    return identifier
                finally:
                    device.close()
        except Exception as exc:
            print(f"[ble] Windows paired-device lookup failed: {exc}")
        return None

    async def find_connected_device(self, explicit_identifier: str | None):
        from bleak.backends.device import BLEDevice
        from winrt.windows.devices.bluetooth import BluetoothConnectionStatus, BluetoothLEDevice
        from winrt.windows.devices.enumeration import DeviceInformation

        connected = getattr(
            BluetoothConnectionStatus,
            "CONNECTED",
            getattr(BluetoothConnectionStatus, "connected", 1),
        )
        try:
            selector = BluetoothLEDevice.get_device_selector_from_pairing_state(True)
            devices = await DeviceInformation.find_all_async(selector)
            matches = [info for info in devices if str(info.name) == DEVICE_NAME]
            for info in matches:
                system_device = await BluetoothLEDevice.from_id_async(info.id)
                if system_device is None:
                    continue
                try:
                    if system_device.connection_status != connected:
                        continue
                    raw_address = int(system_device.bluetooth_address)
                    identifier = ":".join(f"{value:02X}" for value in raw_address.to_bytes(6, byteorder="big"))
                    self.config.set("device_id", identifier)
                    return BLEDevice(identifier, DEVICE_NAME, None)
                finally:
                    system_device.close()
        except Exception as exc:
            print(f"[ble] Windows connected-device lookup failed: {exc}")
        # Explicit identifiers remain useful for diagnostics, but are still
        # gated by ConnectionStatus and never handed to Bleak while offline.
        identifier = explicit_identifier
        if identifier:
            try:
                raw_address = int(identifier.replace(":", ""), 16)
                system_device = await BluetoothLEDevice.from_bluetooth_address_async(raw_address)
                if system_device is not None:
                    try:
                        if system_device.connection_status == connected:
                            return BLEDevice(identifier, DEVICE_NAME, None)
                    finally:
                        system_device.close()
            except Exception:
                pass
        return None
