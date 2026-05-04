"""
ble_probe.py — Brute force BLE protocol discovery for Geoid CC600 / Magene C506

Connects to the device, enables notifications on all characteristics,
then sends probe bytes and logs every response.

Usage:
    python3 ble_probe.py --scan          # find the device address
    python3 ble_probe.py --probe         # connect and probe
    python3 ble_probe.py --probe --address AA:BB:CC:DD:EE:FF  # target specific address
    python3 ble_probe.py --listen        # just connect and listen, send nothing
"""

import asyncio
import argparse
import time
import logging
from typing import Optional, List
from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CC600 / Magene C506 characteristics
# ──────────────────────────────────────────────

SERVICE_UUID  = "8ce5cc01-0a4d-11e9-ab14-d663bd873d93"
CHAR_WRITE    = "8ce5cc04-0a4d-11e9-ab14-d663bd873d93"  # no notify — write only
CHAR_NOTIFY_1 = "8ce5cc05-0a4d-11e9-ab14-d663bd873d93"  # notify
CHAR_NOTIFY_2 = "8ce5cc06-0a4d-11e9-ab14-d663bd873d93"  # notify

DEVICE_NAME_HINTS = ["CC600", "CC700", "C506", "C606", "Magene", "Geoid", "UL"]

# ──────────────────────────────────────────────
# Probe sequences to try
# ──────────────────────────────────────────────

# Common patterns used by cheap Chinese BLE devices:
# - Single command byte
# - [length, command] header
# - [0xAA, 0x55, command] magic header (very common in Chinese IoT)
# - [0xFF, command] prefix
# - JSON strings
# - Plain ASCII commands

PROBE_SEQUENCES = [
    # --- Single bytes ---
    (b"\x01",               "single 0x01"),
    (b"\x02",               "single 0x02"),
    (b"\x03",               "single 0x03"),
    (b"\x04",               "single 0x04"),
    (b"\x05",               "single 0x05"),
    (b"\x10",               "single 0x10"),
    (b"\x11",               "single 0x11"),
    (b"\x20",               "single 0x20"),
    (b"\x21",               "single 0x21"),
    (b"\xAA",               "single 0xAA"),
    (b"\xFF",               "single 0xFF"),

    # --- Common Chinese IoT magic header: AA 55 ---
    (b"\xAA\x55\x01",       "AA55 + 0x01"),
    (b"\xAA\x55\x02",       "AA55 + 0x02"),
    (b"\xAA\x55\x03",       "AA55 + 0x03"),
    (b"\xAA\x55\x04",       "AA55 + 0x04"),
    (b"\xAA\x55\x05",       "AA55 + 0x05"),
    (b"\xAA\x55\x10",       "AA55 + 0x10"),
    (b"\xAA\x55\x11",       "AA55 + 0x11"),
    (b"\xAA\x55\x20",       "AA55 + 0x20"),
    (b"\xAA\x55\xA0",       "AA55 + 0xA0"),
    (b"\xAA\x55\xB0",       "AA55 + 0xB0"),

    # --- Reversed magic: 55 AA ---
    (b"\x55\xAA\x01",       "55AA + 0x01"),
    (b"\x55\xAA\x02",       "55AA + 0x02"),
    (b"\x55\xAA\x10",       "55AA + 0x10"),

    # --- Length-prefixed: [len, cmd] ---
    (b"\x02\x01",           "len=2 cmd=0x01"),
    (b"\x02\x02",           "len=2 cmd=0x02"),
    (b"\x02\x03",           "len=2 cmd=0x03"),
    (b"\x02\x10",           "len=2 cmd=0x10"),
    (b"\x03\x01\x00",       "len=3 cmd=0x01 0x00"),
    (b"\x03\x02\x00",       "len=3 cmd=0x02 0x00"),

    # --- FF prefix ---
    (b"\xFF\x01",           "FF + 0x01"),
    (b"\xFF\x02",           "FF + 0x02"),
    (b"\xFF\x10",           "FF + 0x10"),

    # --- File listing candidates ---
    (b"\xAA\x55\x06",       "AA55 + list files?"),
    (b"\xAA\x55\x07",       "AA55 + list files?"),
    (b"\xAA\x55\x08",       "AA55 + list files?"),
    (b"\xAA\x55\x09",       "AA55 + list files?"),
    (b"\xAA\x55\x0A",       "AA55 + list files?"),
    (b"\xAA\x55\x0B",       "AA55 + list files?"),
    (b"\xAA\x55\x0C",       "AA55 + list files?"),
    (b"\xAA\x55\x0D",       "AA55 + list files?"),
    (b"\xAA\x55\x0E",       "AA55 + list files?"),
    (b"\xAA\x55\x0F",       "AA55 + list files?"),

    # --- JSON probes (some devices use JSON over BLE) ---
    (b'{"cmd":1}',          "JSON cmd=1"),
    (b'{"cmd":2}',          "JSON cmd=2"),
    (b'{"type":"sync"}',    "JSON type=sync"),
    (b'{"action":"list"}',  "JSON action=list"),

    # --- Plain ASCII ---
    (b"SYNC\r\n",           "ASCII SYNC"),
    (b"LIST\r\n",           "ASCII LIST"),
    (b"GET\r\n",            "ASCII GET"),
    (b"AT\r\n",             "AT command"),
    (b"AT+LIST\r\n",        "AT+LIST"),
]


