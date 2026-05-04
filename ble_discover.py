"""
ble_discover.py — dump ALL nearby BLE devices with their service UUIDs.

Used to identify what protocol your cycling computer advertises.

Usage:
    python3 ble_discover.py
"""

import asyncio
from bleak import BleakScanner


async def scan_all():
    print("Scanning for ALL BLE devices (15s)...\n")
    devices = await BleakScanner.discover(timeout=15.0, return_adv=True)

    if not devices:
        print("No BLE devices found at all.")
        print("Make sure your cycling computer is powered on and nearby.")
        return

    print(f"Found {len(devices)} device(s):\n")
    for device, adv in devices.values():
        name = device.name or "Unknown"
        uuids = adv.service_uuids or []
        rssi = adv.rssi
        print(f"Device : {name}")
        print(f"  Address : {device.address}")
        print(f"  RSSI    : {rssi} dBm  ({'strong' if rssi > -60 else 'weak' if rssi < -80 else 'ok'})")
        if uuids:
            for uuid in uuids:
                print(f"  UUID    : {uuid}")
        else:
            print(f"  UUID    : (none advertised — may need to connect to discover services)")
        print()


if __name__ == "__main__":
    asyncio.run(scan_all())
