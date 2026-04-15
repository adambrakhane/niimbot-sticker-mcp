#!/usr/bin/env python3
"""Generate NiimbotPopup.app icon — a dark square with a white label sticker inside."""
import os
import sys
from PIL import Image, ImageDraw


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    # Dark rounded background
    bg_radius = int(s * 0.22)
    d.rounded_rectangle([(0, 0), (s - 1, s - 1)], radius=bg_radius, fill=(22, 22, 22, 255))

    # White label (landscape, centred)
    lw = int(s * 0.68)
    lh = int(s * 0.46)
    lx = (s - lw) // 2
    ly = (s - lh) // 2
    lr = max(2, int(s * 0.038))
    d.rounded_rectangle([(lx, ly), (lx + lw - 1, ly + lh - 1)], radius=lr, fill=(255, 255, 255, 255))

    # Black left sidebar — matches the ticket sticker template
    sw = int(lw * 0.21)
    d.rounded_rectangle([(lx, ly), (lx + sw, ly + lh - 1)], radius=lr, fill=(22, 22, 22, 255))
    # Square off the right side of the sidebar (keep left corners rounded)
    d.rectangle([(lx + lr, ly), (lx + sw, ly + lh - 1)], fill=(22, 22, 22, 255))

    # Three horizontal lines on the white area (suggests text / content)
    line_x0 = lx + sw + int(s * 0.04)
    line_x1 = lx + lw - int(s * 0.04)
    line_color = (180, 180, 180, 255)
    for i, frac in enumerate([0.32, 0.50, 0.68]):
        y = ly + int(lh * frac)
        w = 1 if size <= 32 else max(1, int(s * 0.012))
        # First line shorter (like a title)
        x1 = line_x1 if i > 0 else lx + sw + int((lw - sw) * 0.55)
        if size >= 32:
            d.rounded_rectangle([(line_x0, y - w), (x1, y + w)], radius=w, fill=line_color)

    return img


SIZES = [
    ("icon_16x16.png",       16),
    ("icon_16x16@2x.png",    32),
    ("icon_32x32.png",       32),
    ("icon_32x32@2x.png",    64),
    ("icon_128x128.png",    128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png",    256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png",    512),
    ("icon_512x512@2x.png",1024),
]


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "AppIcon.iconset"
    os.makedirs(out_dir, exist_ok=True)
    for filename, size in SIZES:
        img = draw_icon(size)
        path = os.path.join(out_dir, filename)
        img.save(path)
        print(f"  {path}")
    print(f"Done — {len(SIZES)} sizes written to {out_dir}")


if __name__ == "__main__":
    main()
