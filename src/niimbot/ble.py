"""NIIMBOT B1 Pro BLE communication library.

Uses bleak for BLE transport instead of classic BT RFCOMM.
Based on protocol from niimprint and niimblue projects.
"""
import asyncio
import json
import struct
import math
import logging
from pathlib import Path
from enum import IntEnum
from bleak import BleakClient, BleakScanner

log = logging.getLogger("niimbot")

# BLE characteristics for ISSC transparent UART
# Service 2 is more commonly used for serial data on NIIMBOT
SERVICE_UUID = "e7810a71-73ae-499d-8c15-faa9aef0c3f2"
CHAR_UUID = "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"

# Alternative: ISSC Serial Port service
ALT_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
ALT_NOTIFY_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
ALT_WRITE_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"


class RequestCode(IntEnum):
    GET_INFO = 0x40
    GET_RFID = 0x1a
    HEARTBEAT = 0xdc
    SET_LABEL_TYPE = 0x23
    SET_LABEL_DENSITY = 0x21
    START_PRINT = 0x01
    END_PRINT = 0xf3
    START_PAGE_PRINT = 0x03
    END_PAGE_PRINT = 0xe3
    SET_DIMENSION = 0x13
    SET_QUANTITY = 0x15
    GET_PRINT_STATUS = 0xa3
    ALLOW_PRINT_CLEAR = 0x20
    PRINT_BITMAP_ROW = 0x85
    PRINT_EMPTY_ROW = 0x84
    PRINT_BITMAP_ROW_INDEXED = 0x83
    CONNECT = 0xc1
    CANCEL_PRINT = 0xda
    PRINT_TEST_PAGE = 0x5a


class InfoCode(IntEnum):
    DEVICESERIAL = 0x01
    SOFTVERSION = 0x02
    HARDVERSION = 0x03
    # Some models use different codes
    DEVICESERIAL2 = 0x0b


class NiimbotPacket:
    def __init__(self, type_: int, data: bytes):
        self.type = type_
        self.data = data

    @classmethod
    def from_bytes(cls, pkt: bytes):
        if pkt[:2] != b"\x55\x55":
            raise ValueError(f"Bad header: {pkt[:2].hex()}")
        if pkt[-2:] != b"\xaa\xaa":
            raise ValueError(f"Bad tail: {pkt[-2:].hex()}")
        type_ = pkt[2]
        len_ = pkt[3]
        data = pkt[4:4 + len_]

        checksum = type_ ^ len_
        for b in data:
            checksum ^= b
        if checksum != pkt[-3]:
            raise ValueError(f"Checksum mismatch: expected {checksum:#x}, got {pkt[-3]:#x}")

        return cls(type_, data)

    def to_bytes(self) -> bytes:
        checksum = self.type ^ len(self.data)
        for b in self.data:
            checksum ^= b
        return bytes([0x55, 0x55, self.type, len(self.data), *self.data, checksum, 0xAA, 0xAA])

    def __repr__(self):
        return f"<Packet cmd=0x{self.type:02x} len={len(self.data)} data={self.data.hex()}>"


