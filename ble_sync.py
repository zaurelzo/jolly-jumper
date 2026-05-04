"""
ble_sync.py — Bluetooth FIT file downloader for cycling computers

Scans for BLE cycling computers, connects, downloads FIT activity files,
and uploads them to Strava — all without plugging in the device.

Implements the Garmin Multi-Link (ML) and GFDI protocol from documentation.

Usage:
    python ble_sync.py --scan          # scan and list nearby devices
    python ble_sync.py --sync          # scan, connect, download and upload
    python ble_sync.py --sync --device "Geoid CC600"   # target specific device
    python ble_sync.py --sync --no-upload              # download only, save FIT files locally

Requirements:
    pip install bleak
"""

import asyncio
import argparse
import logging
import struct
import time
import os
from dataclasses import dataclass
from typing import Optional, List

from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice

# ──────────────────────────────────────────────
# Protocol constants
# ──────────────────────────────────────────────

# Garmin Multi-Link BLE service UUIDs
SERVICE_ML      = "6a4e2800-667b-11e3-949a-0800200c9a66"
SERVICE_LEGACY  = "6a4e8022-667b-11e3-949a-0800200c9a66"

# Write characteristics (phone → device)
CHAR_WRITE = "6a4e2820-667b-11e3-949a-0800200c9a66"

# Read/notify characteristics (device → phone)
CHAR_READ  = "6a4e2810-667b-11e3-949a-0800200c9a66"

# Legacy characteristics
CHAR_LEGACY_WRITE = "6a4e4c80-667b-11e3-949a-0800200c9a66"
CHAR_LEGACY_READ  = "6a4ecd28-667b-11e3-949a-0800200c9a66"

# ML service IDs
SERVICE_GFDI         = 1
SERVICE_REGISTRATION = 4

# ML message types
ML_REGISTER_REQUEST  = 0x00
ML_REGISTER_RESPONSE = 0x01
ML_CLOSE_ALL         = 0x05

# ML register status
ML_STATUS_SUCCESS = 0x00

# GFDI message types
GFDI_RESPONSE          = 5000
GFDI_DIRECTORY_FILTER  = 5007
GFDI_SET_FILE_FLAGS    = 5008
GFDI_FIND_REQUEST      = 5009
GFDI_FIND_RESPONSE     = 5010
GFDI_DOWNLOAD_REQUEST  = 5011
GFDI_DOWNLOAD_RESPONSE = 5012

# GFDI status
GFDI_ACK = 0x00

# Directory filters
FILTER_PENDING_UPLOAD = 0x03

# File flags
FLAG_ARCHIVE = 0x10

# FIT activity data type
FIT_ACTIVITY_TYPE = 4

