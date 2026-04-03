# NIIMBOT B1 Pro BLE Driver

Python driver for the NIIMBOT B1 Pro label printer, communicating over Bluetooth Low Energy (BLE). The end goal is an MCP server so Claude Code can print styled stickers from any project.

Based on protocol knowledge from the [niimprint](https://github.com/AndBondStyle/niimprint) and [niimblue](https://github.com/MultiMote/niimblue) projects.

## Setup

```
pip install -e .
```

Requires Python 3.10+, [bleak](https://github.com/hbldh/bleak), and [Pillow](https://python-pillow.org/).

## Project Structure

```
niimbot/
├── src/niimbot/
│   ├── ble.py           Core BLE library (NiimbotBLE, protocol, connection caching)
│   ├── printing.py      Consolidated print logic (one copy, used by all tools)
│   ├── labels.py        Label database and data path resolution
│   ├── tools/
│   │   ├── fast_print.py    Fast non-interactive printing with timing
│   │   ├── calibrate.py     Interactive label size calibration
│   │   └── test_combos.py   Dev tool for exploring printer parameters
│   └── mcp/                 MCP server (not yet implemented)
├── data/
│   ├── label_db.json    Calibrated label dimensions (keyed by RFID barcode)
│   └── .ble_cache.json  Cached BLE address (auto-generated, gitignored)
├── docs/
│   ├── RESEARCH.md      Protocol research notes
│   ├── printer_specs.md Hardware and protocol specs
│   └── mcp_server_spec.md  MCP server design spec
└── pyproject.toml
```

## Tools

### Fast printing

```
python -m niimbot.tools.fast_print                       # print a test image
python -m niimbot.tools.fast_print photo.png             # print an image file
python -m niimbot.tools.fast_print --density 5 photo.png # darker print
```

Non-interactive. Reads RFID to look up calibrated dimensions from `data/label_db.json`, prints with a timing breakdown. Typical total time ~7s.

### Label calibration

```
python -m niimbot.tools.calibrate
```

Interactive workflow for calibrating the printable area of a new label roll. Reads RFID barcode, estimates dimensions, prints test images with a bottom ruler, and saves confirmed dimensions to `data/label_db.json`.

### Dev/test

```
python -m niimbot.tools.test_combos
```

Queries all printer info types and runs test prints at configurable heights. Developer tool for exploring printer capabilities.

## Python API

```python
import asyncio
from niimbot import NiimbotBLE, print_image, load_label_db

async def main():
    db = load_label_db()
    printer = NiimbotBLE()
    await printer.connect()

    rfid = await printer.get_rfid()
    barcode = rfid.get("barcode", "")
    label = db["labels"].get(barcode, {})

    from PIL import Image
    img = Image.open("my_label.png")
    await print_image(printer, img, density=3, batch_size=32)

    await printer.disconnect()

asyncio.run(main())
```

## BLE Cache

On first connection, `niimbot.ble` scans for a BLE device with "b1" or "niim" in its name. Once found, the address is saved to `data/.ble_cache.json`. Subsequent connections skip the scan (~10s savings). Delete the cache file to force a fresh scan.

## What's Next

The MCP server (`docs/mcp_server_spec.md`) — a `print_sticker` tool that Claude Code can call from any project to print styled stickers in 4 categories: urgent, ticket, idea, big_idea.
