"""Query printer for label dimensions, then test descending heights.

Dev tool for exploring printer capabilities and testing print parameters.
"""
import asyncio
import logging
from PIL import Image, ImageDraw, ImageFont

from niimbot.ble import NiimbotBLE, RequestCode
from niimbot.printing import print_image

logging.basicConfig(level=logging.INFO, format='%(name)s:%(levelname)s: %(message)s')
logging.getLogger("bleak").setLevel(logging.WARNING)
log = logging.getLogger("test")

B1_PRO_WIDTH = 568


def create_test_image(width, height, label):
    img = Image.new("1", (width, height), color=1)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width - 1, 3], fill=0)
    draw.rectangle([0, 0, 3, height - 1], fill=0)
    draw.rectangle([width - 4, 0, width - 1, height - 1], fill=0)
    draw.rectangle([0, height - 4, width - 1, height - 1], fill=0)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        font_xs = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        font = ImageFont.load_default()
        font_sm = font
        font_xs = font

    draw.text((20, 20), "TEST", fill=0, font=font)
    draw.text((20, 70), label, fill=0, font=font_sm)

    for offset in range(0, 80):
        y = height - 1 - offset
        if y < 0:
            break
        if offset % 10 == 0:
            draw.line([(4, y), (60, y)], fill=0)
            draw.text((65, y - 7), f"-{offset}", fill=0, font=font_xs)
        elif offset % 5 == 0:
            draw.line([(4, y), (40, y)], fill=0)
        elif offset % 2 == 0:
            draw.line([(4, y), (20, y)], fill=0)

    draw.text((width - 200, height - 70), f"{width}x{height}", fill=0, font=font_sm)
    return img


async def query_printer_info(printer):
    """Query all PrinterInfoType values."""
    INFO_TYPES = {
        1: "Density", 2: "Speed", 3: "LabelType", 6: "Language",
        7: "AutoShutdownTime", 8: "PrinterModelId", 9: "SoftWareVersion",
        10: "BatteryChargeLevel", 11: "SerialNumber", 12: "HardWareVersion",
        13: "BluetoothAddress", 14: "PrintMode", 15: "Area",
    }

    print("\n=== PRINTER INFO ===")
    for key, name in INFO_TYPES.items():
        try:
            pkt = await printer.transceive(RequestCode.GET_INFO, bytes([key]), respoffset=key)
            if pkt:
                raw = pkt.data.hex()
                val = int.from_bytes(pkt.data, "big")
                print(f"  {name} ({key}): raw={raw} int={val} len={len(pkt.data)}")
            else:
                print(f"  {name} ({key}): no response")
        except Exception as e:
            print(f"  {name} ({key}): error: {e}")

    print("\n=== RFID INFO ===")
    rfid = await printer.get_rfid()
    if rfid:
        for k, v in rfid.items():
            print(f"  {k}: {v}")

    barcode = rfid.get("barcode", "") if rfid else ""
    if barcode:
        print(f"\n  Barcode: {barcode}")
        if len(barcode) >= 4:
            try:
                w_mm = int(barcode[0:2])
                h_mm = int(barcode[2:4])
                print(f"  Possible dims: {w_mm}mm x {h_mm}mm")
                print(f"  At 300 DPI: {int(w_mm * 300 / 25.4)}px x {int(h_mm * 300 / 25.4)}px")
            except ValueError:
                pass


TESTS = [
    (350, 3, "350px (calculated from cutoff)"),
]


async def main():
    printer = NiimbotBLE()
    try:
        await printer.connect()
        await printer.heartbeat()
        await query_printer_info(printer)
    except Exception:
        raise

    print("\n\nNow let's find the exact height.")
    print("Press Enter to start tests...")
    input()

    try:
        for i, (height, density, desc) in enumerate(TESTS):
            print(f"\n{'='*60}")
            print(f"Test {i+1}/{len(TESTS)}: {desc} ({B1_PRO_WIDTH}x{height})")
            print(f"{'='*60}")
            print("Enter=print, s=skip, q=quit: ", end="", flush=True)
            line = input().strip().lower()
            if line == 'q':
                break
            if line == 's':
                continue

            img = create_test_image(B1_PRO_WIDTH, height, desc)
            await print_image(printer, img, density=density, batch_size=1)
            log.info("Done!")

            print("\nWhat's the last visible tick? Enter=next, q=quit: ", end="", flush=True)
            line = input().strip().lower()
            if line == 'q':
                break
    finally:
        await printer.disconnect()

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
