import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.routers.settings import build_settings_response
from app.core.config import Settings, get_settings


@pytest.mark.asyncio
async def test_get_and_update_model_settings(authenticated_client: AsyncClient):
    get_response = await authenticated_client.get("/api/settings/models")
    assert get_response.status_code == 200
    initial_payload = get_response.json()
    assert initial_payload["theme"] == "default"
    assert initial_payload["primary_model_id"] == "default"
    assert initial_payload["primary_thinking_mode"] == "default"
    assert initial_payload["available_models"] == [
        {
            "id": "default",
            "name": "默认模型",
            "description": "后端默认主力模型",
            "is_premium": False,
            "icon_url": None,
            "supports_thinking_config": True,
            "default_thinking_mode": "default",
        }
    ]
    defaults = initial_payload["defaults"]
    assert defaults["theme"] == "default"
    assert defaults["primary_model_id"] == "default"
    assert defaults["primary_model"] == "dashscope/qwen3.5-flash"
    assert defaults["suggested_questions_model"] == "dashscope/qwen3.5-flash"
    assert "api_key" not in json.dumps(initial_payload)

    update_response = await authenticated_client.put(
        "/api/settings/models",
        json={
            "theme": "dark",
            "primary_model_id": "default",
            "primary_thinking_mode": "enabled",
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["theme"] == "dark"
    assert payload["primary_model_id"] == "default"
    assert payload["primary_thinking_mode"] == "enabled"
    assert "conversation_model" not in payload
    assert "suggested_questions_model" not in payload

    persisted_response = await authenticated_client.get("/api/settings/models")
    assert persisted_response.status_code == 200
    persisted = persisted_response.json()
    assert persisted["theme"] == "dark"
    assert persisted["primary_model_id"] == "default"
    assert persisted["primary_thinking_mode"] == "enabled"


@pytest.mark.asyncio
async def test_reject_invalid_theme(authenticated_client: AsyncClient):
    response = await authenticated_client.put(
        "/api/settings/models",
        json={
            "theme": "sepia",
            "primary_model_id": "default",
            "primary_thinking_mode": "default",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_unknown_primary_model(authenticated_client: AsyncClient):
    response = await authenticated_client.put(
        "/api/settings/models",
        json={
            "theme": "default",
            "primary_model_id": "missing-model",
            "primary_thinking_mode": "default",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "选择的主力模型不存在"


def test_model_settings_response_does_not_expose_runtime_secrets():
    settings = Settings(
        jwt_secret_key="x" * 32,
        database_url="sqlite+aiosqlite:///:memory:",
        model_catalog_json=json.dumps(
            [
                {
                    "id": "secure-model",
                    "name": "Secure Model",
                    "description": "管理员配置的模型",
                    "is_premium": True,
                    "icon_url": "https://example.com/icon.png",
                    "api_base": "https://api.example.com/v1",
                    "api_key": "secret-key-value",
                    "litellm_model": "openai/secure-model",
                    "supports_thinking_config": False,
                }
            ]
        ),
    )

    payload = build_settings_response(None, settings).model_dump()

    assert payload["available_models"] == [
        {
            "id": "secure-model",
            "name": "Secure Model",
            "description": "管理员配置的模型",
            "is_premium": True,
            "icon_url": "https://example.com/icon.png",
            "supports_thinking_config": False,
            "default_thinking_mode": "default",
        }
    ]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "secret-key-value" not in serialized
    assert "api.example.com" not in serialized


@pytest.mark.asyncio
async def test_get_model_settings_resolves_local_icon_path_to_backend_asset_url(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    asset_root = tmp_path / "iconResources"
    asset_root.mkdir()
    icon_file = asset_root / "qwen-color.svg"
    icon_file.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    monkeypatch.setenv("MODEL_ASSET_ROOT", str(asset_root))
    monkeypatch.setenv(
        "MODEL_CATALOG_JSON",
        json.dumps(
            {
                "available_models": [
                    {
                        "id": "qwen-flash",
                        "name": "qwen3.5-flash",
                        "description": "高性能通用模型，适合日常使用",
                        "icon_url": "iconResources\\qwen-color.svg",
                        "litellm_model": "dashscope/qwen3.5-flash",
                        "supports_thinking_config": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
    )
    get_settings.cache_clear()

    try:
        app = create_app(get_settings())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            register_response = await client.post(
                "/api/auth/register",
                json={"email": "icon@example.com", "password": "StrongPass123"},
            )
            assert register_response.status_code == 201

            settings_response = await client.get("/api/settings/models")
            assert settings_response.status_code == 200
            payload = settings_response.json()
            assert payload["available_models"][0]["icon_url"] == "http://testserver/api/settings/assets/qwen-color.svg"

            asset_response = await client.get("/api/settings/assets/qwen-color.svg")
            assert asset_response.status_code == 200
            assert "image/svg+xml" in asset_response.headers["content-type"]
            assert "<svg" in asset_response.text
    finally:
        get_settings.cache_clear()
