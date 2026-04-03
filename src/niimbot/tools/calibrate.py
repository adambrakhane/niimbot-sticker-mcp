"""Calibrate a new label size: read RFID, estimate dimensions, print test, save to label_db.json."""
import asyncio
import logging
from PIL import Image, ImageDraw, ImageFont

from niimbot.ble import NiimbotBLE
from niimbot.printing import print_image
from niimbot.labels import load_label_db, save_label_db, get_label_db_path

logging.basicConfig(level=logging.INFO, format='%(name)s:%(levelname)s: %(message)s')
logging.getLogger("bleak").setLevel(logging.WARNING)
log = logging.getLogger("calibrate")

B1_PRO_WIDTH = 568
DPI = 300


def create_calibration_image(width, height, label_text):
    """Test image with borders and a bottom ruler to measure cutoff."""
    img = Image.new("1", (width, height), color=1)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, width - 1, 3], fill=0)
    draw.rectangle([0, height - 4, width - 1, height - 1], fill=0)
    draw.rectangle([0, 0, 3, height - 1], fill=0)
    draw.rectangle([width - 4, 0, width - 1, height - 1], fill=0)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
        font_xs = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        font = ImageFont.load_default()
        font_sm = font
        font_xs = font

    draw.text((20, 20), "CALIBRATION", fill=0, font=font)
    draw.text((20, 70), label_text, fill=0, font=font_sm)
    draw.text((width - 200, 20), f"{width}x{height}", fill=0, font=font_sm)

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

    return img


async def main():
    db = load_label_db()

    print("Insert label roll and press Enter...")
    input()

    printer = NiimbotBLE()
    try:
        await printer.connect()
        await printer.heartbeat()

        rfid = await printer.get_rfid()
        if not rfid or not rfid.get("has_rfid"):
            print("ERROR: No RFID tag detected. Is the label roll seated properly?")
            return

        barcode = rfid.get("barcode", "")
        serial = rfid.get("serial", "")
        total_len = rfid.get("total_len", 0)
        label_type = rfid.get("type", 0)

        print(f"\n  Barcode:    {barcode}")
        print(f"  Serial:     {serial}")
        print(f"  Labels/roll: {total_len}")
        print(f"  Type:       {label_type}")

        if barcode in db["labels"]:
            existing = db["labels"][barcode]
            print(f"\n  Already calibrated: {existing['name']}")
            print(f"  Print area: {existing['print_width_px']}x{existing['print_height_px']}px")
            print(f"\n  r=recalibrate, Enter=quit: ", end="", flush=True)
            if input().strip().lower() != "r":
                return

        est_height_mm = None
        if len(barcode) >= 4:
            try:
                w_mm = int(barcode[0:2])
                h_mm = int(barcode[2:4])
                if 5 <= h_mm <= 100:
                    est_height_mm = h_mm
                    print(f"\n  Barcode suggests: {w_mm}mm x {h_mm}mm")
            except ValueError:
                pass

        print(f"\n  Enter label height in mm (e.g. 30)")
        if est_height_mm:
            print(f"  [Enter for {est_height_mm}mm from barcode]: ", end="", flush=True)
        else:
            print(f"  : ", end="", flush=True)
        height_input = input().strip()
        if height_input:
            height_mm = int(height_input)
        elif est_height_mm:
            height_mm = est_height_mm
        else:
            print("  Need a height to start with!")
            return

        print(f"\n  Enter label width in mm [40]: ", end="", flush=True)
        width_input = input().strip()
        width_mm = int(width_input) if width_input else 40

        label_name = f"{width_mm}x{height_mm}mm"
        print(f"\n  Enter label name [{label_name}]: ", end="", flush=True)
        name_input = input().strip()
        if name_input:
            label_name = name_input

        theoretical_px = int(height_mm * DPI / 25.4)
        test_height = theoretical_px - 4
        print(f"\n  Theoretical: {theoretical_px}px ({height_mm}mm @ {DPI} DPI)")
        print(f"  Starting test at: {test_height}px")

        while True:
            print(f"\n{'='*60}")
            print(f"  Printing {B1_PRO_WIDTH}x{test_height} test...")
            print(f"{'='*60}")

            img = create_calibration_image(B1_PRO_WIDTH, test_height, f"{label_name} @ {test_height}px")
            # Use batch_size=1 for calibration — slow but proven reliable
            await print_image(printer, img, batch_size=1)

            print(f"\n  Look at the print. Is the bottom border fully visible?")
            print(f"  y = yes, perfect!  |  t = too tall (cut off)  |  s = too short (gap at bottom)")
            print(f"  Or enter a px offset (e.g. -5 or +3)  |  q = quit")
            print(f"  : ", end="", flush=True)
            resp = input().strip().lower()

            if resp == "q":
                return
            elif resp == "y":
                db["labels"][barcode] = {
                    "barcode": barcode,
                    "name": label_name,
                    "nominal_width_mm": width_mm,
                    "nominal_height_mm": height_mm,
                    "print_width_px": B1_PRO_WIDTH,
                    "print_height_px": test_height,
                    "dpi": DPI,
                    "label_type": label_type,
                    "labels_per_roll": total_len,
                    "calibrated": True,
                    "notes": f"Theoretical {theoretical_px}px, actual {test_height}px.",
                }
                save_label_db(db)
                print(f"\n  Saved! {label_name}: {B1_PRO_WIDTH}x{test_height}px")
                print(f"  Written to {get_label_db_path()}")
                return
            elif resp == "t":
                test_height -= 2
            elif resp == "s":
                test_height += 2
            elif resp.lstrip("-+").isdigit():
                test_height += int(resp)
            else:
                print(f"  Didn't understand '{resp}', trying same height again.")

    finally:
        await printer.disconnect()


def cli():
    asyncio.run(main())


if __name__ == "__main__":
    cli()
