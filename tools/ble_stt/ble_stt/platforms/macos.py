from __future__ import annotations

import asyncio
import platform
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from ..protocol import DEVICE_NAME, SERVICE_UUID
from ..types import TextReplacementResult
from .base import PlatformAdapter


ACCESSIBILITY_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)
BLUETOOTH_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Bluetooth"
CORE_BLUETOOTH_CACHE_TIMEOUT_SECONDS = 5.0
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
    focused_element: Any | None = None


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
        # The visible permission request is driven by the narrowly scoped
        # PostEvent API. Final correction may use AX on the currently focused
        # field only, but it never prompts from the background process.
        if prompt:
            return bool(self.quartz.CGRequestPostEventAccess())
        return bool(self.quartz.CGPreflightPostEventAccess())

    def active_window(self) -> MacWindowToken | None:
        application = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if application is None:
            return None
        pid = int(application.processIdentifier())
        return MacWindowToken(pid, self._focused_element())

    def _same_window(self, expected: MacWindowToken, current: MacWindowToken) -> bool:
        # NSWorkspace is available without Accessibility permission. Guarding
        # by the frontmost application prevents text from leaking into a
        # different app while keeping the permission request minimal.
        return expected.pid == current.pid

    def _same_element(self, expected: Any, current: Any) -> bool:
        compare = getattr(self.quartz, "CFEqual", None)
        try:
            return bool(compare(expected, current)) if callable(compare) else bool(expected == current)
        except Exception:
            return False

    def _ax_copy(self, element: Any, attribute: Any) -> tuple[int, Any | None]:
        function = getattr(self.quartz, "AXUIElementCopyAttributeValue", None)
        if not callable(function):
            return -1, None
        try:
            result = function(element, attribute, None)
        except Exception:
            return -1, None
        if isinstance(result, tuple) and len(result) == 2:
            return int(result[0]), result[1]
        return 0, result

    def _focused_element(self) -> Any | None:
        creator = getattr(self.quartz, "AXUIElementCreateSystemWide", None)
        attribute = getattr(self.quartz, "kAXFocusedUIElementAttribute", None)
        if not callable(creator) or attribute is None:
            return None
        error, value = self._ax_copy(creator(), attribute)
        return value if error == 0 else None

    def _selected_range(self, value: Any) -> tuple[int, int] | None:
        getter = getattr(self.quartz, "AXValueGetValue", None)
        range_type = getattr(self.quartz, "kAXValueCFRangeType", None)
        if not callable(getter) or range_type is None:
            return None
        try:
            result = getter(value, range_type, None)
        except Exception:
            return None
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
            if not result[0]:
                return None
            result = result[1]
        if isinstance(result, tuple) and len(result) == 2:
            return int(result[0]), int(result[1])
        location = getattr(result, "location", None)
        length = getattr(result, "length", None)
        if location is None or length is None:
            return None
        return int(location), int(length)

    def _range_value(self, location: int, length: int) -> Any | None:
        creator = getattr(self.quartz, "AXValueCreate", None)
        range_type = getattr(self.quartz, "kAXValueCFRangeType", None)
        if not callable(creator) or range_type is None:
            return None
        raw_range: Any = (location, length)
        make_range = getattr(self.quartz, "CFRangeMake", None)
        if callable(make_range):
            raw_range = make_range(location, length)
        try:
            return creator(range_type, raw_range)
        except Exception:
            return None

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

    def replace_verified_suffix(
        self,
        expected_suffix: str,
        replacement: str,
        expected_window: object | None,
    ) -> TextReplacementResult:
        if not expected_suffix:
            return TextReplacementResult(False, "empty_suffix")
        current = self.active_window()
        if isinstance(expected_window, MacWindowToken):
            if current is None or not self._same_window(expected_window, current):
                return TextReplacementResult(False, "focus_changed")
            if (
                expected_window.focused_element is not None
                and current.focused_element is not None
                and not self._same_element(expected_window.focused_element, current.focused_element)
            ):
                return TextReplacementResult(False, "focus_changed")
            element = current.focused_element
        else:
            element = self._focused_element()
        if element is None:
            return TextReplacementResult(False, "unsupported")

        value_attribute = getattr(self.quartz, "kAXValueAttribute", None)
        selection_attribute = getattr(self.quartz, "kAXSelectedTextRangeAttribute", None)
        setter = getattr(self.quartz, "AXUIElementSetAttributeValue", None)
        if value_attribute is None or selection_attribute is None or not callable(setter):
            return TextReplacementResult(False, "unsupported")
        value_error, value = self._ax_copy(element, value_attribute)
        range_error, range_value = self._ax_copy(element, selection_attribute)
        selected = self._selected_range(range_value) if range_error == 0 else None
        if value_error != 0 or not isinstance(value, str) or selected is None:
            return TextReplacementResult(False, "unsupported")
        location, length = selected
        if length != 0:
            return TextReplacementResult(False, "selection_changed")

        encoded = value.encode("utf-16-le")
        suffix = expected_suffix.encode("utf-16-le")
        caret = location * 2
        if caret < len(suffix) or encoded[caret - len(suffix) : caret] != suffix:
            return TextReplacementResult(False, "text_mismatch")
        replacement_range = self._range_value(location - len(suffix) // 2, len(suffix) // 2)
        if replacement_range is None:
            return TextReplacementResult(False, "unsupported")
        try:
            error = int(setter(element, selection_attribute, replacement_range))
        except Exception:
            return TextReplacementResult(False, "selection_failed")
        if error != 0:
            return TextReplacementResult(False, "selection_failed")
        try:
            self._post_unicode(replacement)
        except Exception:
            original_range = self._range_value(location, 0)
            if original_range is not None:
                try:
                    setter(element, selection_attribute, original_range)
                except Exception:
                    pass
            return TextReplacementResult(False, "insertion_failed")
        return TextReplacementResult(True, "replaced")


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
        from Foundation import NSArray

        manager = CentralManagerDelegate()
        await manager.wait_until_ready()
        # A HID link owned by macOS is not returned when CoreBluetooth is
        # queried for 0x1812.  The same already-connected peripheral *is*
        # returned for our vendor speech service, which lets the helper attach
        # GATT without scanning or waking a disconnected watch.
        # retrievePeripheralsWithIdentifiers_ only means "known to the cache"
        # and would let Bleak initiate a physical reconnect, so it is never used.
        services = NSArray.arrayWithArray_([CBUUID.UUIDWithString_(SERVICE_UUID)])
        peripherals = manager.central_manager.retrieveConnectedPeripheralsWithServices_(services)
        named_match = None
        for peripheral in peripherals:
            device_id = str(peripheral.identifier().UUIDString())
            if str(peripheral.name()) != DEVICE_NAME:
                continue
            device = BLEDevice(device_id, str(peripheral.name()), (peripheral, manager))
            if identifier and device_id.casefold() == identifier.casefold():
                self.config.set("device_id", device_id)
                return device
            named_match = named_match or device
        if named_match is not None:
            # Pair New rotates the watch identity, so a stale CoreBluetooth UUID
            # must never hide a newly system-connected M5StopWatch HID.
            self.config.set("device_id", str(named_match.address))
        return named_match

    async def find_connected_device(self, explicit_identifier: str | None):
        identifier = explicit_identifier or await self.paired_identifier()
        try:
            return await asyncio.wait_for(
                self._retrieve_system_device(identifier), timeout=CORE_BLUETOOTH_CACHE_TIMEOUT_SECONDS
            )
        except TimeoutError:
            print("[ble] CoreBluetooth connected-device lookup timed out")
            return None
        except Exception as exc:
            print(f"[ble] CoreBluetooth connected-device lookup failed: {exc}")
            return None
