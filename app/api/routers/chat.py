import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user
from app.api.schemas import ArtifactResponse, ArtifactSource, ChatStreamRequest
from app.chat.artifacts import load_artifact_part, save_upload_artifact
from app.chat.stream_service import stream_chat_response
from app.core.config import Settings, get_settings
from app.db.models import MessageArtifact, User
from app.db.session import get_db_session

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "/artifacts",
    response_model=ArtifactResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "example": {
                        "source": "screenshot",
                        "conversation_id": None,
                        "file": "当前标签页截图 PNG 文件",
                    }
                }
            }
        }
    },
)
async def upload_artifact(
    file: UploadFile = File(...),
    source: ArtifactSource = Form("screenshot"),
    conversation_id: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ArtifactResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件不能为空")
    try:
        artifact = await save_upload_artifact(
            session=session,
            user_id=current_user.id,
            filename=file.filename or "artifact.bin",
            mime_type=file.content_type or "application/octet-stream",
            data=data,
            conversation_id=conversation_id,
            source=source,
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    return ArtifactResponse(
        id=artifact.id,
        filename=artifact.filename,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        version=artifact.version,
        source=artifact.source,
    )


@router.get("/artifacts/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    result = await session.execute(
        select(MessageArtifact).where(
            MessageArtifact.id == artifact_id,
            MessageArtifact.user_id == current_user.id,
        )
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
    part = await load_artifact_part(artifact, settings)
    inline_data = getattr(part, "inline_data", None) if part is not None else None
    data = getattr(inline_data, "data", None)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件内容不存在")
    if isinstance(data, str):
        data = base64.b64decode(data)
    mime_type = getattr(inline_data, "mime_type", None) or artifact.mime_type
    return Response(content=data, media_type=mime_type)


@router.post("/stream")
async def stream_chat(
    payload: ChatStreamRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> EventSourceResponse:
    return EventSourceResponse(stream_chat_response(session, current_user.id, payload, settings))
