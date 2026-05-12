import re
import uuid

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


async def load_artifact_part(artifact: MessageArtifact, settings: Settings | None = None) -> types.Part | None:
    settings = settings or get_settings()
    return await get_artifact_service().load_artifact(
        app_name=settings.chat_app_name,
        user_id=artifact.user_id,
        filename=f"user:{artifact.storage_filename}",
        version=artifact.version,
    )
