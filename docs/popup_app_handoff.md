# Niimbot Popup App Handoff

## Current Status

The popup app stack is implemented and builds locally.

Completed:

- Native macOS SwiftUI app scaffold in `mac-app/`
- Floating centered panel with:
  - prompt input
  - editable draft cards
  - per-card preview refresh
  - per-card print
  - print-all with progress
  - auto-dismiss after successful `Print All`
- Python backend sidecar in `src/niimbot/app_backend/`
- Structured MCP tools in `src/niimbot/mcp/server.py`
  - `preview_note`
  - structured `print_note`
- Python tests passing
- Swift tests passing
- `.app` bundle builds to `dist/NiimbotPopup.app`

## Verified Locally

Verified in this environment:

- `python3 -m unittest discover -s tests -v` passes
- `cd mac-app && swift build` passes
- `cd mac-app && swift test` passes
- `./mac-app/build_app.sh` produces `dist/NiimbotPopup.app`
- backend `refresh_preview` JSON-over-stdio flow works end to end

Not verified in this environment:

- live Claude Agent SDK draft generation against Anthropic
- real interactive UI behavior after launch
- real print path from the app UI to hardware

Reason:

- `ANTHROPIC_API_KEY` was not set in this shell

## Important Files

### App

- `mac-app/Package.swift`
- `mac-app/Sources/NiimbotPopup/NiimbotPopupApp.swift`
- `mac-app/Sources/NiimbotPopup/PopupPanelController.swift`
- `mac-app/Sources/NiimbotPopup/ContentView.swift`
- `mac-app/Sources/NiimbotPopup/Models/StickerDraft.swift`
- `mac-app/Sources/NiimbotPopup/ViewModels/AppViewModel.swift`
- `mac-app/Sources/NiimbotPopup/Services/BackendBridge.swift`

### Backend

- `src/niimbot/app_backend/__main__.py`
- `src/niimbot/app_backend/agent.py`
- `src/niimbot/app_backend/mcp_client.py`
- `src/niimbot/app_backend/protocol.py`

### MCP server

- `src/niimbot/mcp/server.py`

### Tests

- `tests/test_mcp_server.py`
- `tests/test_app_backend.py`
- `mac-app/Tests/NiimbotPopupTests/AppViewModelTests.swift`

## Runtime Model

The app launches:

```text
python3 -m niimbot.app_backend
```

The backend then:

1. receives JSON-over-stdio requests from Swift
2. uses Claude Agent SDK for `generate_drafts`
3. uses MCP stdio client to talk to `python -m niimbot.mcp.server`
4. uses `preview_note` for preview refresh
5. uses `print_note` for physical printing

Printing stays deterministic because only draft generation uses the agent. Preview refresh and printing call MCP directly.

## Commands

### Install

```bash
pip install -e '.[app]'
```

### Run tests

```bash
python3 -m unittest discover -s tests -v
cd mac-app && swift test
```

### Build app

```bash
./mac-app/build_app.sh
```

### Launch app

```bash
./mac-app/run_app.sh
```

Or open the built app directly:

```bash
open dist/NiimbotPopup.app
```

## Required Environment

Needed for live AI generation:

- `ANTHROPIC_API_KEY`

Expected locally:

- `python3`
- Swift / Xcode toolchain
- repo available on disk so the app can set `PYTHONPATH` to `repo_root/src`

## Current UX Behavior

- The app opens a floating panel and reuses that panel if re-launched
- `Generate` calls the backend
- If generation fails and there are no drafts yet, the UI falls back to prototype cards
- Editing any field marks the card dirty
- `Regenerate Preview` calls `preview_note`
- `Print` prints the current edited values directly
- `Print All` prints sequentially and dismisses the panel on full success

## Known Gaps / Risks

### 1. Live Claude Agent SDK path is not fully exercised

The package is installed now, but no real generation request was run here because no API key was available in the shell.

Recommended next check:

```bash
export ANTHROPIC_API_KEY=...
python3 -m niimbot.app_backend
```

Then send a `generate_drafts` JSON request or use the app UI directly.

### 2. Claude Agent SDK API surface may need a small compatibility adjustment

`src/niimbot/app_backend/agent.py` currently assumes:

- import path `claude_agent_sdk`
- `query(...)`
- options type compatible with `ClaudeAgentOptions`

That should be the first thing to verify with a live request. If the installed SDK version differs slightly, the fix should be localized to `agent.py`.

### 3. App packaging is basic

The `.app` bundle is produced by a shell script and includes `repo-root.txt` for locating the Python backend source tree. It is good enough for local launch and keyboard binding, but not yet a polished distributable app.

### 4. No persistent history

The app is intentionally stateless between launches.

## Suggested Next Agent Tasks

1. Run one real `generate_drafts` flow with `ANTHROPIC_API_KEY` set.
2. Launch `dist/NiimbotPopup.app` and verify the UI behavior manually.
3. Print a single real label from the app.
4. Print multiple labels with `Print All`.
5. If the Claude Agent SDK API differs, fix `src/niimbot/app_backend/agent.py`.
6. If needed, refine the app bundle so it can launch outside the repo root more robustly.

## Quick Smoke Test Payload

This can be sent directly to the backend stdin for generation testing:

```json
{"id":"1","method":"generate_drafts","params":{"prompt":"make me three stickers: one urgent for deploy failure, two ideas about BLE reconnect improvements"}}
```

This can be used for preview refresh testing:

```json
{"id":"2","method":"refresh_preview","params":{"draft":{"id":"12345678-1234-1234-1234-123456789012","category":"ticket","title":"Check API rate limits","body":"before deploy","project":"niimbot","reference":"OPS-17","preview_png_base64":"","is_dirty":true,"status":"idle","error_message":null}}}
```
