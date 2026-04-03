# NIIMBOT B1 Pro - Printer & Label Specs

## Printer Hardware
- **Model**: B1 Pro (model ID from serial: I116030475)
- **Print method**: Direct thermal (no ink/ribbon)
- **DPI**: 300
- **Printhead width**: 567 dots (568 rounded to multiple of 8 for byte alignment)
- **Battery**: USB-C charging, ~80% reported in testing
- **Connectivity**: Bluetooth (BLE + Classic)

## Label Stock (currently loaded)
- **Size**: 40mm x 30mm
- **At 300 DPI**: 472px x 354px (calculated: mm * 300 / 25.4)
- **RFID barcode**: `061625108` (first 4 digits likely encode dims in some format)
- **RFID serial**: PZ1HC31309007349
- **RFID total_len**: 96, type: unknown
- **Label type**: Gap-detect (label type = 1)

## Tested & Working Print Parameters
- **Image width**: 568px (printhead width, padded to byte boundary)
- **Image height**: 300px confirmed working (~90% of label). 354px = theoretical max. 400px = too tall, fails.
- **Density**: 3 (out of unknown range)
- **BLE write mode**: `response=True` per row is reliable but slow (~20ms/row)
- **BLE write mode**: `response=False` with 10ms delay is fast but unreliable above ~200 rows

## BLE Connection
- **BLE address**: A6961AF4-A34F-DEC9-B4DD-FF072B55408C
- **Service**: ISSC Serial Port `49535343-fe7d-4ae5-8fa9-9fafd205e455`
- **Notify char**: `49535343-1e4d-4bd9-ba61-23c647249616`
- **Write char**: `49535343-8841-43f4-a8d4-ecbe34729bb3`
- **MTU**: System default (bleak/CoreBluetooth handles fragmentation)

## Print Sequence (B1PrintTask)
1. setDensity(3)
2. setLabelType(1)
3. startPrint(totalPages, 7-byte format)
4. startPage()
5. setPageSize(rows, cols, copies) -- 6-byte format
6. Send bitmap rows (0x85 full / 0x84 empty / 0x83 indexed)
7. endPage()
8. Poll status until 100%
9. endPrint()

## Bitmap Row Encoding
- 1-bit monochrome, MSB-first, row-by-row
- **Full row (0x85)**: `[rowNum:u16] [0, countLo, countHi] [repeat:u8] [rowData:71 bytes]`
- **Empty row (0x84)**: `[rowNum:u16] [repeat:u8]`
- **Indexed row (0x83)**: `[rowNum:u16] [0, countLo, countHi] [repeat:u8] [pixelPos:u16...]`
- Indexed mode used when black pixel count <= 6
- Bitmap commands are one-way (no ACK from printer)

## Known Issues
- Sending rows with `response=False` too fast causes buffer overflow -- data arrives after pageEnd, prints blank or on next job
- `response=True` is reliable but slow (~6s for 300 rows)
- Printer needs fresh BLE connection between print jobs for reliability
- Height > physical label causes silent print failure (protocol reports success)

## TODO / Unknown
- [ ] Exact usable label height in pixels (run test_combos.py to confirm)
- [ ] PrinterInfoType.Area (key=15) response -- may report printable area
- [ ] RFID barcode dimension encoding format
- [ ] Faster BLE transfer strategy (batching? larger MTU negotiation?)
- [ ] Density range (min/max values)
- [ ] Multi-page printing (untested)
