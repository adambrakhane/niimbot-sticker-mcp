"""Run the Niimbot popup app backend over JSON-over-stdio."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from typing import Any, Awaitable, Callable

from niimbot.app_backend.agent import generate_drafts
from niimbot.app_backend.mcp_client import NiimbotMCPClient
from niimbot.app_backend.protocol import (
    DraftStatus,
    StickerDraft,
    draft_from_dict,
    make_error,
    make_event,
    make_response,
)

logging.basicConfig(level=logging.INFO, format="%(name)s:%(levelname)s: %(message)s")
log = logging.getLogger("niimbot.app_backend")


def _write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


class BackendService:
    def __init__(self) -> None:
        self._mcp = NiimbotMCPClient()

    async def close(self) -> None:
        await self._mcp.close()

    async def dispatch(self, request_id: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        handlers: dict[str, Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
            "generate_drafts": self._generate_drafts,
            "refresh_preview": self._refresh_preview,
            "print_one": self._print_one,
            "print_all": self._print_all,
        }
        handler = handlers.get(method)
        if handler is None:
            raise RuntimeError(f"Unknown method: {method}")
        return await handler(request_id, params)

    async def _generate_drafts(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        prompt = str(params.get("prompt", "")).strip()
        if not prompt:
            raise RuntimeError("Prompt must not be empty")

        def on_progress(text: str) -> None:
            _write_message(make_event(request_id, "agent_progress", {"text": text}))

        drafts = await generate_drafts(prompt, self._mcp, on_progress=on_progress)
        return {"drafts": [draft.to_dict() for draft in drafts]}

    async def _refresh_preview(self, _: str, params: dict[str, Any]) -> dict[str, Any]:
        draft = draft_from_dict(params.get("draft", {}))
        preview = await self._mcp.call_tool(
            "preview_note",
            {
                "category": draft.category,
                "title": draft.title,
                "body": draft.body,
                "project": draft.project,
                "reference": draft.reference,
            },
        )
        updated = StickerDraft(
            id=draft.id or str(uuid.uuid4()),
            category=preview["category"],
            title=preview["title"],
            body=preview["body"],
            project=preview["project"],
            reference=preview["reference"],
            preview_png_base64=preview["preview_png_base64"],
            is_dirty=False,
            status=DraftStatus.READY.value,
            error_message=None,
        )
        return {"draft": updated.to_dict()}

    async def _print_one(self, _: str, params: dict[str, Any]) -> dict[str, Any]:
        draft = draft_from_dict(params.get("draft", {}))
        payload = await self._mcp.call_tool(
            "print_note",
            {
                "category": draft.category,
                "title": draft.title,
                "body": draft.body,
                "project": draft.project,
                "reference": draft.reference,
                "dry_run": False,
            },
        )

        status = DraftStatus.PRINTED.value if payload.get("status") == "ok" else DraftStatus.FAILED.value
        updated = StickerDraft(
            id=draft.id or str(uuid.uuid4()),
            category=payload.get("category", draft.category),
            title=payload.get("title", draft.title),
            body=payload.get("body", draft.body),
            project=payload.get("project", draft.project),
            reference=payload.get("reference", draft.reference),
            preview_png_base64=payload.get("preview_png_base64", draft.preview_png_base64),
            is_dirty=False,
            status=status,
            error_message=payload.get("error"),
        )
        return {
            "draft": updated.to_dict(),
            "status": payload.get("status", "error"),
            "duration_ms": payload.get("duration_ms"),
            "error": payload.get("error"),
            "message": payload.get("message"),
        }

    async def _print_all(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        raw_drafts = params.get("drafts", [])
        if not isinstance(raw_drafts, list) or not raw_drafts:
            raise RuntimeError("At least one draft is required")

        total = len(raw_drafts)
        results: list[dict[str, Any]] = []
        failures = 0
        for index, raw_draft in enumerate(raw_drafts, start=1):
            draft = draft_from_dict(raw_draft)
            _write_message(
                make_event(
                    request_id,
                    "print_progress",
                    {
                        "current": index,
                        "total": total,
                        "draft_id": draft.id,
                        "phase": "starting",
                    },
                )
            )

            result = await self._print_one(request_id, {"draft": draft.to_dict()})
            results.append(result["draft"])
            if result.get("status") != "ok":
                failures += 1

            _write_message(
                make_event(
                    request_id,
                    "print_progress",
                    {
                        "current": index,
                        "total": total,
                        "draft_id": draft.id,
                        "phase": "finished",
                        "status": result.get("status"),
                        "error": result.get("error"),
                    },
                )
            )

        return {
            "drafts": results,
            "printed_count": total - failures,
            "failed_count": failures,
        }


async def _run() -> None:
    service = BackendService()
    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            request_id = "unknown"
            try:
                request = json.loads(line)
                request_id = str(request.get("id", "unknown"))
                method = str(request.get("method", ""))
                params = request.get("params", {})
                result = await service.dispatch(request_id, method, params if isinstance(params, dict) else {})
                _write_message(make_response(request_id, result))
            except Exception as exc:
                log.error("Backend request failed: %s", exc, exc_info=True)
                _write_message(make_error(request_id, str(exc)))
    finally:
        await service.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
