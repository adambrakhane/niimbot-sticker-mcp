# NIIMBOT B1 Pro Research Notes

## Device Info
- **Model**: B1 Pro-I116030475
- **BT Address**: 35:13:0A:0A:24:CA (classic BT)
- **BLE UUID**: A6961AF4-A34F-DEC9-B4DD-FF072B55408C
- **RSSI**: -35 (strong)
- **Minor Type**: Printer

## BLE Services Discovered

### Service 1: `e7810a71-73ae-499d-8c15-faa9aef0c3f2` (ISSC Transparent UART)
- **Char**: `bef8d6c9-9c21-4c9e-b632-bd58c1009f9f`
  - Props: notify, read, write-without-response, write
  - This is the main data channel - bidirectional UART-like communication
  - Read value: `00000000`

### Service 2: `49535343-fe7d-4ae5-8fa9-9fafd205e455` (ISSC Serial Port)
- **Char 1**: `49535343-1e4d-4bd9-ba61-23c647249616` (notify)
  - RX notifications from printer
- **Char 2**: `49535343-8841-43f4-a8d4-ecbe34729bb3` (write, write-without-response)
  - TX to printer

## Protocol Format
- **Head**: `0x55 0x55`
- **Command**: 1 byte
- **Data Length**: 1 byte
- **Data**: N bytes
- **Checksum**: XOR of all bytes from Command through last Data byte
- **Tail**: `0xAA 0xAA`

## Key Commands
| Cmd  | Name              | Notes |
|------|-------------------|-------|
| 0x01 | PrintStart        | Start print job |
| 0x03 | PageStart         | Start a page |
| 0x13 | SetPageSize       | Set dimensions |
| 0x21 | SetDensity        | Print darkness |
| 0x23 | SetLabelType      | Label type |
| 0x40 | PrinterInfo       | Get info (subcommands via data byte) |
| 0x5a | PrintTestPage     | Test page |
| 0x84 | PrintEmptyRow     | Empty row |
| 0x85 | PrintBitmapRow    | Bitmap row |
| 0xa3 | PrintStatus       | Get status |
| 0xc1 | Connect           | Initial connect |
| 0xdc | Heartbeat         | Keep alive |
| 0xe3 | PageEnd           | End page |
| 0xf3 | PrintEnd          | End print job |

## PrinterInfo Sub-IDs (data byte for cmd 0x40)
| Data | Info Type |
|------|-----------|
| 0x01 | Device Serial |
| 0x02 | Software Version |
| 0x03 | Hardware Version |
| 0x04 | Model Name |
| 0x0b | Device Serial (alt) |

## Open Source Libraries
1. **niimprint** (Python) - https://github.com/AndBondStyle/niimprint - BT + USB, D11/B21/B1
2. **NiimPrintX** (Python) - https://github.com/labbots/NiimPrintX - BT, D11/B21/B1/D110/B18
3. **niimbluelib** (TypeScript) - https://github.com/MultiMote/niimbluelib - Web BLE
4. **niimblue** (Web app) - https://github.com/MultiMote/niimblue - Full web client
5. **niimblue-node** (Node.js) - https://github.com/MultiMote/niimblue-node - CLI + print server
6. **hass-niimbot** (HA integration) - https://github.com/eigger/hass-niimbot

## B1 Pro Specs
- Print head: 203 DPI, likely 384 dots wide (48mm printable)
- Label width: up to 50mm
- Thermal printing (no ink)
- Battery powered with USB-C charging

## BLE Communication Key Details
- **Primary UART char** works: `bef8d6c9-9c21-4c9e-b632-bd58c1009f9f` (read/write/notify)
- Write-without-response mode works for TX
- 20-byte chunk size for BLE MTU
- Responses arrive via notifications on same characteristic

## Test Results
- [x] BLE scan: FOUND (A6961AF4-A34F-DEC9-B4DD-FF072B55408C)
- [x] BLE connect: SUCCESS
- [x] Service discovery: SUCCESS (2 services)
- [x] Heartbeat: SUCCESS - lid closed, 80% battery, paper inserted, RFID OK
- [x] Get printer info: PARTIAL - serial2 works (I116030475), HW ver 0.01
  - Serial (0x01) returns response type 0x41 with data 0x03
  - SW version (0x02) returns cmd 0x00 (not supported?)
  - HW version (0x03) works, returns 0x01
  - Serial2 (0x0b) works, returns "I116030475"
- [x] RFID: SUCCESS - label detected, barcode=061625108, serial=PZ1HC31309007349, 96 total length
- [ ] Print test page
