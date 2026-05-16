from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.monitoring.langwatch import is_langwatch_enabled


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LangWatchAnnotationResult:
    status: str
    annotation_id: str | None = None
    error: str | None = None

    @property
    def synced(self) -> bool:
        return self.status == "synced"


async def create_langwatch_annotation(
    settings: Settings,
    *,
    trace_id: str | None,
    is_thumbs_up: bool,
    comment: str | None,
    email: str | None,
) -> LangWatchAnnotationResult:
    if not is_langwatch_enabled(settings):
        return LangWatchAnnotationResult(status="disabled")
    if not trace_id:
        return LangWatchAnnotationResult(status="skipped", error="缺少 trace_id")

    endpoint = (settings.langwatch_endpoint or "https://app.langwatch.ai").rstrip("/")
    url = f"{endpoint}/api/annotations/trace/{trace_id}"
    body: dict[str, Any] = {"isThumbsUp": is_thumbs_up}
    if comment:
        body["comment"] = comment
    if email:
        body["email"] = email
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, headers={"X-Auth-Token": settings.langwatch_api_key or ""}, json=body)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("LangWatch 反馈同步失败，trace_id=%s error=%s", trace_id, exc)
        return LangWatchAnnotationResult(status="failed", error=str(exc))
    return LangWatchAnnotationResult(status="synced", annotation_id=str(payload.get("id")) if payload.get("id") else None)
