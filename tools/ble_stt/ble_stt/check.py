from __future__ import annotations

import argparse
import asyncio
import sys

from .platforms import PlatformAdapter, create_platform
from .protocol import AUDIO_UUID, SERVICE_UUID, STATUS_UUID, StatusPacket

HID_SERVICE_UUID = "00001812-0000-1000-8000-00805f9b34fb"
MINIMUM_SPEECH_MTU = 185


def missing_required_services(uuids: set[str]) -> list[str]:
    missing: list[str] = []
    if SERVICE_UUID not in uuids:
        missing.append("Speech GATT service")
    return missing


def missing_optional_services(uuids: set[str]) -> list[str]:
    missing: list[str] = []
    if HID_SERVICE_UUID not in uuids:
        missing.append("HID service 0x1812")
    return missing


def error_detail(exc: BaseException) -> str:
    return str(exc) or exc.__class__.__name__


async def check(identifier: str | None, adapter: PlatformAdapter | None = None) -> None:
    from bleak import BleakClient

    adapter = adapter or create_platform()
    print("[ble] scan: locating M5StopWatch HID")
    device = await adapter.find_device(identifier)
    device_name = getattr(device, "name", None) or "M5StopWatch HID"
    device_address = getattr(device, "address", None) or str(device)
    print(f"[ok] scan: {device_name} ({device_address})")
    ready = asyncio.Event()

    def status_received(_, data: bytearray) -> None:
        status = StatusPacket.parse(bytes(data))
        print(
            f"[ok] status notification: event={status.event.name} session={status.session_id} "
            f"format={status.sample_rate}Hz/{status.frame_samples}"
        )
        ready.set()

    print("[ble] connect: opening encrypted GATT connection")
    client = BleakClient(device, timeout=60)
    await adapter.prepare_client(client, device)
    async with client:
        print(f"[ok] connect: connected={client.is_connected}")
        uuids = {str(service.uuid).lower() for service in client.services}
        print("[ble] service discovery:")
        for uuid in sorted(uuids):
            print(f"  {uuid}")
        missing = missing_required_services(uuids)
        if missing:
            raise RuntimeError(
                f"{', '.join(missing)} was not discovered; forget the device and pair it again"
            )
        optional_missing = missing_optional_services(uuids)
        if optional_missing:
            print(
                "[warn] "
                + ", ".join(optional_missing)
                + " was not exposed through CoreBluetooth; continuing because the Speech GATT service is available"
            )
        else:
            print("[ok] HID service 0x1812 discovered")
        print("[ok] Speech GATT service discovered")

        status = StatusPacket.parse(bytes(await client.read_gatt_char(STATUS_UUID)))
        print(
            f"[ok] status read: event={status.event.name} session={status.session_id} "
            f"format={status.sample_rate}Hz/{status.frame_samples}"
        )
        mtu = await adapter.acquire_mtu(client)
        print(f"[ok] MTU negotiated: {mtu}")
        if mtu < MINIMUM_SPEECH_MTU:
            raise RuntimeError(f"negotiated MTU {mtu} is too small for speech audio (need {MINIMUM_SPEECH_MTU})")
        await client.start_notify(STATUS_UUID, status_received)
        await client.start_notify(AUDIO_UUID, lambda *_: None)
        print("[ok] notifications subscribed: status,audio")
        try:
            await asyncio.wait_for(ready.wait(), timeout=5)
        except TimeoutError:
            status = StatusPacket.parse(bytes(await client.read_gatt_char(STATUS_UUID)))
            print(f"[ok] no immediate status notification; latest status={status.event.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the M5StopWatch Speech GATT service without loading STT")
    parser.add_argument(
        "--device-id",
        "--address",
        dest="device_id",
        help="platform device identifier; normally detected and cached automatically",
    )
    args = parser.parse_args()
    try:
        asyncio.run(check(args.device_id))
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"error: {error_detail(exc)}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
