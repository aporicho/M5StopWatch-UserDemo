from __future__ import annotations

from typing import Any

from ..config import UserConfig
from ..types import TextInjector, TextReplacementResult


class PlatformAdapter:
    name = "unknown"

    def __init__(self, config: UserConfig | None = None) -> None:
        self.config = config or UserConfig()

    def create_text_injector(self) -> TextInjector:
        raise NotImplementedError

    def validate_runtime(self) -> None:
        pass

    def check_input_permission(self, prompt: bool = False) -> tuple[bool, str]:
        return True, "input permission is available"

    def check_bluetooth_permission(self, prompt: bool = False) -> tuple[bool, str]:
        return True, "Bluetooth permission is available"

    def open_bluetooth_permission_settings(self) -> None:
        pass

    async def paired_identifier(self) -> str | None:
        value = self.config.get("device_id")
        return str(value) if value else None

    async def find_connected_device(self, explicit_identifier: str | None):
        raise NotImplementedError(f"{self.name} cannot query the operating system's connected HID devices")

    async def wait_for_system_connection(self, explicit_identifier: str | None):
        import asyncio

        announced = False
        while True:
            device = await self.find_connected_device(explicit_identifier)
            if device is not None:
                return device
            if not announced:
                print("[ble] waiting for M5StopWatch HID to be connected by the operating system")
                announced = True
            await asyncio.sleep(2)

    async def find_device(self, explicit_identifier: str | None):
        """Compatibility alias used by diagnostics; never scans or initiates a link."""
        return await self.wait_for_system_connection(explicit_identifier)

    async def prepare_client(self, client: Any, device: Any) -> None:
        pass

    async def acquire_mtu(self, client: Any) -> int:
        return int(client.mtu_size)

    async def record_connected(self, device: Any) -> None:
        pass


def unsupported_text_replacement() -> TextReplacementResult:
    return TextReplacementResult(False, "unsupported")
