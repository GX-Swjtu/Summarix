from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import ModelSettingsRequest, ModelSettingsResponse
from app.core.config import Settings, get_settings
from app.db.models import User, UserModelPreference
from app.db.session import get_db_session

router = APIRouter(prefix="/settings", tags=["settings"])


def build_settings_response(preference: UserModelPreference | None, settings: Settings) -> ModelSettingsResponse:
    return ModelSettingsResponse(
        text_summary_model=preference.text_summary_model if preference else None,
        vision_analysis_model=preference.vision_analysis_model if preference else None,
        conversation_model=preference.conversation_model if preference else None,
        defaults={
            "text_summary_model": settings.effective_text_model,
            "vision_analysis_model": settings.effective_vision_model,
            "conversation_model": settings.effective_conversation_model,
        },
    )


@router.get("/models", response_model=ModelSettingsResponse)
async def get_model_settings(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ModelSettingsResponse:
    result = await session.execute(select(UserModelPreference).where(UserModelPreference.user_id == current_user.id))
    return build_settings_response(result.scalar_one_or_none(), settings)


@router.put("/models", response_model=ModelSettingsResponse)
async def update_model_settings(
    payload: ModelSettingsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ModelSettingsResponse:
    result = await session.execute(select(UserModelPreference).where(UserModelPreference.user_id == current_user.id))
    preference = result.scalar_one_or_none()
    if preference is None:
        preference = UserModelPreference(user_id=current_user.id)
        session.add(preference)
    preference.text_summary_model = payload.text_summary_model
    preference.vision_analysis_model = payload.vision_analysis_model
    preference.conversation_model = payload.conversation_model
    await session.commit()
    await session.refresh(preference)
    return build_settings_response(preference, settings)
