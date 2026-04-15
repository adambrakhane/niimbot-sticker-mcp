"""JSON protocol types for the Niimbot popup backend."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class StickerCategory(str, Enum):
    URGENT = "urgent"
    TICKET = "ticket"
    IDEA = "idea"
    BIG_IDEA = "big_idea"


class DraftStatus(str, Enum):
    IDLE = "idle"
    REGENERATING = "regenerating"
    READY = "ready"
    PRINTING = "printing"
    PRINTED = "printed"
    FAILED = "failed"


@dataclass
class StickerDraft:
    id: str
    category: str
    title: str
    body: str = ""
    project: str = ""
    reference: str = ""
    preview_png_base64: str = ""
    is_dirty: bool = False
    status: str = DraftStatus.READY.value
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def draft_from_dict(payload: dict[str, Any]) -> StickerDraft:
    return StickerDraft(
        id=str(payload.get("id", "")),
        category=str(payload.get("category", StickerCategory.TICKET.value)),
        title=str(payload.get("title", "")),
        body=str(payload.get("body", "")),
        project=str(payload.get("project", "")),
        reference=str(payload.get("reference", "")),
        preview_png_base64=str(payload.get("preview_png_base64", "")),
        is_dirty=bool(payload.get("is_dirty", False)),
        status=str(payload.get("status", DraftStatus.READY.value)),
        error_message=payload.get("error_message"),
    )


def make_response(request_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"type": "response", "id": request_id, "ok": True, "result": result}


def make_error(request_id: str, message: str) -> dict[str, Any]:
    return {"type": "response", "id": request_id, "ok": False, "error": message}


def make_event(request_id: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "event", "id": request_id, "event": event, "payload": payload}
