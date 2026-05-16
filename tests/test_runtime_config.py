from types import SimpleNamespace
import json

import pytest

import main as app_main
from app.core.config import Settings


def build_settings(**overrides) -> Settings:
    values = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "database_auto_create_database": False,
        "database_auto_create_tables": False,
        "jwt_secret_key": "x" * 32,
        "chat_agent_mode": "mock",
    }
    values.update(overrides)
    return Settings(**values)


def test_should_reload_defaults_to_true_in_local_env() -> None:
    settings = build_settings(app_env="local")

    assert settings.should_reload is True


def test_should_reload_defaults_to_false_in_non_local_env() -> None:
    settings = build_settings(app_env="production")

    assert settings.should_reload is False


@pytest.mark.parametrize(
    ("app_env", "app_reload", "expected"),
    [
        ("local", False, False),
        ("production", True, True),
    ],
)
def test_explicit_app_reload_overrides_app_env(app_env: str, app_reload: bool, expected: bool) -> None:
    settings = build_settings(app_env=app_env, app_reload=app_reload)

    assert settings.should_reload is expected


def test_main_uses_computed_reload_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    settings = SimpleNamespace(host="127.0.0.1", port=8000, should_reload=False)

    monkeypatch.setattr(app_main, "get_settings", lambda: settings)
    monkeypatch.setattr(app_main, "configure_logging", lambda current_settings: captured.setdefault("settings", current_settings))

    def fake_run(app: str, *, host: str, port: int, reload: bool) -> None:
        captured.update({
            "app": app,
            "host": host,
            "port": port,
            "reload": reload,
        })

    monkeypatch.setattr(app_main.uvicorn, "run", fake_run)

    app_main.main()

    assert captured["settings"] is settings
    assert captured["app"] == "app.api.app:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert captured["reload"] is False


def test_model_catalog_json_resolves_primary_and_suggested_models() -> None:
    settings = build_settings(
        model_catalog_json=json.dumps(
            [
                {
                    "id": "fast",
                    "name": "Fast Model",
                    "description": "快速模型",
                    "is_premium": False,
                    "icon_url": "https://example.com/fast.png",
                    "api_base": "https://fast.example.com/v1",
                    "api_key": "fast-secret",
                    "litellm_model": "openai/fast",
                    "supports_thinking_config": True,
                    "default_thinking_mode": "disabled",
                },
                {
                    "id": "suggestion",
                    "name": "Suggestion Model",
                    "description": "建议问题模型",
                    "is_premium": False,
                    "litellm_model": "openai/suggestion",
                    "supports_thinking_config": False,
                },
            ]
        ),
        default_primary_model_id="fast",
        suggested_questions_model_id="suggestion",
    )

    assert settings.effective_primary_model_definition.id == "fast"
    assert settings.effective_primary_model_definition.litellm_model == "openai/fast"
    assert settings.effective_primary_model_definition.api_key == "fast-secret"
    assert settings.effective_text_model == "openai/fast"
    assert settings.effective_suggested_questions_model_definition.id == "suggestion"
    assert settings.effective_suggested_questions_model == "openai/suggestion"


def test_model_catalog_file_uses_first_available_model_as_default(tmp_path) -> None:
    config_file = tmp_path / "model-catalog.json"
    config_file.write_text(
        json.dumps(
            {
                "available_models": [
                    {
                        "id": "automatic",
                        "name": "Automatic",
                        "description": "自动模型",
                        "litellm_model": "openai/auto",
                        "supports_thinking_config": True,
                        "default_thinking_mode": "enabled",
                    },
                    {
                        "id": "claude-sonnet",
                        "name": "Claude Sonnet",
                        "description": "高级模型",
                        "litellm_model": "anthropic/claude-sonnet",
                        "supports_thinking_config": False,
                    },
                ],
                "suggested_questions_model": {
                    "id": "suggested-light",
                    "name": "Suggested Light",
                    "description": "建议问题轻量模型",
                    "litellm_model": "openai/suggest-light",
                    "supports_thinking_config": True,
                    "default_thinking_mode": "disabled",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = build_settings(
        model_catalog_file=str(config_file),
        default_primary_model_id="claude-sonnet",
        suggested_questions_model_id="automatic",
    )

    assert [model.id for model in settings.model_catalog] == ["automatic", "claude-sonnet"]
    assert settings.effective_primary_model_id == "automatic"
    assert settings.effective_primary_model_definition.litellm_model == "openai/auto"
    assert settings.effective_suggested_questions_model_definition.id == "suggested-light"
    assert settings.effective_suggested_questions_model == "openai/suggest-light"
    assert settings.effective_suggested_questions_thinking_mode == "disabled"


def test_model_catalog_falls_back_to_default_chat_model() -> None:
    settings = build_settings(default_chat_model="dashscope/default-model")

    assert settings.effective_primary_model_id == "default"
    assert settings.model_catalog[0].litellm_model == "dashscope/default-model"
    assert settings.effective_conversation_model == "dashscope/default-model"