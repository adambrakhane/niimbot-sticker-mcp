"""NIIMBOT sticker printer MCP server.

Exposes a `print_note` tool that renders and prints styled stickers
on a NIIMBOT B1 Pro label printer via BLE.

Printing is handled by the niimbotd background daemon (persistent BLE connection).
The daemon is auto-started if not already running.

Run: python -m niimbot.mcp.server
"""
import base64
import io
import logging
from enum import Enum
from typing import Optional

from mcp.server.fastmcp import FastMCP

from niimbot.mcp.renderer import render_sticker
from niimbot.daemon.client import DaemonClient

logging.basicConfig(level=logging.INFO, format='%(name)s:%(levelname)s: %(message)s')
logging.getLogger("bleak").setLevel(logging.WARNING)
log = logging.getLogger("niimbot.mcp")

server = FastMCP("niimbot-sticker-printer")
_daemon = DaemonClient()


def _image_to_base64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class Category(str, Enum):
    urgent = "urgent"
    ticket = "ticket"
    idea = "idea"
    big_idea = "big_idea"


@server.tool()
async def print_note(
    category: Category,
    title: str,
    body: Optional[str] = None,
    project: Optional[str] = None,
    reference: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    """PHYSICALLY PRINT a paper sticker/note on a thermal label printer connected via Bluetooth.

    This prints a real physical sticky note on the NIIMBOT B1 Pro label printer.
    Use this whenever the user says "print a note", "print a sticker", "print a reminder",
    "make me a label", or wants something physically printed on paper.

    Categories:
    - urgent: White-on-black inverted sticker. For critical/blocking issues.
    - ticket: Sidebar layout with project name. For work items and tasks.
    - idea: Post-it style with lightbulb. For thoughts and suggestions.
    - big_idea: Sunburst border pattern. For vision items and big plans.

    Only title and category are required. Infer project from the current repo/directory.
    Include reference only if a ticket ID or file path is naturally available.
    Use body for extra context only when it adds value — short titles can stand alone.
    """
    img = render_sticker(
        category=category.value,
        title=title,
        body=body or "",
        project=project or "",
        reference=reference or "",
    )

    preview_b64 = _image_to_base64(img)

    if dry_run:
        return f"Preview generated (dry_run=true, not printed).\n\n![sticker preview](data:image/png;base64,{preview_b64})"

    try:
        await _daemon.ensure_daemon()
        result = await _daemon.print_image(img, density=3, batch_size=32)

        if result.get("status") == "ok":
            ms = result.get("duration_ms", "?")
            return f"Printed in {ms}ms.\n\n![sticker preview](data:image/png;base64,{preview_b64})"
        else:
            error = result.get("error", "unknown error")
            return f"Print failed: {error}\n\n![sticker preview](data:image/png;base64,{preview_b64})"

    except Exception as e:
        log.error(f"Print failed: {e}", exc_info=True)
        return f"Print failed: {e}\n\nPreview was:\n![sticker preview](data:image/png;base64,{preview_b64})"


def main():
    server.run()


if __name__ == "__main__":
    main()
