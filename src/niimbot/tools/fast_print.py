"""Fast label printing with timing instrumentation.

Usage:
    python -m niimbot.tools.fast_print                     # print a test image
    python -m niimbot.tools.fast_print image.png           # print an image file
    python -m niimbot.tools.fast_print --density 5 img.png # darker print
"""
import argparse
import asyncio
import logging
import time
from PIL import Image, ImageDraw, ImageFont

from niimbot.ble import NiimbotBLE
from niimbot.printing import print_image
from niimbot.labels import load_label_db

logging.basicConfig(level=logging.INFO, format='%(name)s:%(levelname)s: %(message)s')
logging.getLogger("bleak").setLevel(logging.WARNING)
log = logging.getLogger("fast")

_timings = {}


def tick(name):
    _timings[name] = time.monotonic()


def tock(name):
    elapsed = time.monotonic() - _timings[name]
    _timings[name] = elapsed
    return elapsed


def print_timings():
    print(f"\n{'='*50}")
    print("TIMING BREAKDOWN")
    print(f"{'='*50}")
    total = 0
    for name, val in _timings.items():
        if isinstance(val, float) and val < 1000:
            print(f"  {name:20s}  {val:.3f}s")
            total += val
    print(f"  {'TOTAL':20s}  {total:.3f}s")
    print(f"{'='*50}")


def create_test_image(width, height):
    """Simple test image with borders and text."""
    img = Image.new("1", (width, height), color=1)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width - 1, 3], fill=0)
    draw.rectangle([0, height - 4, width - 1, height - 1], fill=0)
    draw.rectangle([0, 0, 3, height - 1], fill=0)
    draw.rectangle([width - 4, 0, width - 1, height - 1], fill=0)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
    except Exception:
        font = ImageFont.load_default()
        font_sm = font
    draw.text((20, 20), "FAST TEST", fill=0, font=font)
    draw.text((20, 70), f"{width}x{height}", fill=0, font=font_sm)
    return img


def prepare_image(image_path, width, height):
    """Load an image, resize to fit label, convert to 1-bit."""
    img = Image.open(image_path)
    img.thumbnail((width, height), Image.LANCZOS)
    bg = Image.new("L", (width, height), 255)
    x = (width - img.width) // 2
    y = (height - img.height) // 2
    bg.paste(img.convert("L"), (x, y))
    return bg.convert("1")


async def main():
    parser = argparse.ArgumentParser(description="Fast NIIMBOT label print")
    parser.add_argument("image", nargs="?", help="Image file to print (omit for test image)")
    parser.add_argument("--density", type=int, default=3, help="Print density 1-5 (default: 3)")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="Flow control: write-with-response every N rows (default: 32)")
    args = parser.parse_args()

    t_start = time.monotonic()
    db = load_label_db()

    tick("connect")
    printer = NiimbotBLE()
    await printer.connect(connect_timeout=5.0)
    tock("connect")
    print(f"Connected ({_timings['connect']:.3f}s)")

    try:
        tick("heartbeat")
        await printer.heartbeat()
        tock("heartbeat")

        tick("rfid")
        rfid = await printer.get_rfid()
        tock("rfid")

        barcode = rfid.get("barcode", "") if rfid else ""
        if barcode and barcode in db["labels"]:
            label = db["labels"][barcode]
            width = label["print_width_px"]
            height = label["print_height_px"]
            print(f"Label: {label['name']} ({width}x{height}px)")
        else:
            print(f"Unknown label barcode '{barcode}', using defaults 568x350")
            width, height = 568, 350

        tick("image_prep")
        if args.image:
            img = prepare_image(args.image, width, height)
        else:
            img = create_test_image(width, height)
        tock("image_prep")
        print(f"Image prepared ({_timings['image_prep']:.3f}s)")

        tick("print")
        await print_image(printer, img, density=args.density, batch_size=args.batch_size)
        tock("print")

    finally:
        await printer.disconnect()

    _timings["total_wall"] = time.monotonic() - t_start
    print_timings()


def cli():
    asyncio.run(main())


if __name__ == "__main__":
    cli()
