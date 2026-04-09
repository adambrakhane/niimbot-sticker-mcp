"""NIIMBOT B1 Pro USB communication library.

Uses pyusb to talk to the printer's USB Printer Class bulk endpoints (interface 2).
The CDC ACM serial interface the device also exposes silently drops Niimbot protocol
bytes — only the Printer Class bulk endpoints actually route to the firmware.

Protocol framing and command codes are identical to BLE; the only wire-level
difference is that the Connect packet must be prefixed with a literal 0x03 byte.
"""
import asyncio
import logging
import struct
import time
from enum import IntEnum

import usb.core
import usb.util

from niimbot.ble import NiimbotPacket, RequestCode, InfoCode

log = logging.getLogger("niimbot.usb")

# B1 Pro USB identification
VENDOR_ID = 0x3513
PRODUCT_ID = 0x0002

# Printer Class interface + bulk endpoints (see memory/project_usb_transport.md)
PRINTER_INTERFACE = 2
EP_OUT = 0x03
EP_IN = 0x87

# Max bulk packet size for the B1 Pro printer interface
BULK_MAX_PACKET = 64


def find_device() -> bool:
    """Quick synchronous probe: is a B1 Pro on the USB bus?"""
    try:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        return dev is not None
    except Exception as e:
        log.debug(f"USB probe error: {e}")
        return False