# Client UUID (identifies this app to the device)
CLIENT_UUID = bytes([0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

# Max BLE packet size
BLE_MTU = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# COBS encoding / decoding
# ──────────────────────────────────────────────

def cobs_encode(data: bytes) -> bytes:
    """
    Encode bytes using COBS (Consistent Overhead Byte Stuffing).
    Replaces zero bytes with offsets, ensuring no zero bytes in output.
    """
    output = bytearray()
    code_index = 0
    code = 1
    output.append(0)  # placeholder

    for byte in data:
        if byte == 0:
            output[code_index] = code
            code_index = len(output)
            output.append(0)
            code = 1
        else:
            output.append(byte)
            code += 1
            if code == 0xFF:
                output[code_index] = code
                code_index = len(output)
                output.append(0)
                code = 1

    output[code_index] = code
    return bytes(output)


def cobs_decode(data: bytes) -> bytes:
    """Decode COBS-encoded bytes back to original data."""
    output = bytearray()
    index = 0

    while index < len(data):
        code = data[index] & 0xFF
        index += 1

        for _ in range(1, code):
            if index >= len(data):
                break
            output.append(data[index])
            index += 1

        if code != 0xFF and index < len(data):
            output.append(0)

    return bytes(output)


# ──────────────────────────────────────────────
# CRC-16
# ──────────────────────────────────────────────

_CRC16_TABLE = []
for _i in range(256):
    _crc = _i
    for _ in range(8):
        _crc = (_crc >> 1) ^ 0xA001 if (_crc & 1) else _crc >> 1
    _CRC16_TABLE.append(_crc)


def crc16(data: bytes, offset: int = 0, length: int = -1) -> bytes:
    """Compute CRC-16 and return as 2-byte little-endian."""
    if length < 0:
        length = len(data) - offset
    crc = 0
    for i in range(offset, offset + length):
        crc = (crc >> 8) ^ _CRC16_TABLE[(crc ^ data[i]) & 0xFF]
    return struct.pack("<H", crc)


def crc16_verify(data: bytes) -> bool:
    """Verify CRC-16 — last 2 bytes must be the CRC."""
    if len(data) < 3:
        return False
    computed = crc16(data, 0, len(data) - 2)
    return computed == data[-2:]


# ──────────────────────────────────────────────
# ML packet builder
# ──────────────────────────────────────────────

def ml_register_request(service_id: int, reliable: bool = False) -> bytes:
    """Build an ML service registration request packet."""
    reliable_byte = 0x02 if reliable else 0x00
    return bytes([0x00, ML_REGISTER_REQUEST]) + CLIENT_UUID + \
           struct.pack("<H", service_id) + bytes([reliable_byte])


def ml_close_all() -> bytes:
    """Build a close-all-handles request."""
    return bytes([0x00, ML_CLOSE_ALL]) + CLIENT_UUID + bytes([0x00, 0x00])


def ml_chunk_message(handle: int, data: bytes) -> List[bytes]:
    """Split a message into BLE-sized chunks, each prefixed with handle byte."""
    chunks = []
    max_data = BLE_MTU - 1
    offset = 0
    while offset < len(data):
        chunk = bytes([handle]) + data[offset:offset + max_data]
        chunks.append(chunk)
        offset += max_data
    return chunks


def ml_parse_register_response(data: bytes) -> Optional[dict]:
    """Parse an ML register response. Returns dict with handle and status."""
    if len(data) < 13:
        return None
    if data[0] != 0x00 or data[1] != ML_REGISTER_RESPONSE:
        return None
    service = struct.unpack_from("<H", data, 10)[0]
    status = data[12]
    handle = data[13] if status == ML_STATUS_SUCCESS and len(data) > 13 else None
    reliable = data[14] != 0 if len(data) > 14 else False
    return {"service": service, "status": status, "handle": handle, "reliable": reliable}


# ──────────────────────────────────────────────
# GFDI message builder
# ──────────────────────────────────────────────

class GfdiBuilder:
    def __init__(self):
        self._seq = 0

    def _build(self, type_id: int, payload: bytes) -> bytes:
        seq = self._seq & 0x1F
        self._seq += 1
        total = 2 + 2 + len(payload) + 2  # length + type + payload + crc
        msg = bytearray(total)
        struct.pack_into("<H", msg, 0, total)           # length
        msg[2] = type_id & 0xFF                         # type low byte
        msg[3] = 0x80 | seq                             # type high byte with seq
        msg[4:4 + len(payload)] = payload               # payload
        crc = crc16(bytes(msg), 0, total - 2)
        msg[-2:] = crc
        return cobs_encode(bytes(msg))

    def directory_filter(self, filter_val: int = FILTER_PENDING_UPLOAD) -> bytes:
        return self._build(GFDI_DIRECTORY_FILTER - 5000, bytes([filter_val]))

    def find_request(self, data_type: int = FIT_ACTIVITY_TYPE) -> bytes:
        return self._build(GFDI_FIND_REQUEST - 5000, bytes([data_type, 0x00]))

    def download_request(self, file_index: int, offset: int = 0) -> bytes:
        payload = struct.pack("<HI", file_index, offset)
        return self._build(GFDI_DOWNLOAD_REQUEST - 5000, payload)

    def set_file_flags(self, file_index: int, flags: int) -> bytes:
        payload = struct.pack("<HB", file_index, flags)
        return self._build(GFDI_SET_FILE_FLAGS - 5000, payload)


# ──────────────────────────────────────────────
# GFDI response parser
# ──────────────────────────────────────────────

@dataclass
class GfdiResponse:
    original_type: int
    status: int
    seq: int
    payload: bytes


@dataclass
class FitFileEntry:
    file_index: int
    data_type: int
    sub_type: int
    file_number: int
    flags: int
    file_size: int


def gfdi_decode_response(raw: bytes) -> Optional[GfdiResponse]:
    """COBS-decode and parse a GFDI response message."""
    if not raw:
        return None
    try:
        decoded = cobs_decode(raw)
    except Exception:
        return None

    if len(decoded) < 9:
        return None
    if not crc16_verify(decoded):
        log.debug("CRC mismatch on GFDI response")
        return None

    b2, b3 = decoded[2] & 0xFF, decoded[3] & 0xFF
    if b3 & 0x80:
        resp_type = 5000 + b2
        seq = b3 & 0x1F
    else:
        resp_type = b2 | (b3 << 8)
        seq = 0

    if resp_type != GFDI_RESPONSE:
        return None

    original_type = struct.unpack_from("<H", decoded, 4)[0]
    status = decoded[6]
    payload = decoded[7:-2]

    return GfdiResponse(original_type, status, seq, payload)


def parse_find_response(response: GfdiResponse) -> List[FitFileEntry]:
    """Parse the payload of a Find Response into a list of FIT file entries."""
    if response.status != GFDI_ACK:
        return []
    entries = []
    payload = response.payload
    offset = 0
    while offset + 16 <= len(payload):
        file_index, data_type, sub_type, file_number, flags = struct.unpack_from("<HBBHB", payload, offset)
        file_size = struct.unpack_from("<I", payload, offset + 8)[0]
        entries.append(FitFileEntry(file_index, data_type, sub_type, file_number, flags, file_size))
        offset += 16
    return entries


def parse_download_response(response: GfdiResponse) -> Optional[dict]:
    """Parse a Download Response payload. Returns chunk data and progress info."""
    if response.status != GFDI_ACK:
        return None
    payload = response.payload
    if len(payload) < 10:
        return None
    file_index = struct.unpack_from("<H", payload, 0)[0]
    offset     = struct.unpack_from("<I", payload, 2)[0]
    total_size = struct.unpack_from("<I", payload, 6)[0]
    data = payload[10:]
    return {
        "file_index": file_index,
        "offset": offset,
        "total_size": total_size,
        "data": data,
        "complete": (offset + len(data)) >= total_size
    }


# ──────────────────────────────────────────────
# BLE session
# ──────────────────────────────────────────────

class GarminBleSession:
    """
    Manages a BLE session with a Garmin-protocol cycling computer.

    Handles:
    - Service characteristic discovery
    - ML service registration
    - GFDI message send/receive with response correlation
    - FIT file listing and download
    """

    def __init__(self, client: BleakClient):
        self.client = client
        self.write_char: Optional[str] = None
        self.read_char: Optional[str] = None
        self.gfdi_handle: int = 0x01
        self.builder = GfdiBuilder()

        # Incoming data assembly
        self._rx_buffer = bytearray()
        self._response_event = asyncio.Event()
        self._last_response: Optional[GfdiResponse] = None

        # Registration response
        self._reg_event = asyncio.Event()
        self._last_reg: Optional[dict] = None

    # ──────────────────────────────────────────
    # Setup
    # ──────────────────────────────────────────

    async def setup(self) -> bool:
        """Discover characteristics and enable notifications."""
        services = self.client.services

        # Try ML service first
        for service in services:
            uuid = service.uuid.lower()
            if uuid == SERVICE_ML:
                for char in service.characteristics:
                    c = char.uuid.lower()
                    if c == CHAR_WRITE:
                        self.write_char = char.uuid
                    elif c == CHAR_READ:
                        self.read_char = char.uuid
                if self.write_char and self.read_char:
                    log.info("Using Garmin Multi-Link service")
                    break

        # Fall back to legacy
        if not self.write_char:
            for service in services:
                if service.uuid.lower() == SERVICE_LEGACY:
                    for char in service.characteristics:
                        c = char.uuid.lower()
                        if c == CHAR_LEGACY_WRITE:
                            self.write_char = char.uuid
                        elif c == CHAR_LEGACY_READ:
                            self.read_char = char.uuid

        if not self.write_char or not self.read_char:
            log.error("Required BLE characteristics not found")
            log.info("Available services:")
            for service in services:
                log.info(f"  Service: {service.uuid}")
                for char in service.characteristics:
                    log.info(f"    Char: {char.uuid} props={char.properties}")
            return False

        # Enable notifications
        await self.client.start_notify(self.read_char, self._on_notify)
        log.info("BLE notifications enabled")
        return True

    def _on_notify(self, sender, data: bytearray):
        """Handle incoming BLE notification."""
        data = bytes(data)
        log.debug(f"RX: {data.hex()}")

        # Check for ML management message (handle = 0x00)
        if data and data[0] == 0x00:
            reg = ml_parse_register_response(data)
            if reg:
                log.info(f"ML register response: service={reg['service']} "
                         f"status={reg['status']} handle={reg['handle']}")
                self._last_reg = reg
                self._reg_event.set()
            return

        # Check if this is data for our GFDI handle
        if not data or data[0] != self.gfdi_handle:
            return

        # Accumulate payload bytes (strip handle byte)
        self._rx_buffer.extend(data[1:])

        # Try to decode a complete GFDI response
        response = gfdi_decode_response(bytes(self._rx_buffer))
        if response is not None:
            log.debug(f"GFDI response: type={response.original_type} status={response.status}")
            self._rx_buffer.clear()
            self._last_response = response
            self._response_event.set()

    # ──────────────────────────────────────────
    # ML service registration
    # ──────────────────────────────────────────

    async def register_services(self) -> bool:
        """Register the GFDI service and obtain a handle."""
        # Register REGISTRATION service (gets device info)
        await self._write(ml_register_request(SERVICE_REGISTRATION, reliable=False))
        await asyncio.sleep(0.3)

        # Register GFDI service with reliable mode
        self._reg_event.clear()
        await self._write(ml_register_request(SERVICE_GFDI, reliable=True))

        try:
            await asyncio.wait_for(self._reg_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            log.error("Timed out waiting for GFDI registration response")
            return False

        reg = self._last_reg
        if not reg or reg["status"] != ML_STATUS_SUCCESS:
            log.error(f"GFDI registration rejected: {reg}")
            return False

        self.gfdi_handle = reg["handle"] or 0x01
        log.info(f"GFDI registered: handle=0x{self.gfdi_handle:02X}")
        return True

    # ──────────────────────────────────────────
    # GFDI send / receive
    # ──────────────────────────────────────────

    async def send_gfdi(self, encoded: bytes, timeout: float = 10.0) -> Optional[GfdiResponse]:
        """Send a GFDI message and wait for the response."""
        self._response_event.clear()
        self._last_response = None

        chunks = ml_chunk_message(self.gfdi_handle, encoded)
        for chunk in chunks:
            await self._write(chunk)
            await asyncio.sleep(0.05)

        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            log.warning("Timed out waiting for GFDI response")
            return None

        return self._last_response

    async def _write(self, data: bytes):
        """Write bytes to the device."""
        log.debug(f"TX: {data.hex()}")
        await self.client.write_gatt_char(self.write_char, data, response=True)

    # ──────────────────────────────────────────
    # File operations
    # ──────────────────────────────────────────

    async def list_fit_files(self) -> List[FitFileEntry]:
        """List all pending FIT activity files on the device."""
        # Set directory filter to pending upload files only
        await self.send_gfdi(self.builder.directory_filter(FILTER_PENDING_UPLOAD))

        # Request file listing
        response = await self.send_gfdi(self.builder.find_request(FIT_ACTIVITY_TYPE))
        if not response:
            return []

        files = parse_find_response(response)
        activity_files = [f for f in files if f.data_type == FIT_ACTIVITY_TYPE]
        log.info(f"Found {len(activity_files)} activity file(s)")
        return activity_files

    async def download_fit_file(
        self,
        file_entry: FitFileEntry,
        progress_callback=None
    ) -> Optional[bytes]:
        """
        Download a FIT file from the device.

        @param file_entry     File entry from list_fit_files()
        @param progress_callback  Called with (bytes_received, total_bytes)
        """
        file_data = bytearray()
        offset = 0

        while offset < file_entry.file_size:
            response = await self.send_gfdi(
                self.builder.download_request(file_entry.file_index, offset),
                timeout=15.0
            )
            if not response:
                log.error(f"Download timed out at offset {offset}")
                return None

            chunk = parse_download_response(response)
            if not chunk:
                log.error(f"Invalid download response at offset {offset}")
                return None

            file_data.extend(chunk["data"])
            offset += len(chunk["data"])

            if progress_callback:
                progress_callback(offset, file_entry.file_size)

            if chunk["complete"]:
                break

        return bytes(file_data)

    async def mark_file_archived(self, file_index: int):
        """Mark a file as archived so it won't appear in the next sync."""
        await self.send_gfdi(self.builder.set_file_flags(file_index, FLAG_ARCHIVE))


# ──────────────────────────────────────────────
# Device scanner
# ──────────────────────────────────────────────

async def scan_for_devices(timeout: float = 10.0, target_name: Optional[str] = None) -> List[BLEDevice]:
    """
    Scan for BLE cycling computers.
    Returns all found devices, or filters by name if target_name is given.
    """
    log.info(f"Scanning for BLE devices ({timeout}s)...")

    found = []

    def detection_callback(device: BLEDevice, advertisement_data):
        name = device.name or "Unknown"
        uuids = [u.lower() for u in (advertisement_data.service_uuids or [])]

        is_garmin_protocol = SERVICE_ML in uuids or SERVICE_LEGACY in uuids

        if is_garmin_protocol:
            if target_name is None or target_name.lower() in name.lower():
                if device not in found:
                    log.info(f"  Found: {name} ({device.address})")
                    found.append(device)

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()

    return found


# ──────────────────────────────────────────────
# Main sync flow
# ──────────────────────────────────────────────

async def sync(
    target_name: Optional[str] = None,
    upload_to_strava: bool = True,
    output_dir: str = "fit_files"
):
    """
    Full sync: scan → connect → download FIT files → optionally upload to Strava.
    """
    # Find device
    devices = await scan_for_devices(target_name=target_name)
    if not devices:
        print("\nNo compatible cycling computer found.")
        print("Make sure your device is powered on and within range.")
        return

    # Use first found device (or let user pick if multiple)
    device = devices[0]
    if len(devices) > 1:
        print("\nMultiple devices found:")
        for i, d in enumerate(devices):
            print(f"  {i + 1}. {d.name} ({d.address})")
        choice = int(input("Select device (number): ")) - 1
        device = devices[choice]

    print(f"\nConnecting to {device.name}...")

    async with BleakClient(device) as client:
        if not client.is_connected:
            print("Failed to connect.")
            return

        print(f"Connected to {device.name}")

        session = GarminBleSession(client)

        # Setup characteristics and enable notifications
        if not await session.setup():
            print("Device does not appear to use the Garmin ML protocol.")
            print("This device may not be supported yet.")
            return

        # Register GFDI service
        if not await session.register_services():
            print("Could not register file transfer service.")
            return

        # List files
        files = await session.list_fit_files()
        if not files:
            print("No new activities found on device.")
            return

        print(f"\nFound {len(files)} new activit{'y' if len(files) == 1 else 'ies'}:")
        for f in files:
            print(f"  [{f.file_index}] size={f.file_size} bytes")

        # Download each file
        os.makedirs(output_dir, exist_ok=True)
        downloaded = []

        for file_entry in files:
            print(f"\nDownloading file {file_entry.file_index}...", end="", flush=True)

            def progress(received, total):
                pct = int(received / total * 100)
                print(f"\r  Downloading... {pct}%", end="", flush=True)

            data = await session.download_fit_file(file_entry, progress_callback=progress)
            print()

            if data is None:
                print(f"  Failed to download file {file_entry.file_index}")
                continue

            # Save locally
            path = os.path.join(output_dir, f"activity_{file_entry.file_index}.fit")
            with open(path, "wb") as f:
                f.write(data)
            print(f"  Saved to {path}")

            # Mark as archived on device
            await session.mark_file_archived(file_entry.file_index)
            downloaded.append((path, data))

        if not downloaded:
            return

        # Upload to Strava
        if upload_to_strava:
            print(f"\nUploading {len(downloaded)} activit{'y' if len(downloaded) == 1 else 'ies'} to Strava...")
            import dotenv
            dotenv.load_dotenv(".env")
            import exporter
            token = exporter.authenticate()
            for path, data in downloaded:
                upload_fit_bytes_to_strava(token, data, path)

        print(f"\nDone. {len(downloaded)} activit{'y' if len(downloaded) == 1 else 'ies'} synced.")


def upload_fit_bytes_to_strava(token: dict, data: bytes, path: str):
    """Upload raw FIT bytes to Strava."""
    import requests as req
    import datetime
    from dateutil import tz

    now = datetime.datetime.now(tz.tzlocal())
    hour = now.hour
    if 5 <= hour < 12:
        time_label = "Morning"
    elif 12 <= hour < 18:
        time_label = "Afternoon"
    else:
        time_label = "Evening"

    name = f"{time_label} ride (via Strava exporter)"

    r = req.post(
        "https://www.strava.com/api/v3/uploads",
        params={"access_token": token["access_token"]},
        files={"file": ("activity.fit", data, "application/octet-stream")},
        data={"name": name, "data_type": "fit", "trainer": "Workout"}
    )

    if r.ok:
        print(f"  Uploaded: {path} → Strava activity {r.json().get('id_str')}")
    else:
        print(f"  Upload failed for {path}: {r.content}")


# ──────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BLE cycling computer → Strava sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scan",  action="store_true", help="Scan and list nearby devices")
    group.add_argument("--sync",  action="store_true", help="Sync activities to Strava")

    parser.add_argument("--device",    type=str,  default=None,  help="Target device name (partial match)")
    parser.add_argument("--no-upload", action="store_true",      help="Download FIT files but do not upload to Strava")
    parser.add_argument("--output",    type=str,  default="fit_files", help="Directory to save FIT files")
    parser.add_argument("--debug",     action="store_true",      help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.scan:
        async def do_scan():
            devices = await scan_for_devices()
            if not devices:
                print("No compatible devices found.")
            else:
                print(f"\nFound {len(devices)} compatible device(s).")
        asyncio.run(do_scan())

    elif args.sync:
        asyncio.run(sync(
            target_name=args.device,
            upload_to_strava=not args.no_upload,
            output_dir=args.output
        ))


if __name__ == "__main__":
    main()