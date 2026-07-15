from __future__ import annotations

from typing import Any

from ..config import UserConfig
from ..protocol import DEVICE_NAME
from ..types import TextInjector


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

    async def paired_identifier(self) -> str | None:
        value = self.config.get("device_id")
        return str(value) if value else None

    async def find_device(self, explicit_identifier: str | None):
        from bleak import BleakScanner

        identifier = explicit_identifier or await self.paired_identifier()
        if identifier:
            print(f"[ble] using cached device {identifier}")
            device = await BleakScanner.find_device_by_address(identifier, timeout=3)
            return device or identifier

        print(f"[ble] scanning for {DEVICE_NAME}")
        device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
        if device is None:
            raise RuntimeError(f"{DEVICE_NAME} was not found; open BLE Remote and pair it first")
        self.config.set("device_id", str(device.address))
        return device

    async def prepare_client(self, client: Any, device: Any) -> None:
        pass

    async def acquire_mtu(self, client: Any) -> int:
        return int(client.mtu_size)
