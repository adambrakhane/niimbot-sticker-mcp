## Sticker Printer MCP Server — Spec & Build Plan

### Architecture

```
Claude Code instance (any project)
    ↓ stdio
MCP Server (Node/TS or Python)
    ↓
Renderer (Pillow) → 568×350px PNG (40×30mm @ 300 DPI)
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
| `dry_run` | bool | no | If true, return preview image without printing |

Returns: success/failure + a base64 preview of the rendered sticker so Claude can show you what it printed.

### Design Principles — Minimal Friction

The goal is fast, low-effort sticker creation. The user should be able to say something vague and get a sticker printed in seconds.

**Only `title` and `category` are required. Everything else is inferred or omitted.**

- **`category`** — Claude should infer from context when possible:
  - "this is broken in prod" / "fix this now" / "blocking deploy" → `urgent`
  - "we should do X" / "add support for Y" / "refactor Z" → `ticket`
  - "what if we..." / "random thought" / "wouldn't it be cool" → `idea`
  - "long-term, we need..." / "vision for Q3" / "big picture" → `big_idea`
  - If genuinely ambiguous, ask — but bias toward just picking one. Don't overthink it.
- **`project`** — Infer from the current working directory or repo name. Don't ask.
- **`reference`** — Use if there's a ticket number, file path, or URL in the conversation. If not, omit. Never ask for one.
- **`body`** — Include if there's useful extra context. A short title can stand alone. Don't pad it.
- **`dry_run`** — Use when the user asks to preview before printing, or on the first print of a session to confirm the printer works.

### Example Invocations

**Minimal — user just wants a quick note:**
> "Print me a sticker that says 'check API rate limits'"

```json
{"category": "ticket", "title": "Check API rate limits", "project": "niimbot"}
```

**Urgent from conversation context:**
> "The deploy is failing, auth tokens expire after 5 min. Can you print that so I don't forget?"

```json
{"category": "urgent", "title": "Fix auth token expiry", "body": "Tokens expire after 5 min, blocking deploy", "project": "niimbot"}
```

**Idea — casual:**
> "What if we kept the BLE connection alive between prints?"

```json
{"category": "idea", "title": "Persistent BLE connection", "body": "Skip 1.5s reconnect on every print", "project": "niimbot"}
```

**Fully specified — user provides everything:**
> "Print an urgent sticker: 'DB migration failing', body: 'Rollback needed on prod-east-2', ref INFRA-891"

```json
{"category": "urgent", "title": "DB migration failing", "body": "Rollback needed on prod-east-2", "project": "niimbot", "reference": "INFRA-891"}
```

**Big idea with no body:**
> "Big idea: unified design system for all label types"

```json
{"category": "big_idea", "title": "Unified label design system", "project": "niimbot"}
```

### Visual Language (4 Styles)

All stickers share a structure but each category has a **distinct identity recognizable at arm's length:**

**Canvas:** 568×350px, 1-bit (thermal printer, 300 DPI, 40×30mm label). All styling is through layout, weight, borders, and fill patterns — no color.

#### 1. URGENT — Full invert, white on black
- **Entire sticker is black background with white text**
- Small "URGENT" tag top-left
- Title large, bold, white
- Body in regular white text
- Project bottom-left, reference bottom-right
- Thin white inset border
- *Feel: Maximum ink, maximum contrast. Impossible to miss from across the room.*

#### 2. TICKET — Sidebar
- **Black vertical sidebar on left** with project name stacked vertically in white
- Title large, bold, to the right of sidebar
- Body below in regular text
- Reference (ticket ID) in monospace, bottom-right
- *Feel: Structured, workmanlike. Like a mini Jira card.*

#### 3. IDEA — Post-it with lightbulb
- **Light border** like a sticky note
- Small **lightbulb icon** in top-right corner (drawn as circle + rays + base)
- "IDEA" label top-left
- Title large, bold, left-aligned
- Body below
- Project bottom-right, subtle
- *Feel: Post-it energy. Light, approachable, low pressure.*

#### 4. BIG IDEA — Sunburst rays
- **Dashed rays radiating from center** as the border/background pattern
- White content box in the center over the rays
- "BIG IDEA" tag centered at top with horizontal rule below
- Title large, bold, centered
- Body centered below
- Project | reference at bottom, centered
- *Feel: Aspirational, bold, distinctive. The rays catch the eye differently from any other category.*

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
