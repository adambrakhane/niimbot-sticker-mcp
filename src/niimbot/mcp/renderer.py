"""Sticker renderer — generates 568x350px 1-bit images for the NIIMBOT B1 Pro.

Four categories, each with a distinct visual identity:
  - urgent:   Full invert (white on black)
  - ticket:   Black sidebar with vertical project name
  - idea:     Post-it with lightbulb icon
  - big_idea: Sunburst rays from center
"""
import math
from PIL import Image, ImageDraw, ImageFont

W, H = 568, 350
PAD = 16

_FONT_CACHE = {}


def _get_font(size, bold=False):
    key = (size, bold)
    if key not in _FONT_CACHE:
        idx = 1 if bold else 0
        try:
            _FONT_CACHE[key] = ImageFont.truetype(
                "/System/Library/Fonts/Helvetica.ttc", size, index=idx)
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def _get_mono(size):
    key = ("mono", size)
    if key not in _FONT_CACHE:
        try:
            _FONT_CACHE[key] = ImageFont.truetype(
                "/System/Library/Fonts/Courier.ttc", size)
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def _text_size(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


def _wrap_text(draw, text, font, max_w):
    """Word-wrap text to fit within max_w pixels. Returns list of lines."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        if _text_size(draw, test, font)[0] <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [text]


def _fit_text(draw, text, max_w, max_size, min_size, bold=False, max_lines=3):
    """Find the largest font size where text wraps into max_lines within max_w.
    Keeps shrinking until text fits — never truncates."""
    # Try preferred range first
    for size in range(max_size, min_size - 1, -2):
        font = _get_font(size, bold)
        lines = _wrap_text(draw, text, font, max_w)
        if len(lines) <= max_lines:
            if all(_text_size(draw, l, font)[0] <= max_w for l in lines):
                _, lh = _text_size(draw, "Ag", font)
                return lines, font, lh

    # Below min_size: keep shrinking until it fits (hard floor at 18px)
    for size in range(min_size - 2, 16, -2):
        font = _get_font(size, bold)
        lines = _wrap_text(draw, text, font, max_w)
        if len(lines) <= max_lines:
            if all(_text_size(draw, l, font)[0] <= max_w for l in lines):
                _, lh = _text_size(draw, "Ag", font)
                return lines, font, lh

    # Last resort: smallest font, allow as many lines as needed
    font = _get_font(18, bold)
    lines = _wrap_text(draw, text, font, max_w)
    _, lh = _text_size(draw, "Ag", font)
    return lines, font, lh


def _draw_lines(draw, x, y, lines, font, lh, fill=0):
    """Draw wrapped lines."""
    for line in lines:
        draw.text((x, y), line, fill=fill, font=font)
        y += lh + 4
    return y


def _draw_lines_centered(draw, y, lines, font, lh, fill=0):
    for line in lines:
        lw, _ = _text_size(draw, line, font)
        draw.text(((W - lw) // 2, y), line, fill=fill, font=font)
        y += lh + 4
    return y


# ─── URGENT: Full invert (white on black) ────────────────

def _render_urgent(title, body="", project="", reference=""):
    img = Image.new("1", (W, H), 0)  # black background
    draw = ImageDraw.Draw(img)

    # Thin white inset border
    draw.rectangle([4, 4, W - 5, H - 5], outline=1, width=2)

    # URGENT tag top-left
    tag_font = _get_font(26, bold=True)
    draw.text((12, 8), "URGENT", fill=1, font=tag_font)
    _, th = _text_size(draw, "URGENT", tag_font)

    cl, cr = 12, W - 12
    cw = cr - cl
    y = 8 + th + 14

    # Title
    lines, font, lh = _fit_text(draw, title, cw, 60, 36, bold=True)
    y = _draw_lines(draw, cl, y, lines, font, lh, fill=1)

    # Body
    if body:
        y += 4
        lines, font, lh = _fit_text(draw, body, cw, 42, 28)
        _draw_lines(draw, cl, y, lines, font, lh, fill=1)

    # Project bottom-left
    if project:
        draw.text((cl, H - 46), project.upper(), fill=1, font=_get_font(28))

    # Reference bottom-right
    if reference:
        rf = _get_mono(26)
        rw, _ = _text_size(draw, reference, rf)
        draw.text((cr - rw, H - 46), reference, fill=1, font=rf)

    return img


# ─── TICKET: Sidebar with vertical project name ──────────

def _render_ticket(title, body="", project="", reference=""):
    img = Image.new("1", (W, H), 1)
    draw = ImageDraw.Draw(img)

    # Black sidebar on left
    sidebar_w = 48
    draw.rectangle([0, 0, sidebar_w, H - 1], fill=0)

    # Project name stacked vertically in sidebar
    if project:
        pf = _get_font(22, bold=True)
        for i, ch in enumerate(project.upper()):
            chw, _ = _text_size(draw, ch, pf)
            draw.text((sidebar_w // 2 - chw // 2, 12 + i * 26), ch, fill=1, font=pf)

    cl = sidebar_w + PAD
    cr = W - PAD
    cw = cr - cl
    y = 12

    # Title
    lines, font, lh = _fit_text(draw, title, cw, 56, 36, bold=True)
    y = _draw_lines(draw, cl, y, lines, font, lh)

    # Body
    if body:
        y += 8
        lines, font, lh = _fit_text(draw, body, cw, 40, 28)
        _draw_lines(draw, cl, y, lines, font, lh)

    # Reference bottom-right
    if reference:
        rf = _get_mono(28)
        rw, _ = _text_size(draw, reference, rf)
        draw.text((cr - rw, H - 44), reference, fill=0, font=rf)

    return img


# ─── IDEA: Post-it with lightbulb ────────────────────────

def _render_idea(title, body="", project="", reference=""):
    img = Image.new("1", (W, H), 1)
    draw = ImageDraw.Draw(img)

    # Light border like a sticky note
    draw.rectangle([0, 0, W - 1, H - 1], outline=0, width=2)

    # Lightbulb in top-right corner
    bx, by = W - 46, 30
    br = 20
    draw.ellipse([bx - br, by - br, bx + br, by + br], outline=0, width=3)
    for angle in [-70, -35, 0, 35, 70]:
        rad = math.radians(angle - 90)
        ix = bx + int((br - 4) * math.cos(rad))
        iy = by + int((br - 4) * math.sin(rad))
        ox = bx + int((br + 10) * math.cos(rad))
        oy = by + int((br + 10) * math.sin(rad))
        draw.line([(ix, iy), (ox, oy)], fill=0, width=2)
    draw.rectangle([bx - 10, by + br, bx + 10, by + br + 10], outline=0, width=2)
    draw.line([(bx - 8, by + br + 4), (bx + 8, by + br + 4)], fill=0, width=2)
    draw.line([(bx - 8, by + br + 8), (bx + 8, by + br + 8)], fill=0, width=2)

    # "IDEA" top-left
    draw.text((PAD, 8), "IDEA", fill=0, font=_get_font(28))

    cw = W - PAD * 2
    y = 52

    # Title
    lines, font, lh = _fit_text(draw, title, cw, 56, 36, bold=True)
    y = _draw_lines(draw, PAD, y, lines, font, lh)

    # Body
    if body:
        y += 8
        lines, font, lh = _fit_text(draw, body, cw, 40, 28)
        _draw_lines(draw, PAD, y, lines, font, lh)

    # Project bottom-right
    if project:
        pf = _get_font(28)
        pw, _ = _text_size(draw, project, pf)
        draw.text((W - pw - PAD, H - 44), project, fill=0, font=pf)

    return img


# ─── BIG IDEA: Sunburst rays ─────────────────────────────

def _render_big_idea(title, body="", project="", reference=""):
    img = Image.new("1", (W, H), 1)
    draw = ImageDraw.Draw(img)

    # Sunburst rays from center
    cx, cy = W // 2, H // 2
    num_rays = 48
    ray_len = max(W, H)
    for i in range(num_rays):
        angle = 2 * math.pi * i / num_rays
        ex = cx + int(ray_len * math.cos(angle))
        ey = cy + int(ray_len * math.sin(angle))
        steps = 60
        for s in range(0, steps, 2):
            t0 = s / steps
            t1 = min((s + 1) / steps, 1.0)
            x0 = int(cx + (ex - cx) * t0)
            y0 = int(cy + (ey - cy) * t0)
            x1 = int(cx + (ex - cx) * t1)
            y1 = int(cy + (ey - cy) * t1)
            draw.line([(x0, y0), (x1, y1)], fill=0, width=2)

    # White content box over the rays
    margin = 28
    draw.rectangle([margin, margin, W - 1 - margin, H - 1 - margin], fill=1)

    content_l = margin + PAD
    content_r = W - margin - PAD
    content_w = content_r - content_l

    # "BIG IDEA" tag centered
    tag_font = _get_font(32, bold=True)
    tw, th = _text_size(draw, "BIG IDEA", tag_font)
    draw.text(((W - tw) // 2, margin + 4), "BIG IDEA", fill=0, font=tag_font)

    # Rule
    y = margin + 4 + th + 8
    draw.rectangle([(content_l, y), (content_r, y + 3)], fill=0)
    y += 14

    # Title centered
    lines, font, lh = _fit_text(draw, title, content_w, 56, 36, bold=True)
    y = _draw_lines_centered(draw, y, lines, font, lh)

    # Body centered
    if body:
        y += 8
        lines, font, lh = _fit_text(draw, body, content_w, 40, 28)
        _draw_lines_centered(draw, y, lines, font, lh)

    # Bottom metadata centered
    bottom = " | ".join(filter(None, [project, reference]))
    if bottom:
        bf = _get_font(28)
        bw, _ = _text_size(draw, bottom, bf)
        draw.text(((W - bw) // 2, H - margin - 38), bottom, fill=0, font=bf)

    return img


# ─── Public API ───────────────────────────────────────────

RENDERERS = {
    "urgent": _render_urgent,
    "ticket": _render_ticket,
    "idea": _render_idea,
    "big_idea": _render_big_idea,
}


def render_sticker(category: str, title: str, body: str = "",
                   project: str = "", reference: str = "") -> Image.Image:
    """Render a sticker image for the given category.

    Args:
        category: One of "urgent", "ticket", "idea", "big_idea".
        title: Main text (required).
        body: Additional detail (optional).
        project: Project name (optional, inferred from cwd by caller).
        reference: Ticket ID, file path, etc. (optional).

    Returns:
        PIL Image, mode "1", 568x350px.
    """
    renderer = RENDERERS.get(category)
    if renderer is None:
        raise ValueError(f"Unknown category '{category}'. Must be one of: {list(RENDERERS.keys())}")
    return renderer(title, body=body, project=project, reference=reference)
