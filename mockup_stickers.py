"""Render mockup PNGs of all 4 sticker categories.

Run: python mockup_stickers.py
Outputs:
  images/mockup_{name}_template.png  — field names shown
  images/mockup_{name}_example.png   — filled with sample data

Canvas: 568x350px = 40x30mm label @ 300 DPI.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import textwrap

W, H = 568, 350
PAD = 16
OUT = Path(__file__).parent / "images"
OUT.mkdir(exist_ok=True)

# Fonts
_FONT_CACHE = {}


def get_font(size, bold=False):
    key = (size, bold)
    if key not in _FONT_CACHE:
        idx = 1 if bold else 0
        try:
            _FONT_CACHE[key] = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size, index=idx)
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def get_mono(size):
    key = ("mono", size)
    if key not in _FONT_CACHE:
        try:
            _FONT_CACHE[key] = ImageFont.truetype("/System/Library/Fonts/Courier.ttc", size)
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def text_size(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


def fit_text(draw, text, font_func, max_w, max_size, min_size, bold=False, max_lines=3):
    """Find the largest font size where text wraps into max_lines within max_w.
    Scales font down before truncating. Returns (lines, font, line_height)."""
    for size in range(max_size, min_size - 1, -2):
        font = font_func(size, bold) if font_func != get_mono else get_mono(size)
        # Binary search for chars_per_line by measuring real pixel widths
        # Start generous, tighten until all lines fit
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            tw, _ = text_size(draw, test, font)
            if tw <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        if not lines:
            lines = [text]

        # Check: does it fit in max_lines?
        if len(lines) <= max_lines:
            # Verify each line actually fits (single long words)
            if all(text_size(draw, line, font)[0] <= max_w for line in lines):
                _, lh = text_size(draw, "Ag", font)
                return lines, font, lh

    # At min size, wrap and truncate if needed
    font = font_func(min_size, bold) if font_func != get_mono else get_mono(min_size)
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        tw, _ = text_size(draw, test, font)
        if tw <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    _, lh = text_size(draw, "Ag", font)
    return lines if lines else [text], font, lh


def draw_wrapped(draw, x, y, lines, font, lh, fill=0, max_lines=3):
    """Draw wrapped lines, truncating with ... if too many."""
    for i, line in enumerate(lines[:max_lines]):
        if i == max_lines - 1 and len(lines) > max_lines:
            line = line[:len(line) - 3] + "..."
        draw.text((x, y + i * (lh + 4)), line, fill=fill, font=font)
    return y + min(len(lines), max_lines) * (lh + 4)


def border_solid(draw, thickness):
    """Solid thick border — for URGENT."""
    t = thickness
    draw.rectangle([0, 0, W - 1, t - 1], fill=0)
    draw.rectangle([0, H - t, W - 1, H - 1], fill=0)
    draw.rectangle([0, 0, t - 1, H - 1], fill=0)
    draw.rectangle([W - t, 0, W - 1, H - 1], fill=0)


def border_single(draw):
    """Thin single border — for TICKET."""
    draw.rectangle([0, 0, W - 1, H - 1], outline=0, width=3)


def border_sunburst(draw):
    """Dashed rays from center — for BIG IDEA."""
    import math
    cx, cy = W // 2, H // 2
    num_rays = 48
    ray_len = max(W, H)  # long enough to reach edges
    for i in range(num_rays):
        angle = 2 * math.pi * i / num_rays
        ex = cx + int(ray_len * math.cos(angle))
        ey = cy + int(ray_len * math.sin(angle))
        # Draw dashed ray: alternate 8px on, 8px off
        steps = 60
        for s in range(0, steps, 2):  # every other segment
            t0 = s / steps
            t1 = min((s + 1) / steps, 1.0)
            x0 = int(cx + (ex - cx) * t0)
            y0 = int(cy + (ey - cy) * t0)
            x1 = int(cx + (ex - cx) * t1)
            y1 = int(cy + (ey - cy) * t1)
            draw.line([(x0, y0), (x1, y1)], fill=0, width=2)


# ─── RENDERERS ────────────────────────────────────────────

def render_urgent(title, body="", project="", reference=""):
    img = Image.new("1", (W, H), 1)
    draw = ImageDraw.Draw(img)

    # Bold thick border (12px) — the visual identity of URGENT
    border_solid(draw, 12)

    # "URGENT" tag tucked into top-left corner, overlapping the border
    tag_font = get_font(28, bold=True)
    tw, th = text_size(draw, "URGENT", tag_font)
    # Black rect in the corner
    draw.rectangle([0, 0, tw + 20, th + 12], fill=0)
    draw.text((8, 4), "URGENT", fill=1, font=tag_font)

    content_l = 12 + PAD
    content_r = W - 12 - PAD
    content_w = content_r - content_l

    # Title — starts right below the tag, big and bold
    y = th + 20
    lines, font, lh = fit_text(draw, title, get_font, content_w, 64, 36, bold=True)
    y = draw_wrapped(draw, content_l, y, lines, font, lh, max_lines=2)

    # Body
    if body:
        y += 8
        lines, font, lh = fit_text(draw, body, get_font, content_w, 44, 28)
        draw_wrapped(draw, content_l, y, lines, font, lh, max_lines=2)

    # Project bottom-left
    if project:
        pf = get_font(30)
        draw.text((content_l, H - 50), project.upper(), fill=0, font=pf)

    # Reference bottom-right
    if reference:
        rf = get_mono(28)
        rw, _ = text_size(draw, reference, rf)
        draw.text((content_r - rw, H - 50), reference, fill=0, font=rf)

    return img


def render_ticket(title, body="", project="", reference=""):
    img = Image.new("1", (W, H), 1)
    draw = ImageDraw.Draw(img)

    # Single-line border
    border_single(draw)

    # Project strip at top-left
    strip_h = 46
    draw.rectangle([3, 3, W - 4, strip_h], fill=0)
    if project:
        pf = get_font(30, bold=True)
        draw.text((12, 6), project.upper(), fill=1, font=pf)

    # Reference in top-right corner, overlapping border
    if reference:
        rf = get_mono(26)
        rw, rh = text_size(draw, reference, rf)
        # White box to clear the border, then draw text
        rx = W - rw - 12
        draw.rectangle([rx - 6, 0, W - 1, rh + 10], fill=1)
        draw.rectangle([rx - 6, 0, W - 1, rh + 10], outline=0, width=2)
        draw.text((rx, 3), reference, fill=0, font=rf)

    content_l = 3 + PAD
    content_r = W - 3 - PAD
    content_w = content_r - content_l

    # Title
    y = strip_h + 14
    lines, font, lh = fit_text(draw, title, get_font, content_w, 56, 36, bold=True)
    y = draw_wrapped(draw, content_l, y, lines, font, lh, max_lines=2)

    # Body
    if body:
        y += 8
        lines, font, lh = fit_text(draw, body, get_font, content_w, 40, 28)
        draw_wrapped(draw, content_l, y, lines, font, lh, max_lines=3)

    return img


def render_idea(title, body="", project="", reference=""):
    img = Image.new("1", (W, H), 1)
    draw = ImageDraw.Draw(img)

    # No border — airy

    content_w = W - PAD * 2

    # "IDEA" tag top-left, light
    tag_font = get_font(30)
    draw.text((PAD, 12), "IDEA", fill=0, font=tag_font)

    # Title centered, wrapped
    y = 70
    lines, font, lh = fit_text(draw, title, get_font, content_w, 56, 36, bold=True)
    for line in lines[:2]:
        lw, _ = text_size(draw, line, font)
        draw.text(((W - lw) // 2, y), line, fill=0, font=font)
        y += lh + 4

    # Body centered, wrapped
    if body:
        y += 8
        lines, font, lh = fit_text(draw, body, get_font, content_w, 40, 28)
        for line in lines[:2]:
            lw, _ = text_size(draw, line, font)
            draw.text(((W - lw) // 2, y), line, fill=0, font=font)
            y += lh + 4

    # Project bottom-right
    if project:
        pf = get_font(30)
        pw, _ = text_size(draw, project, pf)
        draw.text((W - pw - PAD, H - 46), project, fill=0, font=pf)

    return img


def render_big_idea(title, body="", project="", reference=""):
    img = Image.new("1", (W, H), 1)
    draw = ImageDraw.Draw(img)

    # Sunburst rays from center — the visual identity
    border_sunburst(draw)

    # White content area in the center (leave rays visible around edges)
    margin = 28
    draw.rectangle([margin, margin, W - 1 - margin, H - 1 - margin], fill=1)

    content_l = margin + PAD
    content_r = W - margin - PAD
    content_w = content_r - content_l

    # "BIG IDEA" tag centered at top
    tag_font = get_font(32, bold=True)
    tw, th = text_size(draw, "BIG IDEA", tag_font)
    draw.text(((W - tw) // 2, margin + 4), "BIG IDEA", fill=0, font=tag_font)

    # Rule
    y = margin + 4 + th + 8
    draw.rectangle([(content_l, y), (content_r, y + 3)], fill=0)
    y += 14

    # Title centered, wrapped
    lines, font, lh = fit_text(draw, title, get_font, content_w, 56, 36, bold=True)
    for line in lines[:2]:
        lw, _ = text_size(draw, line, font)
        draw.text(((W - lw) // 2, y), line, fill=0, font=font)
        y += lh + 4

    # Body centered, wrapped
    if body:
        y += 8
        lines, font, lh = fit_text(draw, body, get_font, content_w, 40, 28)
        for line in lines[:2]:
            lw, _ = text_size(draw, line, font)
            draw.text(((W - lw) // 2, y), line, fill=0, font=font)
            y += lh + 4

    # Bottom metadata centered
    bottom = " | ".join(filter(None, [project, reference]))
    if bottom:
        bf = get_font(28)
        bw, _ = text_size(draw, bottom, bf)
        draw.text(((W - bw) // 2, H - margin - 38), bottom, fill=0, font=bf)

    return img


# ─── DATA ─────────────────────────────────────────────────

templates = [
    ("urgent", render_urgent, "{title}", "{body}", "{project}", "{reference}"),
    ("ticket", render_ticket, "{title}", "{body}", "{project}", "{reference}"),
    ("idea", render_idea, "{title}", "{body}", "{project}", "{reference}"),
    ("big_idea", render_big_idea, "{title}", "{body}", "{project}", "{reference}"),
]

examples = [
    ("urgent", render_urgent,
     "Fix auth token expiry bug in prod",
     "Users getting logged out after 5 minutes, affecting all orgs",
     "niimbot", "AUTH-442"),
    ("ticket", render_ticket,
     "Add retry logic to BLE connection",
     "Connection drops on first attempt about 30% of the time",
     "niimbot", "NIIM-17"),
    ("idea", render_idea,
     "Persistent BLE daemon process",
     "Keep connection alive, skip 1.5s reconnect on every print",
     "niimbot", ""),
    ("big_idea", render_big_idea,
     "Unified label design system",
     "Reusable sticker templates for any project or team",
     "niimbot", "Q3 roadmap"),
]


if __name__ == "__main__":
    # Clean old mockups
    for old in OUT.glob("mockup_*.png"):
        old.unlink()

    for name, renderer, title, body, project, ref in templates:
        img = renderer(title, body, project, ref)
        path = OUT / f"mockup_{name}_template.png"
        img.save(path)
        print(f"Saved {path.name}")

    for name, renderer, title, body, project, ref in examples:
        img = renderer(title, body, project, ref)
        path = OUT / f"mockup_{name}_example.png"
        img.save(path)
        print(f"Saved {path.name}")