class NiimbotBLE:
    """BLE transport for NIIMBOT printers."""

    def __init__(self):
        self.client = None
        self._rx_buffer = bytearray()
        self._rx_event = asyncio.Event()
        self._use_alt = False  # Whether to use alt service

    def _notification_handler(self, sender, data: bytearray):
        log.debug(f"RX ({len(data)} bytes): {data.hex()}")
        self._rx_buffer.extend(data)
        self._rx_event.set()

    async def connect(self, address: str = None, connect_timeout: float = 20.0):
        """Connect to NIIMBOT printer. If no address, try cache then scan."""
        if address is None:
            # Try cached address first
            from niimbot.labels import get_ble_cache_path
            cache_path = get_ble_cache_path()
            if cache_path.exists():
                try:
                    cached = json.loads(cache_path.read_text())
                    address = cached.get("address")
                    log.info(f"Trying cached address: {address} ({cached.get('name', '?')})")
                except Exception:
                    pass

        if address is None:
            log.info("Scanning for NIIMBOT printer...")
            devices = await BleakScanner.discover(timeout=10.0)
            for d in devices:
                name = d.name or ""
                if "b1" in name.lower() or "niim" in name.lower():
                    address = d.address
                    log.info(f"Found: {d.name} @ {d.address}")
                    # Cache for next time
                    from niimbot.labels import get_ble_cache_path
                    cache_path = get_ble_cache_path()
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps({"address": address, "name": d.name}))
                    break
            if address is None:
                raise RuntimeError("No NIIMBOT printer found")

        self.client = BleakClient(address, timeout=connect_timeout)
        await self.client.connect()
        log.info(f"Connected: {self.client.is_connected}")

        # Check MTU
        mtu = self.client.mtu_size
        log.info(f"MTU: {mtu}")

        # Use the ISSC serial port service (49535343-...) - this is what niimbluelib uses
        # Notify on the RX characteristic, write on the TX characteristic
        try:
            await self.client.start_notify(ALT_NOTIFY_UUID, self._notification_handler)
            self._write_uuid = ALT_WRITE_UUID
            log.info(f"Using ISSC serial port service (notify={ALT_NOTIFY_UUID}, write={ALT_WRITE_UUID})")
        except Exception as e:
            log.warning(f"Alt service failed ({e}), trying primary UART service")
            await self.client.start_notify(CHAR_UUID, self._notification_handler)
            self._write_uuid = CHAR_UUID
            log.info(f"Using primary UART service (single char: {CHAR_UUID})")

        return True

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            log.info("Disconnected")

    async def _send(self, packet: NiimbotPacket, response: bool = False):
        data = packet.to_bytes()
        log.debug(f"TX ({len(data)} bytes): {data.hex()}")
        await self.client.write_gatt_char(self._write_uuid, data, response=response)

    async def _recv(self, timeout: float = 3.0) -> list:
        """Wait for and parse response packets."""
        packets = []
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            self._rx_event.clear()

            # Try to parse any complete packets in buffer
            while len(self._rx_buffer) > 4:
                # Find packet start
                start = -1
                for i in range(len(self._rx_buffer) - 1):
                    if self._rx_buffer[i] == 0x55 and self._rx_buffer[i + 1] == 0x55:
                        start = i
                        break

                if start == -1:
                    self._rx_buffer.clear()
                    break

                if start > 0:
                    self._rx_buffer = self._rx_buffer[start:]

                if len(self._rx_buffer) < 7:  # minimum packet size
                    break

                pkt_len = self._rx_buffer[3] + 7  # header(2) + cmd(1) + len(1) + data(N) + checksum(1) + tail(2)
                if len(self._rx_buffer) < pkt_len:
                    break

                try:
                    pkt = NiimbotPacket.from_bytes(bytes(self._rx_buffer[:pkt_len]))
                    packets.append(pkt)
                    log.debug(f"Parsed: {pkt}")
                except ValueError as e:
                    log.warning(f"Packet parse error: {e}")
                del self._rx_buffer[:pkt_len]

            if packets:
                return packets

            try:
                await asyncio.wait_for(self._rx_event.wait(), timeout=min(0.5, deadline - asyncio.get_event_loop().time()))
            except asyncio.TimeoutError:
                continue

        return packets

    async def transceive(self, reqcode: int, data: bytes, respoffset: int = 1,
                         timeout: float = 3.0, recv_timeout: float = 0.5,
                         retries: int = 6) -> NiimbotPacket | None:
        """Send a request and wait for a response."""
        respcode = respoffset + reqcode
        packet = NiimbotPacket(reqcode, data)
        await self._send(packet)

        for attempt in range(retries):
            packets = await self._recv(timeout=recv_timeout)
            for pkt in packets:
                if pkt.type == 219:  # Error
                    log.error(f"Printer error: {pkt}")
                    raise ValueError(f"Printer returned error: {pkt}")
                elif pkt.type == respcode:
                    return pkt
                else:
                    log.debug(f"Unexpected response type 0x{pkt.type:02x} (expected 0x{respcode:02x})")

        log.warning(f"No response for cmd 0x{reqcode:02x}")
        return None

    # === High-level commands ===

    async def heartbeat(self) -> dict:
        pkt = await self.transceive(RequestCode.HEARTBEAT, b"\x01")
        if pkt is None:
            return {"error": "no response"}

        result = {"raw": pkt.data.hex(), "data_len": len(pkt.data)}
        d = pkt.data

        if len(d) == 20:
            result["paperstate"] = d[18]
            result["rfidreadstate"] = d[19]
        elif len(d) == 13:
            result["closingstate"] = d[9]
            result["powerlevel"] = d[10]
            result["paperstate"] = d[11]
            result["rfidreadstate"] = d[12]
        elif len(d) == 10:
            result["closingstate"] = d[8]
            result["powerlevel"] = d[9]
        elif len(d) >= 9:
            result["closingstate"] = d[8]

        return result

    async def get_info(self, key: int) -> str | int | None:
        pkt = await self.transceive(RequestCode.GET_INFO, bytes([key]), respoffset=key)
        if pkt is None:
            return None

        if key == InfoCode.DEVICESERIAL or key == InfoCode.DEVICESERIAL2:
            return pkt.data.hex()
        elif key in (InfoCode.SOFTVERSION, InfoCode.HARDVERSION):
            val = int.from_bytes(pkt.data, "big")
            return val / 100
        else:
            return int.from_bytes(pkt.data, "big")

    async def get_rfid(self) -> dict | None:
        pkt = await self.transceive(RequestCode.GET_RFID, b"\x01")
        if pkt is None:
            return None

        d = pkt.data
        if d[0] == 0:
            return {"has_rfid": False}

        try:
            uuid = d[0:8].hex()
            idx = 8
            barcode_len = d[idx]
            idx += 1
            barcode = d[idx:idx + barcode_len].decode()
            idx += barcode_len
            serial_len = d[idx]
            idx += 1
            serial = d[idx:idx + serial_len].decode()
            idx += serial_len
            total_len, used_len, type_ = struct.unpack(">HHB", d[idx:idx + 5])
            return {
                "has_rfid": True,
                "uuid": uuid,
                "barcode": barcode,
                "serial": serial,
                "used_len": used_len,
                "total_len": total_len,
                "type": type_,
            }
        except Exception as e:
            return {"has_rfid": True, "raw": d.hex(), "error": str(e)}

    async def get_all_info(self) -> dict:
        """Get all available printer info."""
        info = {}
        info["serial"] = await self.get_info(InfoCode.DEVICESERIAL)
        info["software_version"] = await self.get_info(InfoCode.SOFTVERSION)
        info["hardware_version"] = await self.get_info(InfoCode.HARDVERSION)
        info["serial2"] = await self.get_info(InfoCode.DEVICESERIAL2)
        return info

    async def set_label_type(self, n: int) -> bool:
        pkt = await self.transceive(RequestCode.SET_LABEL_TYPE, bytes([n]), respoffset=16)
        return pkt is not None and pkt.data[0] == 1

    async def set_label_density(self, n: int) -> bool:
        pkt = await self.transceive(RequestCode.SET_LABEL_DENSITY, bytes([n]), respoffset=16)
        return pkt is not None and pkt.data[0] == 1

    async def start_print(self, total_pages=1) -> bool:
        # B1 uses 7-byte format per protocol docs
        # Bytes: [total_pages_hi, total_pages_lo, 0, 0, 0, 0, page_color]
        data = struct.pack(">HH", 0, total_pages) + bytes([0, 0, 0])
        pkt = await self.transceive(RequestCode.START_PRINT, data)
        return pkt is not None and pkt.data[0] == 1

    async def end_print(self) -> bool:
        pkt = await self.transceive(RequestCode.END_PRINT, b"\x01")
        return pkt is not None and pkt.data[0] == 1

    async def start_page_print(self) -> bool:
        pkt = await self.transceive(RequestCode.START_PAGE_PRINT, b"\x01")
        return pkt is not None and pkt.data[0] == 1

    async def end_page_print(self) -> bool:
        pkt = await self.transceive(RequestCode.END_PAGE_PRINT, b"\x01")
        return pkt is not None and pkt.data[0] == 1

    async def set_dimension(self, rows: int, cols: int) -> bool:
        data = struct.pack(">HH", rows, cols)
        pkt = await self.transceive(RequestCode.SET_DIMENSION, data)
        return pkt is not None and pkt.data[0] == 1

    async def set_quantity(self, n: int) -> bool:
        pkt = await self.transceive(RequestCode.SET_QUANTITY, struct.pack(">H", n))
        return pkt is not None and pkt.data[0] == 1

    async def get_print_status(self) -> dict:
        pkt = await self.transceive(RequestCode.GET_PRINT_STATUS, b"\x01", respoffset=16)
        if pkt is None:
            return {"error": "no response"}
        d = pkt.data
        log.debug(f"Print status raw ({len(d)} bytes): {d.hex()}")
        if len(d) >= 4:
            page = struct.unpack(">H", d[0:2])[0]
            progress1 = d[2] if len(d) > 2 else 0
            progress2 = d[3] if len(d) > 3 else 0
            return {"page": page, "progress1": progress1, "progress2": progress2, "raw": d.hex()}
        return {"raw": d.hex()}

    async def _drain_notifications(self, timeout=0.2):
        """Drain any pending notifications from the printer."""
        try:
            await asyncio.wait_for(self._rx_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        self._rx_event.clear()
        # Parse any packets in buffer
        packets = []
        while len(self._rx_buffer) > 4:
            start = -1
            for i in range(len(self._rx_buffer) - 1):
                if self._rx_buffer[i] == 0x55 and self._rx_buffer[i + 1] == 0x55:
                    start = i
                    break
            if start == -1:
                self._rx_buffer.clear()
                break
            if start > 0:
                self._rx_buffer = self._rx_buffer[start:]
            if len(self._rx_buffer) < 7:
                break
            pkt_len = self._rx_buffer[3] + 7
            if len(self._rx_buffer) < pkt_len:
                break
            try:
                pkt = NiimbotPacket.from_bytes(bytes(self._rx_buffer[:pkt_len]))
                packets.append(pkt)
                log.debug(f"Drained: {pkt}")
            except ValueError as e:
                log.warning(f"Drain parse error: {e}")
            del self._rx_buffer[:pkt_len]
        return packets
