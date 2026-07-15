from __future__ import annotations

import argparse
import asyncio
import sys

from .main import acquire_mtu, find_device, use_cached_bluez_device
from .protocol import AUDIO_UUID, SERVICE_UUID, STATUS_UUID, StatusPacket


async def check(address: str | None) -> None:
    from bleak import BleakClient

    device = await find_device(address)
    ready = asyncio.Event()

    def status_received(_, data: bytearray) -> None:
        status = StatusPacket.parse(bytes(data))
        print(
            f"status event={status.event.name} session={status.session_id} "
            f"format={status.sample_rate}Hz/{status.frame_samples}"
        )
        ready.set()

    client = BleakClient(device, timeout=20)
    await use_cached_bluez_device(client, device)
    async with client:
        uuids = {str(service.uuid).lower() for service in client.services}
        for uuid in sorted(uuids):
            print(uuid)
        if SERVICE_UUID not in uuids:
            raise RuntimeError("Speech GATT service not discovered (BlueZ may still have the old service cache)")
        await client.read_gatt_char(STATUS_UUID)
        mtu = await acquire_mtu(client)
        print(f"connected={client.is_connected} mtu={mtu}")
        if mtu < 185:
            raise RuntimeError(f"negotiated MTU {mtu} is too small for speech audio (need 185)")
        await client.start_notify(STATUS_UUID, status_received)
        await client.start_notify(AUDIO_UUID, lambda *_: None)
        try:
            await asyncio.wait_for(ready.wait(), timeout=5)
        except TimeoutError:
            status = StatusPacket.parse(bytes(await client.read_gatt_char(STATUS_UUID)))
            print(f"status read={status.event.name}; notifications subscribed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the M5StopWatch Speech GATT service without loading STT")
    parser.add_argument("--address", help="Bluetooth address; normally detected from bluetoothctl")
    args = parser.parse_args()
    try:
        asyncio.run(check(args.address))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
