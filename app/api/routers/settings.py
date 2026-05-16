from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import AvailableModelOption, ModelSettingsRequest, ModelSettingsResponse
from app.core.config import ChatModelDefinition, Settings, get_settings, normalize_thinking_mode
from app.db.models import User, UserModelPreference
from app.db.session import get_db_session

router = APIRouter(prefix="/settings", tags=["settings"])


def is_external_icon_url(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().lower()
    return normalized.startswith(("http://", "https://", "data:", "blob:"))


def normalize_model_asset_path(icon_url: str, settings: Settings) -> str | None:
    normalized = icon_url.strip().replace("\\", "/").lstrip("/")
    if not normalized or is_external_icon_url(normalized):
        return normalized or None
    asset_root_name = settings.model_asset_root_path.name.replace("\\", "/").strip("/")
    if asset_root_name and normalized.startswith(f"{asset_root_name}/"):
        normalized = normalized[len(asset_root_name) + 1 :]
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized or None


def resolve_model_icon_url(model: ChatModelDefinition, settings: Settings, request: Request | None = None) -> str | None:
    if not model.icon_url:
        return None
    if is_external_icon_url(model.icon_url):
        return model.icon_url
    asset_path = normalize_model_asset_path(model.icon_url, settings)
    if not asset_path:
        return None
    if request is None:
        return model.icon_url
    return str(request.url_for("get_model_asset", asset_path=asset_path))


def serialize_available_model(
    model: ChatModelDefinition,
    settings: Settings,
    request: Request | None = None,
) -> AvailableModelOption:
    return AvailableModelOption(
        id=model.id,
        name=model.name,
        description=model.description,
        is_premium=model.is_premium,
        icon_url=resolve_model_icon_url(model, settings, request),
        supports_thinking_config=model.supports_thinking_config,
        default_thinking_mode=model.default_thinking_mode,
    )


def resolve_primary_model(preference: UserModelPreference | None, settings: Settings) -> ChatModelDefinition:
    if preference is not None:
        model = settings.find_model_definition(preference.primary_model_id)
        if model is not None:
            return model
        model = settings.find_model_definition(preference.conversation_model)
        if model is not None:
            return model
    return settings.effective_primary_model_definition


def resolve_primary_thinking_mode(preference: UserModelPreference | None, model: ChatModelDefinition) -> str:
    if not model.supports_thinking_config:
        return "default"
    return normalize_thinking_mode(preference.primary_thinking_mode if preference else None, model.default_thinking_mode)


def build_settings_response(
    preference: UserModelPreference | None,
    settings: Settings,
    request: Request | None = None,
) -> ModelSettingsResponse:
    primary_model = resolve_primary_model(preference, settings)
    default_model = settings.effective_primary_model_definition
    suggested_model = settings.effective_suggested_questions_model_definition
    return ModelSettingsResponse(
        theme=(preference.theme if preference else None) or "default",
        primary_model_id=primary_model.id,
        primary_thinking_mode=resolve_primary_thinking_mode(preference, primary_model),
        available_models=[serialize_available_model(model, settings, request) for model in settings.model_catalog],
        defaults={
            "primary_model_id": default_model.id,
            "primary_model": default_model.litellm_model,
            "primary_thinking_mode": default_model.default_thinking_mode,
            "suggested_questions_model_id": suggested_model.id,
            "suggested_questions_model": suggested_model.litellm_model,
            "suggested_questions_thinking_mode": settings.effective_suggested_questions_thinking_mode,
            "theme": "default",
        },
    )


@router.get("/models", response_model=ModelSettingsResponse)
async def get_model_settings(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ModelSettingsResponse:
    result = await session.execute(select(UserModelPreference).where(UserModelPreference.user_id == current_user.id))
    return build_settings_response(result.scalar_one_or_none(), settings, request)


@router.put("/models", response_model=ModelSettingsResponse)
async def update_model_settings(
    request: Request,
    payload: ModelSettingsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ModelSettingsResponse:
    result = await session.execute(select(UserModelPreference).where(UserModelPreference.user_id == current_user.id))
    preference = result.scalar_one_or_none()
    requested_model = settings.find_model_definition(payload.primary_model_id) if payload.primary_model_id else settings.effective_primary_model_definition
    if requested_model is None:
        raise HTTPException(status_code=422, detail="选择的主力模型不存在")
    if not requested_model.supports_thinking_config and payload.primary_thinking_mode != "default":
        raise HTTPException(status_code=422, detail="该模型不支持配置深度思考模式")
    if preference is None:
        preference = UserModelPreference(user_id=current_user.id)
        session.add(preference)
    preference.primary_model_id = payload.primary_model_id
    preference.primary_thinking_mode = payload.primary_thinking_mode
    preference.theme = payload.theme
    await session.commit()
    await session.refresh(preference)
    return build_settings_response(preference, settings, request)


@router.get("/assets/{asset_path:path}", include_in_schema=False, name="get_model_asset")
async def get_model_asset(asset_path: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    normalized = normalize_model_asset_path(asset_path, settings)
    if not normalized:
        raise HTTPException(status_code=404, detail="图标不存在")
    asset_root = settings.model_asset_root_path
    resolved_path = (asset_root / Path(normalized)).resolve()
    if resolved_path != asset_root and asset_root not in resolved_path.parents:
        raise HTTPException(status_code=404, detail="图标不存在")
    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="图标不存在")
    return FileResponse(resolved_path)
