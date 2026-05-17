from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from langwatch.utils.auth import build_auth_headers

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
    url = f"{endpoint}/api/annotations/trace/{quote(trace_id, safe='')}"
    annotation_comment = comment.strip() if comment else ""
    body: dict[str, Any] = {
        "comment": annotation_comment or ("用户点赞" if is_thumbs_up else "用户点踩"),
        "isThumbsUp": is_thumbs_up,
    }
    if email:
        body["email"] = email
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, headers=build_auth_headers(settings.langwatch_api_key or ""), json=body)
            response.raise_for_status()
            payload = response.json()
            annotation_payload = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
            annotation_id = annotation_payload.get("id") if isinstance(annotation_payload, dict) else None
    except httpx.HTTPStatusError as exc:
        error = _format_http_status_error(exc)
        logger.warning("LangWatch 反馈同步失败，trace_id=%s error=%s", trace_id, error)
        return LangWatchAnnotationResult(status="failed", error=error)
    except Exception as exc:
        logger.warning("LangWatch 反馈同步失败，trace_id=%s error=%s", trace_id, exc)
        return LangWatchAnnotationResult(status="failed", error=str(exc))
    return LangWatchAnnotationResult(status="synced", annotation_id=str(annotation_id) if annotation_id else None)


def _format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    detail = ""
    try:
        payload = exc.response.json()
    except Exception:
        detail = exc.response.text.strip()
    else:
        if isinstance(payload, dict):
            raw_detail = payload.get("message") or payload.get("error") or payload.get("detail")
            detail = str(raw_detail) if raw_detail else ""
        else:
            detail = str(payload)
    return f"{exc} response={detail}" if detail else str(exc)
