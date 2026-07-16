from __future__ import annotations

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
                "Accessibility permission is required; run 'ble-stt doctor --request-permissions' first"
            )

    def check_input_permission(self, prompt: bool = False) -> tuple[bool, str]:
        try:
            trusted = self.create_text_injector().check_accessibility(prompt)
        except ImportError as exc:
            return False, f"PyObjC is unavailable: {exc}"
        if trusted:
            return True, "macOS Accessibility permission is granted"
        return False, _accessibility_instructions()

    def open_input_permission_settings(self) -> None:
        subprocess.run(
            ["open", ACCESSIBILITY_SETTINGS_URL],
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
