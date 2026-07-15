from __future__ import annotations

from typing import Any

from ..protocol import DEVICE_NAME
from .base import PlatformAdapter


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


class WindowsTextInjector:
    def __init__(self, api: Any | None = None) -> None:
        self.api = api or _WindowsAPI()

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

    async def find_device(self, explicit_identifier: str | None):
        from bleak import BleakScanner
        from bleak.backends.device import BLEDevice

        identifier = explicit_identifier or await self.paired_identifier()
        if identifier:
            print(f"[ble] using cached Windows device {identifier}")
            device = await BleakScanner.find_device_by_address(identifier, timeout=3)
            if device is not None:
                return device
            # A BLE HID peripheral normally stops advertising after Windows
            # connects it. Passing a BLEDevice makes Bleak's WinRT backend use
            # BluetoothLEDevice.FromBluetoothAddressAsync and the system cache
            # instead of starting a second advertisement scan.
            return BLEDevice(identifier, DEVICE_NAME, None)
        return await super().find_device(None)
