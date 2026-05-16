from types import SimpleNamespace

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