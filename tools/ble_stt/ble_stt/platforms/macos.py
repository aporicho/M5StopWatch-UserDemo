from __future__ import annotations

import asyncio
import platform
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from ..protocol import DEVICE_NAME, SERVICE_UUID
from .base import PlatformAdapter


ACCESSIBILITY_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)
BLUETOOTH_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Bluetooth"
CORE_BLUETOOTH_CACHE_TIMEOUT_SECONDS = 5.0
BLE_ADDRESS_SCAN_TIMEOUT_SECONDS = 5.0
BLE_NAME_SCAN_TIMEOUT_SECONDS = 12.0
_BLUETOOTH_PERMISSION_MANAGER: Any | None = None
HID_TO_MAC_KEY = {
    **{0x04 + index: value for index, value in enumerate((0x00, 0x0B, 0x08, 0x02, 0x0E, 0x03, 0x05, 0x04,
                                                           0x22, 0x26, 0x28, 0x25, 0x2E, 0x2D, 0x1F, 0x23,
                                                           0x0C, 0x0F, 0x01, 0x11, 0x20, 0x09, 0x0D, 0x07,
                                                           0x10, 0x06))},
    0x28: 0x24,
    0x29: 0x35,
    0x2A: 0x33,
    0x2B: 0x30,
    0x2C: 0x31,
    0x3A: 0x7A,
    0x3B: 0x78,
    0x3C: 0x63,
    0x3D: 0x76,
    0x3E: 0x60,
    0x3F: 0x61,
    0x40: 0x62,
    0x41: 0x64,
    0x42: 0x65,
    0x43: 0x6D,
    0x44: 0x67,
    0x45: 0x6F,
    0x4A: 0x73,
    0x4B: 0x74,
    0x4C: 0x75,
    0x4D: 0x77,
    0x4E: 0x79,
    0x4F: 0x7C,
    0x50: 0x7B,
    0x51: 0x7D,
    0x52: 0x7E,
}


def _accessibility_principal() -> str:
    return "M5StopWatch" if getattr(sys, "frozen", False) else sys.executable


def _accessibility_instructions() -> str:
    if getattr(sys, "frozen", False):
        return (
            "enable M5StopWatch in System Settings > Privacy & Security > Accessibility"
        )
    return (
        "in System Settings > Privacy & Security > Accessibility, click +, press Shift-Command-G, "
        f"then add and enable {sys.executable}"
    )


def _bluetooth_instructions() -> str:
    if getattr(sys, "frozen", False):
        return "enable M5StopWatch in System Settings > Privacy & Security > Bluetooth"
    return (
        "enable the current terminal/Python process in System Settings > Privacy & Security > "
        "Bluetooth, then rerun the command"
    )


def _request_bluetooth_authorization(central_manager_type: Any) -> None:
    global _BLUETOOTH_PERMISSION_MANAGER
    try:
        _BLUETOOTH_PERMISSION_MANAGER = central_manager_type.alloc().initWithDelegate_queue_options_(
            None, None, None
        )
    except Exception:
        return
    try:
        from Foundation import NSDate, NSRunLoop

        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
    except Exception:
        pass


@dataclass(frozen=True)
class MacWindowToken:
    pid: int


