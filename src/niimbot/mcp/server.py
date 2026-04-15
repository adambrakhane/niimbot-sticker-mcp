"""NIIMBOT sticker printer MCP server.

Exposes structured sticker preview and print tools for the NIIMBOT B1 Pro.

Printing is handled by the niimbotd background daemon (persistent BLE connection).
The daemon is auto-started if not already running.

Run: python -m niimbot.mcp.server
"""
import base64
import io
import logging
from enum import Enum
from typing import Any, Optional

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


def _render_preview_payload(
    category: Category,
    title: str,
    body: Optional[str] = None,
    project: Optional[str] = None,
    reference: Optional[str] = None,
) -> dict[str, Any]:
    img = render_sticker(
        category=category.value,
        title=title,
        body=body or "",
        project=project or "",
        reference=reference or "",
    )
    return {
        "category": category.value,
        "title": title,
        "body": body or "",
        "project": project or "",
        "reference": reference or "",
        "preview_png_base64": _image_to_base64(img),
    }, img


@server.tool()
async def preview_note(
    category: Category,
    title: str,
    body: Optional[str] = None,
    project: Optional[str] = None,
    reference: Optional[str] = None,
) -> dict[str, Any]:
    """Generate a preview for a sticker without printing it."""
    payload, _ = _render_preview_payload(category, title, body, project, reference)
    return payload


@server.tool()
async def print_note(
    category: Category,
    title: str,
    body: Optional[str] = None,
    project: Optional[str] = None,
    reference: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
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
    preview_payload, img = _render_preview_payload(category, title, body, project, reference)

    if dry_run:
        return {
            "status": "preview",
            "dry_run": True,
            "message": "Preview generated (dry_run=true, not printed).",
            **preview_payload,
        }

    try:
        await _daemon.ensure_daemon()
        result = await _daemon.print_image(img, density=3, batch_size=32)

        if result.get("status") == "ok":
            ms = result.get("duration_ms", "?")
            return {
                "status": "ok",
                "duration_ms": ms,
                "message": f"Printed in {ms}ms.",
                **preview_payload,
            }

        error = result.get("error", "unknown error")
        return {
            "status": "error",
            "error": error,
            "message": f"Print failed: {error}",
            **preview_payload,
        }

    except Exception as e:
        log.error(f"Print failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "message": f"Print failed: {e}",
            **preview_payload,
        }


def main():
    server.run()


if __name__ == "__main__":
    main()
