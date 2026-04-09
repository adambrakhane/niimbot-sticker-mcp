"""Consolidated print logic for NIIMBOT printers.

Based on the proven print flow from fast_print.py's print_image_proven(),
which is the only path confirmed to work reliably.

Works with any transport that implements the NiimbotBLE/NiimbotUSB interface:
write_raw(), transceive(), and the high-level command methods.
"""
import asyncio
import logging
import struct
from PIL import ImageOps

from niimbot.ble import NiimbotPacket, RequestCode

log = logging.getLogger("niimbot.printing")


def extract_rows(img):
    """Convert a PIL Image to row bytes for the printer.

    Returns (rows, width, height, width_bytes).
    Uses the proven getpixel method from test_combos.py.
    """
    bw = ImageOps.invert(img.convert("L")).convert("1")
    w, h = bw.width, bw.height
    wb = w // 8

    all_rows = []
    for y in range(h):
        row = bytearray(wb)
        for bi in range(wb):
            val = 0
            for bit in range(8):
                x = bi * 8 + bit
                if x < w and bw.getpixel((x, y)) != 0:
                    val |= (1 << (7 - bit))
            row[bi] = val
        all_rows.append(bytes(row))
    return all_rows, w, h, wb


async def print_image(printer, img, density: int = 3, batch_size: int = 32):
    """Print a PIL Image on the printer.

    This is the single canonical print implementation. All tools should use this.

    Args:
        printer: Connected transport (NiimbotBLE or NiimbotUSB).
        img: PIL Image to print (any mode — will be converted to 1-bit).
        density: Print darkness 1-5 (default 3).
        batch_size: Flow control — write-with-response every N rows (BLE only;
                    USB ignores the response flag since bulk writes are reliable).
                    32 = proven fast and reliable (~2.5s for 350 rows over BLE).
                    1 = safe/slow (~28s for 350 rows over BLE).
    """
    rows, w, h, wb = extract_rows(img)

    # Clear any previous state
    try:
        await printer.end_print()
    except Exception:
        pass
    await asyncio.sleep(0.2)

    # Setup
    await printer.set_label_density(density)
    await printer.set_label_type(1)

    data = struct.pack(">H", 1) + bytes([0x00, 0x00, 0x00, 0x00, 0x00])
    await printer.transceive(RequestCode.START_PRINT, data)
    await printer.start_page_print()

    dim_data = struct.pack(">HHH", h, w, 1)
    await printer.transceive(RequestCode.SET_DIMENSION, dim_data)

    # Send rows
    for y in range(h):
        row = rows[y]
        black_count = sum(bin(b).count('1') for b in row)
        if black_count == 0:
            header = struct.pack(">HB", y, 1)
            pkt = NiimbotPacket(RequestCode.PRINT_EMPTY_ROW, header)
        else:
            counts = bytes([0, black_count & 0xFF, (black_count >> 8) & 0xFF])
            header = struct.pack(">H", y) + counts + struct.pack("B", 1)
            pkt = NiimbotPacket(RequestCode.PRINT_BITMAP_ROW, header + row)

        use_response = ((y + 1) % batch_size == 0) or (y == h - 1)
        await printer.write_raw(pkt.to_bytes(), response=use_response)

        if (y + 1) % 100 == 0:
            log.info(f"row {y+1}/{h}")

    log.info(f"All {h} rows sent")

    # Post-print: proven flow from test_combos.py
    await asyncio.sleep(1.0)
    await printer._drain_notifications(timeout=0.5)
    await printer.end_page_print()

    for i in range(60):
        status = await printer.get_print_status()
        p = status.get("progress1", 0)
        if i % 5 == 0:
            log.info(f"status: {p}%")
        if p >= 100:
            break
        await asyncio.sleep(0.5)

    await printer.end_print()

    # Printer needs BLE connection alive while label ejects
    await asyncio.sleep(2.0)
