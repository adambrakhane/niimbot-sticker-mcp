"""Thin client for communicating with niimbotd over Unix socket."""
import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import time

from PIL import Image

log = logging.getLogger("niimbot.daemon.client")

SOCKET_PATH = "/tmp/niimbotd.sock"


async def _send_command(cmd: dict, timeout: float = 30.0) -> dict:
    """Send a JSON command to niimbotd and return the response."""
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    try:
        writer.write(json.dumps(cmd).encode() + b"\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        return json.loads(line.decode())
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


class DaemonClient:
    """Client for the niimbotd background daemon."""

    async def ensure_daemon(self, timeout: float = 10.0):
        """Make sure the daemon is running. Start it if not."""
        # Check if socket exists and daemon responds
        if os.path.exists(SOCKET_PATH):
            try:
                result = await _send_command({"cmd": "ping"}, timeout=2.0)
                if result.get("status") == "ok":
                    return  # Daemon is running
            except Exception:
                pass  # Socket exists but daemon is dead

        # Start the daemon
        log.info("Starting niimbotd...")
        subprocess.Popen(
            ["python", "-m", "niimbot.daemon.server"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        )

        # Wait for socket to appear
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(SOCKET_PATH):
                try:
                    result = await _send_command({"cmd": "ping"}, timeout=2.0)
                    if result.get("status") == "ok":
                        log.info("niimbotd started")
                        return
                except Exception:
                    pass
            await asyncio.sleep(0.3)

        raise RuntimeError(f"Failed to start niimbotd within {timeout}s")

    async def print_image(self, img: Image.Image, density: int = 3, batch_size: int = 32) -> dict:
        """Send a print job to the daemon."""
        # Encode image as base64 PNG
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        return await _send_command({
            "cmd": "print",
            "image_b64": image_b64,
            "density": density,
            "batch_size": batch_size,
        }, timeout=30.0)

    async def status(self) -> dict:
        """Get daemon status."""
        return await _send_command({"cmd": "status"}, timeout=5.0)
