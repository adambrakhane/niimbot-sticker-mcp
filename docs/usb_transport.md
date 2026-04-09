# USB Transport — status & known issue

## Summary

The B1 Pro supports printing over USB. The full transport layer, protocol
handshake, and print flow are implemented in `src/niimbot/usb.py` and wired
into the daemon in `src/niimbot/daemon/connection.py`. **The code is known
to work end-to-end** — during development we printed a full 568×350 ticket
template over USB successfully.

However, there is a macOS-specific kernel-driver-ownership problem that
currently prevents the daemon from claiming the USB printer interface in
most sessions. Until that's resolved, the daemon falls back to BLE, which
works fine.

## How the USB transport works (when it works)

- **Device**: NIIMBOT B1 Pro, `idVendor=0x3513`, `idProduct=0x0002`
- **Target interface**: interface 2, bulk OUT `0x03`, bulk IN `0x87`, max
  packet 64 bytes. This is the **USB Printer Class** interface.
- The device also exposes a CDC ACM serial port at `/dev/cu.B1Pro-*`
  (interfaces 0+1). **Do not use it.** The firmware accepts bytes on that
  endpoint but silently drops them — Niimbot protocol commands never reach
  the printer controller. This was verified empirically; see the debug log
  section below.
- Protocol framing is byte-for-byte identical to BLE: same `NiimbotPacket`
  class, same command codes, same payload layouts. The only wire-level
  difference is that the `Connect` (0xc1) packet must be prefixed with a
  literal `0x03` byte before the `\x55\x55...\xaa\xaa` frame. (This matches
  niimbluelib's behavior.)
- USB bulk is ~3× faster than BLE — a 350-row full label sends in ~0.76 s
  vs ~2.5 s over BLE.
- USB does **not** wake a soft-off printer. The Niimbot protocol has no
  wake command (verified against niimbluelib's full command map). The
  printer's main MCU is asleep when soft-off; the USB chip enumerates and
  responds to control requests (e.g., `GET_DEVICE_ID`), but Niimbot protocol
  bulk commands get no response. The user must press the physical power
  button (hold 3 s) to wake the MCU.

## Known issue: macOS kernel driver ownership

### Symptom

`usb.util.claim_interface(dev, 2)` fails with:

    [Errno 13] Access denied (insufficient permissions)

This happens **even when running as the same user that can write to the
CDC ACM port**, and even when no other process has the device open. The
error is coming from macOS's IOKit, not from file permissions.

### Root cause

The B1 Pro identifies itself as a USB composite device via IAD (Interface
Association Descriptor):

    bDeviceClass    = 0xEF  (Miscellaneous)
    bDeviceSubClass = 2     (Common Class)
    bDeviceProtocol = 1     (Interface Association)

Inside the composite device there are three interfaces:

    Interface 0: CDC Communication (class 0x02, subclass 2, protocol 1)
    Interface 1: CDC Data          (class 0x0A)
    Interface 2: USB Printer       (class 0x07, subclass 1, protocol 2)

macOS's `AppleUSBCDCCompositeDevice` driver matches the IAD top-level
descriptors and claims the entire composite function — **including
interface 2**, even though it only actively uses 0 and 1. Once the
composite driver has bound the interface group, unprivileged user-space
code (libusb / pyusb) cannot claim any of those interfaces without first
detaching the kernel driver, and on macOS `detach_kernel_driver` requires
elevated privileges.

Evidence from `ioreg -c IOUSBHostInterface -l`:

    +-o IOUSBHostDevice (B1 Pro-I116030475)
      |   IOClass = "AppleUSBCDCCompositeDevice"
      +-o IOUSBHostInterface@0  bInterfaceNumber=0  bInterfaceClass=2
      |     IOClass = "AppleUSBACMControl"
      +-o IOUSBHostInterface@1  bInterfaceNumber=1  bInterfaceClass=10
      |     IOClass = "AppleUSBACMData"
      |       IOClass = "IOSerialBSDClient"   (creates /dev/cu.B1Pro-*)
      +-o IOUSBHostInterface@2  bInterfaceNumber=2  bInterfaceClass=7
            (no user-space driver, but owned by composite)

pyusb reports the following on an affected session:

    iface 0 kernel driver active: True
    iface 1 kernel driver active: True
    iface 2 kernel driver active: True
    iface 0 detach: [Errno 13] Access denied (insufficient permissions)
    iface 2 detach: [Errno 13] Access denied (insufficient permissions)
    claim iface 2: [Errno 13] Access denied (insufficient permissions)

Interestingly, **interface 1 can sometimes be claimed** even though it's
driven by `AppleUSBACMData`, while iface 2 cannot — IOKit's ownership rules
for composite devices are inconsistent.

### Why it worked during development

During the initial USB exploration in this same session we successfully:

1. Enumerated the device
2. Claimed interface 2
3. Sent `CONNECT`, `HEARTBEAT`, printed a 200×96 test image
4. Printed a full 568×350 ticket template

This happened before I unplugged the device and plugged it back in during
a later debugging step. The most likely explanation is that the driver
binding state differs between "device plugged in with the daemon already
holding BLE" vs "device freshly enumerated after a disconnect" — macOS's
IOKit driver matching runs through a probe-score contest, and minor timing
or state differences can change which driver wins.

We also did one `dev.reset()` which forced a re-enumeration; after that,
the `AppleUSBCDCCompositeDevice` match stuck and we couldn't get iface 2
back.

### What does *not* work

- `dev.reset()` — the reset itself runs, but after re-enumeration the
  kernel driver re-binds and we're back in the same state.
- `dev.detach_kernel_driver(0 or 2)` — returns EACCES on macOS.
- `dev.set_auto_detach_kernel_driver(True)` — pyusb's macOS backend does
  not expose this method.
- Racing the claim immediately after `reset()` — we polled for 20 attempts
  at 50 ms intervals and every single attempt got EACCES; the driver
  re-binds faster than user-space can race it.
- CUPS is not involved (`lpstat -p` shows no Niimbot printer registered).

## Possible fixes (none implemented)

Ordered best → worst:

### 1. Physical unplug → replug, then start the daemon first

If the daemon claims iface 2 before macOS's CDC composite driver finishes
binding, IOKit will honor the user-space claim. This requires careful boot
ordering and is fragile.

### 2. Codeless Info.plist / DriverKit override

The canonical solution: tell macOS "do not match `AppleUSBCDCCompositeDevice`
to VID 0x3513, PID 0x0002". Requires either disabling SIP (bad) or shipping
a signed DriverKit DEXT (too much effort for this project). There may be a
middle path via an override personality bundle, but modern macOS has made
this harder.

### 3. Run the daemon as root via launchd

macOS launchd supports system-level daemons running as root. With root
privileges, `detach_kernel_driver` would succeed. The user's current
`niimbotd` is a user-level launchd agent running as `adam`. Switching to a
system daemon is doable but changes the service model.

### 4. Privileged helper binary

Ship a tiny `setuid` or `sudo`-invoked helper that does just the
`detach_kernel_driver` for VID 0x3513 / PID 0x0002, runs once at
startup, and exits. The daemon then claims iface 2. Still requires a
password prompt or sudoers rule.

## How to validate the code when conditions allow

When you happen to be in a state where `usb.util.claim_interface(dev, 2)`
succeeds (e.g., immediately after a fresh plug-in, or after a reboot before
the CDC composite driver settles), you can validate the full daemon USB
path like this:

```sh
niimbotd stop
rm -f /tmp/niimbotd.log
niimbotd run > /tmp/niimbotd.log 2>&1 &
sleep 3
niimbotd status     # expect: Transport: USB
```

Or run the standalone probe:

```sh
python3 -c "
import usb.core, usb.util
d = usb.core.find(idVendor=0x3513, idProduct=0x0002)
usb.util.claim_interface(d, 2)
print('iface 2 claimed OK — USB path is available')
usb.util.release_interface(d, 2)
"
```

## Current state of the code

- `src/niimbot/usb.py` — complete `NiimbotUSB` transport, mirrors
  `NiimbotBLE` interface (`is_connected`, `transport_name`, `write_raw`,
  `transceive`, and all high-level command methods). Uses
  `asyncio.to_thread` to keep the daemon event loop responsive since
  pyusb is blocking.
- `src/niimbot/ble.py` — added `is_connected` property, `transport_name`
  property, and `write_raw` method so `printing.py` can be
  transport-agnostic.
- `src/niimbot/printing.py` — uses `printer.write_raw()` instead of the
  BLE-specific `client.write_gatt_char()`. Works with either transport.
- `src/niimbot/daemon/connection.py` — `ConnectionManager` now probes USB
  first in `_try_connect()`; if USB is absent or claim fails, falls back
  to BLE. Also re-probes USB every `USB_PROBE_INTERVAL` (5s) while
  connected over BLE, and calls `_maybe_swap_to_usb()` which acquires the
  print lock and swaps transports **between jobs only** (never during an
  active print).
- `src/niimbot/daemon/server.py` — `status` response includes the active
  transport string.
- `src/niimbot/daemon/__init__.py` — `niimbotd status` CLI prints it.
- `pyproject.toml` — `pyusb>=1.2` added as a dependency.

When the macOS driver-ownership issue is worked around, the daemon should
automatically start using USB without any further code changes.

## Related memory notes

`memory/project_usb_transport.md` has the original exploration notes
(protocol quirks, byte layouts, endpoint numbers). That's accurate but
does not cover the driver-ownership issue documented here.