class MacOSTextInjector:
    def __init__(
        self,
        quartz: Any | None = None,
        appkit: Any | None = None,
    ) -> None:
        if quartz is None:
            import Quartz

            quartz = Quartz
        if appkit is None:
            import AppKit

            appkit = AppKit
        self.quartz = quartz
        self.appkit = appkit

    def check_accessibility(self, prompt: bool = False) -> bool:
        # Text insertion only needs the narrowly scoped PostEvent privilege.
        # Requesting full AX access made setup less reliable and exposed APIs
        # the product does not otherwise need.
        if prompt:
            return bool(self.quartz.CGRequestPostEventAccess())
        return bool(self.quartz.CGPreflightPostEventAccess())

    def active_window(self) -> MacWindowToken | None:
        application = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if application is None:
            return None
        pid = int(application.processIdentifier())
        return MacWindowToken(pid)

    def _same_window(self, expected: MacWindowToken, current: MacWindowToken) -> bool:
        # NSWorkspace is available without Accessibility permission. Guarding
        # by the frontmost application prevents text from leaking into a
        # different app while keeping the permission request minimal.
        return expected.pid == current.pid

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

    def _modifier_flags(self, modifiers: int) -> int:
        flags = 0
        if modifiers & 0x01:
            flags |= int(self.quartz.kCGEventFlagMaskControl)
        if modifiers & 0x02:
            flags |= int(self.quartz.kCGEventFlagMaskShift)
        if modifiers & 0x04:
            flags |= int(self.quartz.kCGEventFlagMaskAlternate)
        if modifiers & 0x08:
            flags |= int(self.quartz.kCGEventFlagMaskCommand)
        return flags

    def _post_key(self, key_code: int, modifiers: int) -> None:
        mac_key = HID_TO_MAC_KEY.get(key_code)
        if mac_key is None:
            raise RuntimeError(f"unsupported HID key code for macOS fallback: 0x{key_code:02x}")
        source = self.quartz.CGEventSourceCreate(self.quartz.kCGEventSourceStateCombinedSessionState)
        flags = self._modifier_flags(modifiers)
        key_down = self.quartz.CGEventCreateKeyboardEvent(source, mac_key, True)
        key_up = self.quartz.CGEventCreateKeyboardEvent(source, mac_key, False)
        if key_down is None or key_up is None:
            raise RuntimeError("failed to create macOS keyboard event")
        self.quartz.CGEventSetFlags(key_down, flags)
        self.quartz.CGEventSetFlags(key_up, flags)
        self.quartz.CGEventPost(self.quartz.kCGHIDEventTap, key_down)
        self.quartz.CGEventPost(self.quartz.kCGHIDEventTap, key_up)

    def type_text(self, text: str, expected_window: object | None) -> bool:
        if not text:
            return True
        if not self.check_accessibility(False):
            raise RuntimeError(
                "Accessibility permission is required; run 'ble-stt doctor --request-permissions' "
                f"and allow {_accessibility_principal()}"
            )
        current = self.active_window()
        if isinstance(expected_window, MacWindowToken):
            if current is None or not self._same_window(expected_window, current):
                print("[focus] frontmost application changed; suppressing text injection")
                return False
        self._post_unicode(text)
        return True

    def tap_key(self, key_code: int, modifiers: int, expected_window: object | None) -> bool:
        if not self.check_accessibility(False):
            raise RuntimeError(
                "Accessibility permission is required; run 'ble-stt doctor --request-permissions' "
                f"and allow {_accessibility_principal()}"
            )
        current = self.active_window()
        if isinstance(expected_window, MacWindowToken):
            if current is None or not self._same_window(expected_window, current):
                print("[focus] frontmost application changed; suppressing key action")
                return False
        self._post_key(key_code, modifiers)
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
            if not getattr(self, "_input_permission_prompted", False):
                self._input_permission_prompted = True
                injector.check_accessibility(True)
            raise RuntimeError(
                "Accessibility permission is required; enable M5StopWatch in System Settings > "
                "Privacy & Security > Accessibility"
            )

    def check_input_permission(self, prompt: bool = False) -> tuple[bool, str]:
        try:
            trusted = self.create_text_injector().check_accessibility(prompt)
        except ImportError as exc:
            return False, f"PyObjC is unavailable: {exc}"
        if trusted:
            return True, "macOS Accessibility permission is granted"
        return False, _accessibility_instructions()

    def check_bluetooth_permission(self, prompt: bool = False) -> tuple[bool, str]:
        try:
            from CoreBluetooth import (
                CBCentralManager,
                CBManagerAuthorizationAllowedAlways,
                CBManagerAuthorizationDenied,
                CBManagerAuthorizationNotDetermined,
                CBManagerAuthorizationRestricted,
            )
        except ImportError as exc:
            return False, f"PyObjC CoreBluetooth is unavailable: {exc}"

        authorization = int(CBCentralManager.authorization())
        if prompt and authorization == int(CBManagerAuthorizationNotDetermined):
            _request_bluetooth_authorization(CBCentralManager)
            authorization = int(CBCentralManager.authorization())
        if authorization == int(CBManagerAuthorizationAllowedAlways):
            return True, "macOS Bluetooth permission is granted"
        if authorization == int(CBManagerAuthorizationNotDetermined):
            return False, f"macOS Bluetooth permission has not been granted yet; {_bluetooth_instructions()}"
        if authorization == int(CBManagerAuthorizationDenied):
            return False, f"macOS Bluetooth permission is denied; {_bluetooth_instructions()}"
        if authorization == int(CBManagerAuthorizationRestricted):
            return False, "macOS Bluetooth permission is restricted by system policy"
        return False, f"macOS Bluetooth permission is unavailable (authorization={authorization})"

    def open_input_permission_settings(self) -> None:
        subprocess.run(
            ["open", ACCESSIBILITY_SETTINGS_URL],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def open_bluetooth_permission_settings(self) -> None:
        subprocess.run(
            ["open", BLUETOOTH_SETTINGS_URL],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

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
            device = await asyncio.wait_for(
                self._retrieve_system_device(identifier),
                timeout=CORE_BLUETOOTH_CACHE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            print("[ble] CoreBluetooth cache lookup timed out")
            device = None
        except Exception as exc:
            print(f"[ble] CoreBluetooth cache lookup failed: {exc}")
            device = None
        if device is not None:
            print(f"[ble] using CoreBluetooth cached device {device.address}")
            return device
        if identifier:
            try:
                device = await asyncio.wait_for(
                    BleakScanner.find_device_by_address(identifier, timeout=3),
                    timeout=BLE_ADDRESS_SCAN_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                print("[ble] cached address scan timed out")
                device = None
            if device is not None:
                return device
        print(f"[ble] scanning for {DEVICE_NAME}")
        try:
            device = await asyncio.wait_for(
                BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10),
                timeout=BLE_NAME_SCAN_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            print("[ble] device name scan timed out")
            device = None
        if device is None:
            raise RuntimeError(
                f"{DEVICE_NAME} was not found; reopen BLE Remote or forget the stale pairing and try again"
            )
        self.config.set("device_id", str(device.address))
        return device
