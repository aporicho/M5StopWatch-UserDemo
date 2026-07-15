from __future__ import annotations

import argparse
import asyncio
import sys

from .platforms import PlatformAdapter, create_platform
from .protocol import AUDIO_UUID, SERVICE_UUID, STATUS_UUID, StatusPacket


async def check(identifier: str | None, adapter: PlatformAdapter | None = None) -> None:
    from bleak import BleakClient

    adapter = adapter or create_platform()
    device = await adapter.find_device(identifier)
    ready = asyncio.Event()

    def status_received(_, data: bytearray) -> None:
        status = StatusPacket.parse(bytes(data))
        print(
            f"status event={status.event.name} session={status.session_id} "
            f"format={status.sample_rate}Hz/{status.frame_samples}"
        )
        ready.set()

    client = BleakClient(device, timeout=60)
    await adapter.prepare_client(client, device)
    async with client:
        uuids = {str(service.uuid).lower() for service in client.services}
        for uuid in sorted(uuids):
            print(uuid)
        if SERVICE_UUID not in uuids:
            raise RuntimeError("Speech GATT service was not discovered; forget the device and pair it again")
        await client.read_gatt_char(STATUS_UUID)
        mtu = await adapter.acquire_mtu(client)
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
        pass
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
