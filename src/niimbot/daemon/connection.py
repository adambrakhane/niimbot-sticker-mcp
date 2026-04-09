"""Connection manager with state machine, heartbeat, and auto-reconnect.

Supports two transports:
  - USB (preferred when a B1 Pro is on the bus)
  - BLE (fallback when USB is absent)

Switching rules:
  - On each reconnect, re-probe USB first.
  - If currently on BLE and USB appears, swap to USB — but never during a print
    (the print lock guards the swap).
"""
import asyncio
import enum
import logging
import time

from bleak import BleakScanner

from niimbot.ble import NiimbotBLE
from niimbot.usb import NiimbotUSB, find_device as usb_find_device
from niimbot.labels import get_ble_cache_path

log = logging.getLogger("niimbotd.conn")

# Reconnect backoff schedule (seconds)
BACKOFF = [0, 5, 15, 45, 120, 300]  # then cap at 300
MAX_RETRIES = 20
HEARTBEAT_INTERVAL = 30  # seconds
# How often to re-probe USB while connected over BLE (so we can hot-swap
# when the cable gets plugged in)
USB_PROBE_INTERVAL = 5  # seconds


class State(enum.Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    WAIT_RETRY = "wait_retry"


class ConnectionManager:
    """Manages a persistent connection to the NIIMBOT printer (USB preferred, BLE fallback)."""

    def __init__(self):
        self.state = State.IDLE
        self.printer: NiimbotBLE | NiimbotUSB | None = None
        self.printer_name: str = ""
        self.transport: str = ""  # "USB" or "BLE" or ""
        self.power_level: int = 0
        self.paper_state: int = 0
        self._retry_count = 0
        self._keepalive_task: asyncio.Task | None = None
        self._reconnect_event = asyncio.Event()
        self._shutdown = False
        self._print_lock = asyncio.Lock()

    def _on_disconnect(self, client):
        """Called by bleak / USB transport when the connection drops."""
        log.warning(f"{self.transport or 'transport'} disconnect detected")
        if not self._shutdown:
            self.state = State.RECONNECTING
            self._retry_count = 0
            self._reconnect_event.set()

    async def start(self):
        """Start the connection manager — attempt initial connection and start keepalive."""
        self._shutdown = False
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        # Trigger initial connection
        self._reconnect_event.set()

    async def stop(self):
        """Clean shutdown."""
        self._shutdown = True
        self._reconnect_event.set()  # wake up any waits
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        if self.printer:
            try:
                await self.printer.disconnect()
            except Exception:
                pass
            self.printer = None
        self.transport = ""
        self.state = State.IDLE

    async def ensure_connected(self, timeout: float = 15.0) -> bool:
        """Ensure we're connected. If not, trigger connection and wait.
        Called before every print job."""
        if self.state == State.CONNECTED and self.printer and self.printer.is_connected:
            return True

        # Trigger reconnection
        log.info("Not connected, triggering connection attempt...")
        self._retry_count = 0
        self._reconnect_event.set()

        # Wait for connection
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.state == State.CONNECTED:
                return True
            await asyncio.sleep(0.2)

        log.error(f"Failed to connect within {timeout}s")
        return False

    @property
    def print_lock(self) -> asyncio.Lock:
        return self._print_lock

    async def _try_connect(self) -> bool:
        """Attempt one connection. USB preferred, BLE fallback. Returns True on success."""
        self.state = State.SCANNING
        log.info(f"Connecting (attempt {self._retry_count + 1})...")

        # 1. Try USB first if a B1 Pro is on the bus
        if await asyncio.to_thread(usb_find_device):
            log.info("USB device detected, trying USB transport")
            if await self._connect_usb():
                return True
            log.warning("USB connect failed, falling back to BLE")

        # 2. BLE fallback
        return await self._connect_ble()

    async def _connect_usb(self) -> bool:
        printer = NiimbotUSB(disconnected_callback=self._on_disconnect)
        try:
            await printer.connect(connect_timeout=5.0)
            hb = await printer.heartbeat()
            self.power_level = hb.get("powerlevel", 0)
            self.paper_state = hb.get("paperstate", 0)

            rfid = await printer.get_rfid()
            if rfid and rfid.get("has_rfid"):
                log.info(f"Label: barcode={rfid.get('barcode', '?')}")

            self.printer = printer
            self.printer_name = "B1 Pro"
            self.transport = "USB"
            self.state = State.CONNECTED
            self._retry_count = 0
            log.info(f"Connected via USB! Battery: {self.power_level}%")
            return True
        except Exception as e:
            log.warning(f"USB connection failed: {e}")
            try:
                await printer.disconnect()
            except Exception:
                pass
            return False

    async def _connect_ble(self) -> bool:
        printer = NiimbotBLE(disconnected_callback=self._on_disconnect)
        try:
            # Try cached address first (fast: ~1.5s)
            cache_path = get_ble_cache_path()
            address = None
            if cache_path.exists():
                import json
                try:
                    cached = json.loads(cache_path.read_text())
                    address = cached.get("address")
                    name = cached.get("name", "?")
                    log.info(f"Trying cached address: {address} ({name})")
                except Exception:
                    pass

            if address:
                device = await BleakScanner.find_device_by_address(address, timeout=5.0)
                if device is None:
                    log.info("Cached device not found, trying full scan...")
                    address = None

            await printer.connect(address=address, connect_timeout=5.0)

            hb = await printer.heartbeat()
            self.power_level = hb.get("powerlevel", 0)
            self.paper_state = hb.get("paperstate", 0)

            rfid = await printer.get_rfid()
            if rfid and rfid.get("has_rfid"):
                log.info(f"Label: barcode={rfid.get('barcode', '?')}")

            self.printer = printer
            self.printer_name = getattr(printer.client, '_device_path', '') or "B1 Pro"
            self.transport = "BLE"
            self.state = State.CONNECTED
            self._retry_count = 0
            log.info(f"Connected via BLE! Battery: {self.power_level}%")
            return True

        except Exception as e:
            log.warning(f"BLE connection failed: {e}")
            try:
                await printer.disconnect()
            except Exception:
                pass
            return False

    async def _maybe_swap_to_usb(self):
        """If we're on BLE and a USB device has appeared, disconnect BLE and
        reconnect over USB. The print lock ensures this never happens mid-job.
        """
        if self.transport != "BLE":
            return
        if not await asyncio.to_thread(usb_find_device):
            return

        # Grab the print lock so we don't interrupt an active print.
        # Non-blocking: if a print is in progress, skip this cycle and try again later.
        if self._print_lock.locked():
            return
        async with self._print_lock:
            log.info("USB device appeared — swapping from BLE to USB")
            try:
                if self.printer:
                    await self.printer.disconnect()
            except Exception as e:
                log.debug(f"BLE disconnect during swap: {e}")
            self.printer = None
            self.transport = ""
            if not await self._connect_usb():
                log.warning("USB swap failed, attempting to reconnect BLE")
                await self._connect_ble()

    async def _keepalive_loop(self):
        """Background loop: heartbeat when connected, reconnect when not,
        and probe for USB hot-plug while connected on BLE."""
        while not self._shutdown:
            try:
                if self.state == State.CONNECTED:
                    # Short cycles so USB hot-plug is noticed quickly.
                    # Heartbeat only fires every HEARTBEAT_INTERVAL seconds.
                    elapsed = 0
                    while elapsed < HEARTBEAT_INTERVAL and not self._shutdown:
                        await asyncio.sleep(USB_PROBE_INTERVAL)
                        elapsed += USB_PROBE_INTERVAL
                        if self._shutdown:
                            break
                        # While on BLE, watch for USB cable being plugged in
                        if self.transport == "BLE":
                            await self._maybe_swap_to_usb()
                            if self.state != State.CONNECTED:
                                break

                    if self._shutdown or self.state != State.CONNECTED:
                        continue

                    if self.printer and self.printer.is_connected:
                        try:
                            hb = await self.printer.heartbeat()
                            self.power_level = hb.get("powerlevel", 0)
                            self.paper_state = hb.get("paperstate", 0)
                            log.debug(f"Heartbeat OK via {self.transport} (battery={self.power_level}%)")
                        except Exception as e:
                            log.warning(f"Heartbeat failed: {e}")
                            self.state = State.RECONNECTING
                            self._retry_count = 0
                    else:
                        self.state = State.RECONNECTING
                        self._retry_count = 0

                elif self.state in (State.IDLE, State.RECONNECTING, State.SCANNING):
                    if self.state == State.IDLE:
                        # In IDLE, wait for a trigger (print job, startup, or explicit request)
                        if not self._reconnect_event.is_set():
                            await self._reconnect_event.wait()
                        self._reconnect_event.clear()
                        if self._shutdown:
                            break

                    # Try to connect
                    success = await self._try_connect()
                    if not success:
                        self._retry_count += 1
                        if self._retry_count >= MAX_RETRIES:
                            log.warning(f"Max retries ({MAX_RETRIES}) reached, going idle")
                            self.state = State.IDLE
                        else:
                            # Exponential backoff
                            delay = BACKOFF[min(self._retry_count, len(BACKOFF) - 1)]
                            log.info(f"Retry {self._retry_count}/{MAX_RETRIES} in {delay}s...")
                            self.state = State.WAIT_RETRY
                            try:
                                await asyncio.wait_for(self._reconnect_event.wait(), timeout=delay)
                                self._reconnect_event.clear()
                                # Event was set — either a print job or shutdown
                            except asyncio.TimeoutError:
                                pass  # Backoff expired, retry
                            self.state = State.RECONNECTING

                elif self.state == State.WAIT_RETRY:
                    # Shouldn't normally land here, but handle gracefully
                    self.state = State.RECONNECTING

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Keepalive loop error: {e}", exc_info=True)
                await asyncio.sleep(5)
