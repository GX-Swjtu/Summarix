import hashlib
import re
import uuid
from urllib.parse import urlparse

from google.adk.artifacts import FileArtifactService
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import get_chat_artifact_root
from app.core.config import Settings, get_settings
from app.db.models import MessageArtifact


_artifact_service: FileArtifactService | None = None


def get_artifact_service() -> FileArtifactService:
    global _artifact_service
    if _artifact_service is None:
        _artifact_service = FileArtifactService(root_dir=get_chat_artifact_root())
    return _artifact_service


def make_storage_filename(original_filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_filename).strip("._") or "artifact"
    return f"{uuid.uuid4()}_{safe_name}"


def make_page_text_filename(page_title: str | None, page_url: str | None) -> str:
    title = (page_title or "").strip()
    if not title and page_url:
        title = urlparse(page_url).netloc or page_url
    title = title or "当前网页"
    filename = f"{title}.txt"
    return filename[:255]


def make_text_excerpt(text: str | None, fallback: str | None = None, limit: int = 180) -> str | None:
    source = text or fallback or ""
    excerpt = re.sub(r"\s+", " ", source).strip()
    if not excerpt:
        return None
    return excerpt if len(excerpt) <= limit else f"{excerpt[:limit].rstrip()}..."


async def save_upload_artifact(
    session: AsyncSession,
    user_id: str,
    filename: str,
    mime_type: str,
    data: bytes,
    conversation_id: str | None = None,
    source: str = "screenshot",
    settings: Settings | None = None,
) -> MessageArtifact:
    settings = settings or get_settings()
    if len(data) > settings.chat_max_artifact_bytes:
        raise ValueError("文件过大")
    storage_filename = make_storage_filename(filename)
    part = types.Part.from_bytes(data=data, mime_type=mime_type)
    version = await get_artifact_service().save_artifact(
        app_name=settings.chat_app_name,
        user_id=user_id,
        session_id=conversation_id,
        filename=f"user:{storage_filename}",
        artifact=part,
        custom_metadata={"original_filename": filename, "source": source},
    )
    artifact = MessageArtifact(
        user_id=user_id,
        conversation_id=conversation_id,
        filename=filename,
        storage_filename=storage_filename,
        mime_type=mime_type,
        size_bytes=len(data),
        version=version,
        source=source,
    )
    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)
    return artifact


async def save_page_text_artifact(
    session: AsyncSession,
    user_id: str,
    conversation_id: str,
    message_id: str,
    page_title: str | None,
    page_url: str | None,
    page_text: str | None,
    original_text_length: int | None,
    settings: Settings | None = None,
) -> MessageArtifact:
    settings = settings or get_settings()
    reference_lines: list[str] = []
    if page_title:
        reference_lines.append(f"标题：{page_title}")
    if page_url:
        reference_lines.append(f"URL：{page_url}")
    if page_text:
        if reference_lines:
            reference_lines.append("")
        reference_lines.append(page_text)
    reference_text = "\n".join(reference_lines).strip()
    if not reference_text:
        reference_text = "未提供网页正文。"
    data = reference_text.encode("utf-8")
    if len(data) > settings.chat_max_artifact_bytes:
        raise ValueError("网页正文过大")

    filename = make_page_text_filename(page_title, page_url)
    storage_filename = make_storage_filename(filename)
    version = await get_artifact_service().save_artifact(
        app_name=settings.chat_app_name,
        user_id=user_id,
        session_id=conversation_id,
        filename=f"user:{storage_filename}",
        artifact=types.Part.from_bytes(data=data, mime_type="text/plain; charset=utf-8"),
        custom_metadata={"original_filename": filename, "source": "page_text", "page_url": page_url, "page_title": page_title},
    )
    artifact = MessageArtifact(
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        filename=filename,
        storage_filename=storage_filename,
        mime_type="text/plain; charset=utf-8",
        size_bytes=len(data),
        version=version,
        source="page_text",
        page_url=page_url,
        page_title=page_title,
        text_excerpt=make_text_excerpt(page_text, page_title or page_url),
        text_length=original_text_length if original_text_length is not None else len(page_text or ""),
        content_hash=hashlib.sha256(data).hexdigest(),
    )
    session.add(artifact)
    await session.flush()
    return artifact


async def load_artifact_part(artifact: MessageArtifact, settings: Settings | None = None) -> types.Part | None:
    settings = settings or get_settings()
    return await get_artifact_service().load_artifact(
        app_name=settings.chat_app_name,
        user_id=artifact.user_id,
        filename=f"user:{artifact.storage_filename}",
        version=artifact.version,
    )