class NiimbotUSB:
    """USB transport for NIIMBOT B1 Pro printers via the Printer Class bulk endpoints.

    pyusb is blocking; all USB I/O is dispatched through asyncio.to_thread so the
    daemon's event loop stays responsive.
    """

    def __init__(self, disconnected_callback=None):
        self._dev = None
        self._claimed = False
        self._rx_buffer = bytearray()
        self._disconnected_callback = disconnected_callback
        self._closed = False

    @property
    def is_connected(self) -> bool:
        return self._dev is not None and self._claimed and not self._closed

    @property
    def transport_name(self) -> str:
        return "USB"

    async def connect(self, connect_timeout: float = 5.0) -> bool:
        """Find the USB device, claim the printer interface, and send Connect."""
        def _open():
            dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
            if dev is None:
                raise RuntimeError("No NIIMBOT printer found on USB")
            usb.util.claim_interface(dev, PRINTER_INTERFACE)
            return dev

        self._dev = await asyncio.to_thread(_open)
        self._claimed = True
        self._closed = False
        log.info(f"Claimed USB Printer Class interface {PRINTER_INTERFACE}")

        # Send the Connect packet (with required 0x03 prefix) so the firmware
        # knows we're here and returns its protocol version.
        try:
            await self._send_connect()
        except Exception as e:
            log.warning(f"USB Connect handshake failed: {e}")
            await self.disconnect()
            raise

        return True

    async def _send_connect(self):
        """Send the prefixed Connect packet and verify response 0xc2."""
        packet = NiimbotPacket(RequestCode.CONNECT, b"\x01")
        framed = b"\x03" + packet.to_bytes()
        await self.write_raw(framed)

        # Wait briefly for the Connect response (0xc2)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            packets = await self._recv(timeout=0.3)
            for pkt in packets:
                if pkt.type == 0xc2:
                    log.info(f"USB Connect OK (protocol version {pkt.data.hex()})")
                    return
        raise RuntimeError("USB Connect: no 0xc2 response (is printer powered on?)")

    async def disconnect(self):
        self._closed = True
        if self._dev is not None and self._claimed:
            def _release():
                try:
                    usb.util.release_interface(self._dev, PRINTER_INTERFACE)
                except Exception as e:
                    log.debug(f"release_interface: {e}")
            await asyncio.to_thread(_release)
            self._claimed = False
            log.info("USB disconnected")
        self._dev = None

    def _handle_disconnect(self, reason: str):
        """Invoked when USB I/O detects the device has gone away."""
        if self._closed:
            return
        log.warning(f"USB transport lost: {reason}")
        self._closed = True
        self._claimed = False
        if self._disconnected_callback:
            try:
                self._disconnected_callback(self)
            except Exception as e:
                log.error(f"disconnected_callback error: {e}")

    async def write_raw(self, data: bytes, response: bool = False):
        """Write raw bytes to the printer bulk OUT endpoint.

        `response` is ignored — USB bulk writes are inherently reliable.
        """
        if self._dev is None or self._closed:
            raise RuntimeError("USB not connected")
        log.debug(f"TX ({len(data)} bytes): {data.hex()}")

        def _write():
            self._dev.write(EP_OUT, data, timeout=3000)

        try:
            await asyncio.to_thread(_write)
        except usb.core.USBError as e:
            # NO_DEVICE / pipe errors mean the cable was yanked or firmware reset
            if e.errno in (19, 5) or "No such device" in str(e):
                self._handle_disconnect(str(e))
            raise

    async def _read_once(self, timeout_ms: int = 200) -> bytes:
        """Do one non-blocking bulk IN read. Returns b'' on timeout."""
        if self._dev is None or self._closed:
            return b""

        def _read():
            try:
                return bytes(self._dev.read(EP_IN, 512, timeout=timeout_ms))
            except usb.core.USBError as e:
                if "timeout" in str(e).lower() or "Operation timed out" in str(e):
                    return b""
                raise

        try:
            chunk = await asyncio.to_thread(_read)
            if chunk:
                log.debug(f"RX ({len(chunk)} bytes): {chunk.hex()}")
            return chunk
        except usb.core.USBError as e:
            if e.errno in (19, 5) or "No such device" in str(e):
                self._handle_disconnect(str(e))
            raise

    async def _recv(self, timeout: float = 1.0) -> list:
        """Read bytes from bulk IN and parse any complete Niimbot packets."""
        packets = []
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            chunk = await self._read_once(timeout_ms=200)
            if chunk:
                self._rx_buffer.extend(chunk)

            # Parse any complete packets in buffer
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
                    del self._rx_buffer[:start]
                if len(self._rx_buffer) < 7:
                    break
                pkt_len = self._rx_buffer[3] + 7
                if len(self._rx_buffer) < pkt_len:
                    break
                try:
                    pkt = NiimbotPacket.from_bytes(bytes(self._rx_buffer[:pkt_len]))
                    packets.append(pkt)
                except ValueError as e:
                    log.warning(f"Packet parse error: {e}")
                del self._rx_buffer[:pkt_len]

            if packets:
                return packets

        return packets

    async def transceive(self, reqcode: int, data: bytes, respoffset: int = 1,
                         timeout: float = 3.0, recv_timeout: float = 0.5,
                         retries: int = 6) -> NiimbotPacket | None:
        """Send a request and wait for a matching response."""
        respcode = respoffset + reqcode
        packet = NiimbotPacket(reqcode, data)
        await self.write_raw(packet.to_bytes())

        for _ in range(retries):
            packets = await self._recv(timeout=recv_timeout)
            for pkt in packets:
                if pkt.type == 219:  # Error
                    log.error(f"Printer error: {pkt}")
                    raise ValueError(f"Printer returned error: {pkt}")
                if pkt.type == respcode:
                    return pkt
                log.debug(f"Unexpected response type 0x{pkt.type:02x} (expected 0x{respcode:02x})")

        log.warning(f"No response for cmd 0x{reqcode:02x}")
        return None

    async def _drain_notifications(self, timeout: float = 0.2) -> list:
        """Drain any pending bytes from the printer for the given window."""
        return await self._recv(timeout=timeout)

    # === High-level commands (byte-for-byte identical to NiimbotBLE) ===

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

    async def get_info(self, key: int):
        pkt = await self.transceive(RequestCode.GET_INFO, bytes([key]), respoffset=key)
        if pkt is None:
            return None

        if key == InfoCode.DEVICESERIAL or key == InfoCode.DEVICESERIAL2:
            return pkt.data.hex()
        elif key in (InfoCode.SOFTVERSION, InfoCode.HARDVERSION):
            return int.from_bytes(pkt.data, "big") / 100
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

    async def set_label_type(self, n: int) -> bool:
        pkt = await self.transceive(RequestCode.SET_LABEL_TYPE, bytes([n]), respoffset=16)
        return pkt is not None and pkt.data[0] == 1

    async def set_label_density(self, n: int) -> bool:
        pkt = await self.transceive(RequestCode.SET_LABEL_DENSITY, bytes([n]), respoffset=16)
        return pkt is not None and pkt.data[0] == 1

    async def start_print(self, total_pages: int = 1) -> bool:
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
