"""niimbotd — background daemon that owns the BLE connection and accepts print jobs."""
import asyncio
import base64
import io
import json
import logging
import os
import signal
import time

from PIL import Image

from niimbot.daemon.connection import ConnectionManager
from niimbot.printing import print_image
from niimbot.labels import get_data_dir

log = logging.getLogger("niimbotd")

SOCKET_PATH = "/tmp/niimbotd.sock"


def get_pid_path():
    return get_data_dir() / ".niimbotd.pid"


class Daemon:
    def __init__(self):
        self.conn = ConnectionManager()
        self._shutdown_event = asyncio.Event()
        self._server = None
        self._start_time = time.monotonic()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle one client connection: read JSON line, dispatch, write response."""
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not line:
                return

            request = json.loads(line.decode())
            cmd = request.get("cmd", "")

            if cmd == "ping":
                response = {"status": "ok"}

            elif cmd == "status":
                response = {
                    "status": "ok",
                    "state": self.conn.state.value,
                    "printer_name": self.conn.printer_name,
                    "transport": self.conn.transport,
                    "power_level": self.conn.power_level,
                    "paper_state": self.conn.paper_state,
                    "uptime_s": int(time.monotonic() - self._start_time),
                }

            elif cmd == "print":
                response = await self._handle_print(request)

            else:
                response = {"status": "error", "error": f"Unknown command: {cmd}"}

            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()

        except asyncio.TimeoutError:
            log.warning("Client read timeout")
        except Exception as e:
            log.error(f"Client handler error: {e}", exc_info=True)
            try:
                writer.write(json.dumps({"status": "error", "error": str(e)}).encode() + b"\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_print(self, request: dict) -> dict:
        """Handle a print command."""
        t0 = time.monotonic()

        # Ensure connected
        connected = await self.conn.ensure_connected(timeout=15.0)
        if not connected:
            return {"status": "error", "error": "Printer not connected, connection attempt failed"}

        # Decode image
        image_b64 = request.get("image_b64", "")
        if not image_b64:
            return {"status": "error", "error": "Missing image_b64"}

        try:
            img_bytes = base64.b64decode(image_b64)
            img = Image.open(io.BytesIO(img_bytes))
        except Exception as e:
            return {"status": "error", "error": f"Invalid image: {e}"}

        density = request.get("density", 3)
        batch_size = request.get("batch_size", 32)

        # Print with lock
        async with self.conn.print_lock:
            try:
                await print_image(self.conn.printer, img, density=density, batch_size=batch_size)
            except Exception as e:
                log.error(f"Print failed: {e}", exc_info=True)
                return {"status": "error", "error": f"Print failed: {e}"}

        duration_ms = int((time.monotonic() - t0) * 1000)
        log.info(f"Print completed in {duration_ms}ms")
        return {"status": "ok", "duration_ms": duration_ms}

    async def run(self):
        """Main daemon entry point."""
        log.info("Starting niimbotd...")

        # Clean up stale socket
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)

        # Write PID file
        pid_path = get_pid_path()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))

        # Start connection manager
        await self.conn.start()

        # Start socket server
        self._server = await asyncio.start_unix_server(self.handle_client, path=SOCKET_PATH)
        log.info(f"Listening on {SOCKET_PATH}")

        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        # Wait for shutdown
        await self._shutdown_event.wait()
        log.info("Shutting down...")

        # Cleanup
        self._server.close()
        await self._server.wait_closed()
        await self.conn.stop()

        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        if pid_path.exists():
            pid_path.unlink()

        log.info("Stopped")


def main():
    """Run the daemon in the foreground."""
    logging.basicConfig(level=logging.INFO, format='%(name)s:%(levelname)s: %(message)s')
    logging.getLogger("bleak").setLevel(logging.WARNING)
    daemon = Daemon()
    asyncio.run(daemon.run())
