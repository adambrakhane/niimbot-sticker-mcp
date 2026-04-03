## Sticker Printer MCP Server — Spec & Build Plan

### Architecture

```
Claude Code instance (any project)
    ↓ stdio
MCP Server (Node/TS or Python)
    ↓
Renderer (Pillow) → 319×240px PNG (40×30mm @ 203 DPI)
    ↓
Printer (niimbot_ble) → BLE → NIIMBOT P1 Pro
```

**Single MCP server, two responsibilities:** render a styled sticker image, then print it. One tool call from Claude's perspective.

### MCP Tool Definition

One tool: `print_sticker`

| Param | Type | Required | Description |
|---|---|---|---|
| `category` | enum | yes | `urgent`, `ticket`, `idea`, `big_idea` |
| `title` | string | yes | Main text (short — 3-8 words ideal) |
| `body` | string | no | Additional detail, auto-scaled to fit |
| `project` | string | no | Project/product name for context strip |
| `reference` | string | no | File path, ticket ID, or external ref |

Returns: success/failure + a base64 preview of the rendered sticker so Claude can show you what it printed.

### Visual Language (4 Styles)

All stickers share a structure but each category has a **distinct identity recognizable at arm's length:**

**Canvas:** 319×240px, 1-bit or grayscale (thermal printer). All styling is through layout, weight, borders, and fill patterns — no color.

#### 1. URGENT — Maximum visual weight
- **Full black header bar** (~40% of sticker) with inverted white text: `⚠ URGENT`
- Title in bold, large type below
- Body in smaller type if present
- Project name in small caps at bottom
- **Thick border** around entire sticker
- *Feel: You can't miss it. Black-heavy, high contrast.*

#### 2. TICKET — Structured, workmanlike
- **Thin top strip** with project name (black bg, white text)
- Title in medium-weight type, left-aligned
- Body text below in smaller type
- Reference/ticket ID in a `monospace pill` at bottom-right
- **Single-line border**
- *Feel: A miniature Jira card. Clean, scannable.*

#### 3. IDEA — Light, approachable
- **No border.** Open/airy.
- Small `💡 IDEA` label top-left (or a lightbulb glyph rendered as bitmap)
- Title in medium type, centered
- Body in italic if present
- Project name bottom-right, subtle
- *Feel: Post-it energy. Low pressure.*

#### 4. BIG IDEA — Bold but aspirational
- **Double-line border** (distinctive from Urgent's thick single)
- `★ BIG IDEA` header in large outline/stroke text (not filled — distinguishes from Urgent's solid black)
- Title large, centered
- Body below in regular weight
- Project/reference at bottom
- *Feel: Blueprint for something important. Stands out but differently than Urgent.*

### Text Scaling Logic

This is critical for a fixed 40×30mm canvas:

1. **Title:** Start at max font size for category. Binary search down until it fits within the title region (max 2 lines, word-wrapped).
2. **Body:** Start at a readable size, scale down to a minimum. If it still doesn't fit, truncate with `…` — the sticker is a *pointer*, not a document.
3. **Reference:** Fixed small size, truncated with `…/filename` if it's a path.

Minimum readable size at 203 DPI thermal: ~8pt. Don't go below it.

### Project Structure

```
niimbot-mcp/
├── src/
│   ├── server.py          # MCP server (stdio transport)
│   ├── renderer.py        # Pillow-based sticker rendering
│   ├── printer.py         # niimbot_ble wrapper
│   ├── fonts/             # 2-3 bundled fonts (mono, sans, sans-bold)
│   └── templates.py       # Per-category layout constants
├── pyproject.toml
└── README.md
```

Python makes sense here since your printer lib is already Python. No need to port to Node.

### Global Claude Code Config

In `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "sticker-printer": {
      "command": "python",
      "args": ["-m", "niimbot_mcp.server"],
      "env": {
        "NIIMBOT_DEVICE_ADDRESS": "XX:XX:XX:XX:XX:XX"
      }
    }
  }
}
```

Every Claude Code session, any project, gets `print_sticker` automatically. The BLE address is the only config needed.

### Build Sequence

1. **Renderer first.** Get the 4 templates producing good-looking PNGs with test data. Iterate visually until you like them. This is the hard/subjective part.
2. **MCP server shell.** Wire up the tool schema, parse params, call renderer, return base64 preview. Test with `claude mcp serve` or the MCP inspector.
3. **Printer integration.** Wire renderer output → `niimbot_ble`. Handle BLE connection failures gracefully (retry once, then return error to Claude).
4. **Global config.** Drop into `settings.json`, test from a fresh project.

### Edge Cases to Handle

- **BLE not connected / printer off:** Return clear error so Claude can tell you "printer appears offline" rather than hanging.
- **Text too long:** Aggressive truncation is fine. The sticker is a *reference*, not the source of truth.
- **Concurrent prints:** BLE is one-at-a-time. If you're printing from two sessions simultaneously, the MCP server should queue or reject-with-retry. A simple file lock would work.
- **Preview without printing:** Consider a `dry_run` boolean param so Claude can show you the sticker before committing to paper.