# ──────────────────────────────────────────────
# Response logger
# ──────────────────────────────────────────────

class ResponseLogger:
    def __init__(self):
        self.responses: List[dict] = []
        self.last_probe: Optional[str] = None
        self.event = asyncio.Event()

    def on_notify(self, char_uuid: str, data: bytes):
        entry = {
            "time": time.time(),
            "char": char_uuid[-8:],  # last 8 chars of UUID for readability
            "probe": self.last_probe,
            "hex": data.hex(),
            "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in data),
            "bytes": list(data),
            "len": len(data)
        }
        self.responses.append(entry)
        self.event.set()

        print(f"\n{'='*60}")
        print(f"  RESPONSE on {entry['char']}")
        print(f"  Probe   : {self.last_probe}")
        print(f"  Hex     : {entry['hex']}")
        print(f"  ASCII   : {entry['ascii']}")
        print(f"  Bytes   : {entry['bytes']}")
        print(f"{'='*60}")

    def has_new_response(self) -> bool:
        return self.event.is_set()

    def clear(self):
        self.event.clear()


# ──────────────────────────────────────────────
# Scanner
# ──────────────────────────────────────────────

async def find_device(target_address: Optional[str] = None) -> Optional[BLEDevice]:
    """Find the CC600 / Magene device."""
    print("Scanning (10s)...")

    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)

    for device, adv in devices.values():
        name = device.name or ""
        uuids = [u.lower() for u in (adv.service_uuids or [])]

        if target_address and device.address.upper() == target_address.upper():
            print(f"Found target: {name} ({device.address})")
            return device

        if SERVICE_UUID in uuids:
            print(f"Found Magene/Geoid device: {name} ({device.address})")
            return device

        if any(hint.lower() in name.lower() for hint in DEVICE_NAME_HINTS):
            print(f"Found by name: {name} ({device.address})")
            return device

    return None


# ──────────────────────────────────────────────
# Listener — just connect and log everything
# ──────────────────────────────────────────────

async def listen(address: Optional[str] = None):
    """Connect and log all notifications without sending anything."""
    device = await find_device(address)
    if not device:
        print("Device not found.")
        return

    logger = ResponseLogger()

    def make_handler(uuid):
        def handler(_, data):
            logger.on_notify(uuid, bytes(data))
        return handler

    print(f"\nConnecting to {device.name}...")
    async with BleakClient(device) as client:
        print(f"Connected. Listening for notifications (60s)...")
        print("Open OneLapFit and sync your device now.\n")

        await client.start_notify(CHAR_NOTIFY_1, make_handler(CHAR_NOTIFY_1))
        await client.start_notify(CHAR_NOTIFY_2, make_handler(CHAR_NOTIFY_2))

        await asyncio.sleep(60)

    print(f"\nCaptured {len(logger.responses)} notification(s).")
    save_responses(logger.responses, "listen_log.txt")


# ──────────────────────────────────────────────
# Prober — send sequences and log responses
# ──────────────────────────────────────────────

