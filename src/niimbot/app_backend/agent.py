"""Claude Agent SDK integration for draft generation."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from niimbot.app_backend.protocol import DraftStatus, StickerDraft
from niimbot.app_backend.mcp_client import NiimbotMCPClient


COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def extract_requested_count(prompt: str) -> int | None:
    lower = prompt.lower()
    match = re.search(r"\b(\d+)\s+stickers?\b", lower)
    if match:
        return max(1, int(match.group(1)))
    for word, value in COUNT_WORDS.items():
        if re.search(rf"\b{word}\s+stickers?\b", lower):
            return value
    return None


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        parts = stripped.split("```")
        stripped = next((part for part in parts if "{" in part), stripped)
        stripped = stripped[stripped.find("{") :]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Agent did not return JSON")
    return json.loads(stripped[start : end + 1])


def normalize_drafts(payload: dict[str, Any], requested_count: int | None, project_default: str) -> list[dict[str, Any]]:
    drafts = payload.get("drafts")
    if not isinstance(drafts, list) or not drafts:
        raise ValueError("Agent response did not contain a non-empty drafts array")

    normalized: list[dict[str, Any]] = []
    for item in drafts:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        normalized.append(
            {
                "category": str(item.get("category", "ticket")),
                "title": title,
                "body": str(item.get("body", "")).strip(),
                "project": str(item.get("project", "")).strip() or project_default,
                "reference": str(item.get("reference", "")).strip(),
            }
        )

    if not normalized:
        raise ValueError("Agent returned no usable drafts")

    if requested_count is not None:
        if len(normalized) > requested_count:
            normalized = normalized[:requested_count]
        seed = dict(normalized[-1])
        while len(normalized) < requested_count:
            clone = dict(seed)
            clone["title"] = f"{clone['title']} ({len(normalized) + 1})"
            normalized.append(clone)

    return normalized


async def generate_drafts(
    prompt: str,
    mcp_client: NiimbotMCPClient,
    project_default: str = "",
    on_progress: Callable[[str], None] | None = None,
) -> list[StickerDraft]:
    try:
        from claude_agent_sdk import ClaudeAgentOptions as SDKOptions, query
    except ImportError as exc:
        raise RuntimeError(
            "Claude Agent SDK is not installed. Install with: pip install '.[app]'"
        ) from exc

    requested_count = extract_requested_count(prompt)
    count_text = requested_count if requested_count is not None else "the right number"
    schema_hint = {
        "drafts": [
            {
                "category": "urgent|ticket|idea|big_idea",
                "title": "short sticker title",
                "body": "optional short body",
                "project": project_default,
                "reference": "",
            }
        ]
    }
    agent_prompt = (
        "Generate concise sticker drafts for a small thermal label printer.\n"
        f"Return exactly {count_text} draft objects if the user requested a count.\n"
        "Keep titles short and sticker-sized. Body is optional and should stay brief.\n"
        "Infer category when obvious. Use one of: urgent, ticket, idea, big_idea.\n"
        "Default project to the current repo name when not stated.\n"
        "Do not print anything. Do not include explanation.\n"
        f"Return only JSON matching this shape: {json.dumps(schema_hint)}\n\n"
        f"User prompt: {prompt}"
    )

    options = SDKOptions(
        system_prompt="You create concise sticker drafts and output strict JSON only.",
        model="claude-haiku-4-5",
        allowed_tools=[],
        include_partial_messages=True,
    )

    result_text = None
    async for message in query(prompt=agent_prompt, options=options):
        if hasattr(message, "is_error") and message.is_error:
            errors = getattr(message, "errors", None) or []
            raise RuntimeError(f"Agent returned an error: {'; '.join(errors) or 'unknown'}")
        if hasattr(message, "result") and message.result is not None:
            result_text = message.result
        # Stream assistant text chunks to the progress callback
        if on_progress and hasattr(message, "content"):
            for block in message.content:
                text = getattr(block, "text", None)
                if text:
                    on_progress(text)

    if not result_text:
        raise RuntimeError("Claude Agent SDK did not return a final result")

    normalized = normalize_drafts(extract_json(result_text), requested_count, project_default)
    total = len(normalized)
    drafts: list[StickerDraft] = []
    for i, item in enumerate(normalized, start=1):
        if on_progress:
            on_progress(f"\nRendering sticker {i}/{total}: {item['title']}")
        preview = await mcp_client.call_tool("preview_note", item)
        drafts.append(
            StickerDraft(
                id=str(uuid.uuid4()),
                category=preview["category"],
                title=preview["title"],
                body=preview["body"],
                project=preview["project"],
                reference=preview["reference"],
                preview_png_base64=preview["preview_png_base64"],
                is_dirty=False,
                status=DraftStatus.READY.value,
            )
        )
    return drafts
