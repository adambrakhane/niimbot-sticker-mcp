import unittest
from unittest.mock import AsyncMock, patch

from niimbot.mcp.server import Category, preview_note, print_note


class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_note_returns_structured_payload(self):
        result = await preview_note(
            category=Category.ticket,
            title="Check API rate limits",
            body="before next deploy",
            project="niimbot",
            reference="OPS-17",
        )
        self.assertEqual(result["category"], "ticket")
        self.assertEqual(result["title"], "Check API rate limits")
        self.assertTrue(result["preview_png_base64"])

    async def test_print_note_returns_structured_success_payload(self):
        with patch("niimbot.mcp.server._daemon") as daemon:
            daemon.ensure_daemon = AsyncMock()
            daemon.print_image = AsyncMock(return_value={"status": "ok", "duration_ms": 3210})

            result = await print_note(category=Category.idea, title="Persistent BLE connection")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["duration_ms"], 3210)
        self.assertTrue(result["preview_png_base64"])

    async def test_print_note_returns_error_payload(self):
        with patch("niimbot.mcp.server._daemon") as daemon:
            daemon.ensure_daemon = AsyncMock()
            daemon.print_image = AsyncMock(return_value={"status": "error", "error": "printer offline"})

            result = await print_note(category=Category.urgent, title="Deploy broken")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "printer offline")