async def probe(address: Optional[str] = None):
    """Connect and systematically send probe bytes, logging all responses."""
    device = await find_device(address)
    if not device:
        print("Device not found.")
        return

    logger = ResponseLogger()

    def make_handler(uuid):
        def handler(_, data):
            logger.on_notify(uuid, bytes(data))
        return handler

    print(f"\nConnecting to {device.name} ({device.address})...")

    async with BleakClient(device) as client:
        print("Connected.\n")

        # Print all services for reference
        print("Services discovered:")
        for service in client.services:
            print(f"  {service.uuid}")
            for char in service.characteristics:
                print(f"    {char.uuid}  props={char.properties}")
        print()

        # Enable notifications
        try:
            await client.start_notify(CHAR_NOTIFY_1, make_handler(CHAR_NOTIFY_1))
            print(f"Notifications enabled on {CHAR_NOTIFY_1[-8:]}")
        except Exception as e:
            print(f"Could not enable notify on char 05: {e}")

        try:
            await client.start_notify(CHAR_NOTIFY_2, make_handler(CHAR_NOTIFY_2))
            print(f"Notifications enabled on {CHAR_NOTIFY_2[-8:]}")
        except Exception as e:
            print(f"Could not enable notify on char 06: {e}")

        await asyncio.sleep(0.5)
        print(f"\nStarting probe with {len(PROBE_SEQUENCES)} sequences...\n")

        for payload, description in PROBE_SEQUENCES:
            logger.last_probe = description
            logger.clear()

            print(f"→ Sending: {description:30s}  hex={payload.hex()}", end="", flush=True)

            try:
                # Try write with response first
                await client.write_gatt_char(CHAR_WRITE, payload, response=True)
            except Exception:
                try:
                    # Fall back to write without response
                    await client.write_gatt_char(CHAR_WRITE, payload, response=False)
                except Exception as e:
                    print(f"  [write failed: {e}]")
                    continue

            # Wait up to 2 seconds for a response
            try:
                await asyncio.wait_for(logger.event.wait(), timeout=2.0)
                # Give extra time for multi-packet responses
                await asyncio.sleep(0.3)
            except asyncio.TimeoutError:
                print("  [no response]")

            # Small delay between probes
            await asyncio.sleep(0.2)

        print(f"\n{'='*60}")
        print(f"Probe complete. {len(logger.responses)} response(s) received.")
        save_responses(logger.responses, "probe_log.txt")


# ──────────────────────────────────────────────
# Save results
# ──────────────────────────────────────────────

def save_responses(responses: List[dict], filename: str):
    if not responses:
        print("No responses to save.")
        return

    with open(filename, "w") as f:
        f.write(f"{'='*60}\n")
        f.write(f"BLE Probe Results — {len(responses)} response(s)\n")
        f.write(f"{'='*60}\n\n")
        for r in responses:
            f.write(f"Probe   : {r['probe']}\n")
            f.write(f"Char    : {r['char']}\n")
            f.write(f"Hex     : {r['hex']}\n")
            f.write(f"ASCII   : {r['ascii']}\n")
            f.write(f"Bytes   : {r['bytes']}\n")
            f.write(f"Length  : {r['len']}\n")
            f.write("\n")

    print(f"Results saved to {filename}")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BLE probe for Geoid CC600 / Magene C506")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scan",   action="store_true", help="Scan and list nearby devices")
    group.add_argument("--probe",  action="store_true", help="Connect and send probe sequences")
    group.add_argument("--listen", action="store_true", help="Connect and listen only (open OneLapFit while running)")

    parser.add_argument("--address", type=str, default=None, help="Target device BLE address")
    parser.add_argument("--debug",   action="store_true",    help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.scan:
        async def do_scan():
            from bleak import BleakScanner
            print("Scanning for ALL BLE devices (60s)...\n")
            devices = await BleakScanner.discover(timeout=60.0, return_adv=True)
            for device, adv in devices.values():
                name = device.name or "Unknown"
                uuids = adv.service_uuids or []
                print(f"{name:30s}  {device.address}  rssi={adv.rssi}")
                for u in uuids:
                    print(f"  uuid: {u}")
        asyncio.run(do_scan())

    elif args.listen:
        asyncio.run(listen(args.address))

    elif args.probe:
        asyncio.run(probe(args.address))


if __name__ == "__main__":
    main()