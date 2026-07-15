from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any

from ..protocol import DEVICE_NAME, SERVICE_UUID
from .base import PlatformAdapter


@dataclass(frozen=True)
class MacWindowToken:
    pid: int
    window: object | None


class MacOSTextInjector:
    def __init__(self, quartz: Any | None = None, appkit: Any | None = None) -> None:
        if quartz is None:
            import Quartz

            quartz = Quartz
        if appkit is None:
            import AppKit

            appkit = AppKit
        self.quartz = quartz
        self.appkit = appkit
        self._warned_no_window = False

    def check_accessibility(self, prompt: bool = False) -> bool:
        options = {self.quartz.kAXTrustedCheckOptionPrompt: bool(prompt)}
        return bool(self.quartz.AXIsProcessTrustedWithOptions(options))

    def _copy_ax_value(self, element: object, attribute: str) -> object | None:
        try:
            result = self.quartz.AXUIElementCopyAttributeValue(element, attribute, None)
        except Exception:
            return None
        if isinstance(result, tuple):
            if len(result) >= 2 and int(result[0]) == 0:
                return result[-1]
            return None
        return result

    def active_window(self) -> MacWindowToken | None:
        application = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if application is None:
            return None
        pid = int(application.processIdentifier())
        ax_application = self.quartz.AXUIElementCreateApplication(pid)
        window = self._copy_ax_value(ax_application, self.quartz.kAXFocusedWindowAttribute)
        return MacWindowToken(pid, window)

    def _same_window(self, expected: MacWindowToken, current: MacWindowToken) -> bool:
        if expected.pid != current.pid:
            return False
        if expected.window is None or current.window is None:
            return True
        compare = getattr(self.quartz, "CFEqual", None)
        if compare is not None:
            try:
                return bool(compare(expected.window, current.window))
            except Exception:
                pass
        return expected.window == current.window

    def _post_unicode(self, text: str) -> None:
        source = self.quartz.CGEventSourceCreate(self.quartz.kCGEventSourceStateCombinedSessionState)
        for offset in range(0, len(text), 20):
            chunk = text[offset : offset + 20]
            key_down = self.quartz.CGEventCreateKeyboardEvent(source, 0, True)
            key_up = self.quartz.CGEventCreateKeyboardEvent(source, 0, False)
            if key_down is None or key_up is None:
                raise RuntimeError("failed to create macOS keyboard event")
            self.quartz.CGEventKeyboardSetUnicodeString(key_down, len(chunk), chunk)
            self.quartz.CGEventPost(self.quartz.kCGHIDEventTap, key_down)
            self.quartz.CGEventPost(self.quartz.kCGHIDEventTap, key_up)

    def type_text(self, text: str, expected_window: object | None) -> bool:
        if not text:
            return True
        if not self.check_accessibility(False):
            raise RuntimeError(
                "Accessibility permission is required; run 'ble-stt-doctor --request-permissions' and allow Python"
            )
        current = self.active_window()
        if isinstance(expected_window, MacWindowToken):
            if current is None or not self._same_window(expected_window, current):
                print("[focus] active window changed; suppressing text injection")
                return False
            if expected_window.window is None and not self._warned_no_window:
                print("[focus] focused window is unavailable; protecting by frontmost application only")
                self._warned_no_window = True
        self._post_unicode(text)
        return True


class MacOSPlatform(PlatformAdapter):
    name = "macos"

    def create_text_injector(self) -> MacOSTextInjector:
        return MacOSTextInjector()

    def validate_runtime(self) -> None:
        if platform.machine().lower() != "arm64":
            raise RuntimeError("the macOS MLX backend requires Apple Silicon")
        injector = self.create_text_injector()
        if not injector.check_accessibility(False):
            raise RuntimeError(
                "Accessibility permission is required; run 'ble-stt-doctor --request-permissions' first"
            )

    def check_input_permission(self, prompt: bool = False) -> tuple[bool, str]:
        try:
            trusted = self.create_text_injector().check_accessibility(prompt)
        except ImportError as exc:
            return False, f"PyObjC is unavailable: {exc}"
        if trusted:
            return True, "macOS Accessibility permission is granted"
        return False, "allow this Python executable in System Settings > Privacy & Security > Accessibility"

    async def _retrieve_system_device(self, identifier: str | None):
        from bleak.backends.corebluetooth.CentralManagerDelegate import CentralManagerDelegate
        from bleak.backends.device import BLEDevice
        from CoreBluetooth import CBUUID
        from Foundation import NSArray, NSUUID

        manager = CentralManagerDelegate()
        await manager.wait_until_ready()
        if identifier:
            uuid = NSUUID.alloc().initWithUUIDString_(identifier)
            if uuid is None:
                return None
            identifiers = NSArray.arrayWithArray_([uuid])
            peripherals = manager.central_manager.retrievePeripheralsWithIdentifiers_(identifiers)
        else:
            services = NSArray.arrayWithArray_([CBUUID.UUIDWithString_(SERVICE_UUID)])
            peripherals = manager.central_manager.retrieveConnectedPeripheralsWithServices_(services)
        for peripheral in peripherals:
            if identifier is None and str(peripheral.name()) != DEVICE_NAME:
                continue
            device_id = str(peripheral.identifier().UUIDString())
            self.config.set("device_id", device_id)
            return BLEDevice(device_id, str(peripheral.name()), (peripheral, manager))
        return None

    async def find_device(self, explicit_identifier: str | None):
        from bleak import BleakScanner

        identifier = explicit_identifier or await self.paired_identifier()
        try:
            device = await self._retrieve_system_device(identifier)
        except Exception as exc:
            print(f"[ble] CoreBluetooth cache lookup failed: {exc}")
            device = None
        if device is not None:
            print(f"[ble] using CoreBluetooth cached device {device.address}")
            return device
        if identifier:
            device = await BleakScanner.find_device_by_address(identifier, timeout=3)
            if device is not None:
                return device
        print(f"[ble] scanning for {DEVICE_NAME}")
        device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
        if device is None:
            raise RuntimeError(
                f"{DEVICE_NAME} was not found; reopen BLE Remote or forget the stale pairing and try again"
            )
        self.config.set("device_id", str(device.address))
        return device
