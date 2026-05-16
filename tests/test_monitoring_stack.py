import json

import pytest

import scripts.monitoring_stack as monitoring_stack

from scripts.monitoring_stack import (
    build_generated_env,
    build_persisted_env,
    ensure_langwatch_api_key_configured,
    is_langwatch_api_key,
    normalize_public_url_for_https,
    upsert_env_value,
)


def test_build_generated_env_uses_shared_postgres_defaults(monkeypatch) -> None:
    for key in ("LANGWATCH_ENABLED", "PORT", "SUMMARIX_BACKEND_PORT"):
        monkeypatch.delenv(key, raising=False)

    persisted = build_persisted_env({}, {}, {})
    values = build_generated_env({}, {}, persisted, {})

    expected_password = persisted["SUMMARIX_POSTGRES_PASSWORD"]

    assert values["DATABASE_URL"] == f"postgresql+asyncpg://summarix:{expected_password}@postgres:5432/summarix"
    assert values["ADK_DATABASE_URL"] == f"postgresql+asyncpg://summarix:{expected_password}@postgres:5432/summarix"
    assert values["LANGWATCH_DATABASE_URL"] == f"postgresql://summarix:{expected_password}@postgres:5432/summarix?schema=langwatch"
    assert values["LANGWATCH_REDIS_URL"] == "redis://redis:6379"
    assert values["PROMETHEUS_ENABLED"] == "true"
    assert values["LANGWATCH_ENABLED"] == "true"
    assert values["LANGWATCH_APP_METRICS_TARGET"] == "langwatch-app:5560"
    assert values["LANGWATCH_WORKERS_METRICS_TARGET"] == "langwatch-workers:2999"
    assert len(values["METRICS_API_KEY"]) >= 32
    assert len(values["JWT_SECRET_KEY"]) >= 32


def test_build_generated_env_respects_existing_ports_and_urls(monkeypatch) -> None:
    for key in (
        "CHAT_AGENT_MODE",
        "PORT",
        "SUMMARIX_BACKEND_PORT",
        "LANGWATCH_ENABLED",
        "LANGWATCH_PUBLIC_URL",
        "BASE_HOST",
        "NEXTAUTH_URL",
        "LOG_LEVEL",
        "LANGWATCH_REDIS_URL",
        "SUMMARIX_POSTGRES_DB",
        "SUMMARIX_POSTGRES_USER",
        "SUMMARIX_POSTGRES_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    persisted = build_persisted_env({}, {}, {"JWT_SECRET_KEY": "x" * 32})
    values = build_generated_env(
        {
            "SUMMARIX_BACKEND_PORT": "8010",
            "LANGWATCH_PUBLIC_URL": "http://127.0.0.1:6600",
            "LOG_LEVEL": "DEBUG",
        },
        {"LANGWATCH_REDIS_URL": "redis://custom-redis:6379"},
        {
            **persisted,
            "SUMMARIX_POSTGRES_DB": "demo",
            "SUMMARIX_POSTGRES_USER": "demo_user",
            "SUMMARIX_POSTGRES_PASSWORD": "demo_pass",
        },
        {"DASHSCOPE_API_KEY": "sk-demo"},
    )

    assert values["SUMMARIX_BACKEND_PORT"] == "8010"
    assert values["LANGWATCH_PUBLIC_URL"] == "https://127.0.0.1:6600"
    assert values["BASE_HOST"] == "https://127.0.0.1:6600"
    assert values["NEXTAUTH_URL"] == "https://127.0.0.1:6600"
    assert values["LOG_LEVEL"] == "DEBUG"
    assert values["DATABASE_URL"] == "postgresql+asyncpg://demo_user:demo_pass@postgres:5432/demo"
    assert values["LANGWATCH_REDIS_URL"] == "redis://custom-redis:6379"
    assert values["DASHSCOPE_API_KEY"] == "sk-demo"
    assert values["CHAT_AGENT_MODE"] == "adk"


def test_build_generated_env_rewrites_local_langwatch_endpoint_for_docker_runtime() -> None:
    persisted = build_persisted_env({}, {}, {"JWT_SECRET_KEY": "x" * 32})

    values = build_generated_env(
        {
            "LANGWATCH_ENDPOINT": "http://127.0.0.1:5560",
            "LANGWATCH_PUBLIC_URL": "http://127.0.0.1:5560",
        },
        {},
        persisted,
        {},
    )

    assert values["LANGWATCH_ENDPOINT"] == "http://langwatch:5560"
    assert values["LANGWATCH_PUBLIC_URL"] == "https://127.0.0.1:5560"


def test_build_generated_env_uses_fallback_backend_port_when_8000_is_occupied(monkeypatch) -> None:
    monkeypatch.delenv("SUMMARIX_BACKEND_PORT", raising=False)
    monkeypatch.setattr(monitoring_stack, "host_port_available", lambda port: port == "18000")

    persisted = build_persisted_env({}, {}, {})
    values = build_generated_env({}, {}, persisted, {})

    assert values["SUMMARIX_BACKEND_PORT"] == "18000"


def test_build_generated_env_enables_langwatch_for_monitoring_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LANGWATCH_ENABLED", raising=False)

    persisted = build_persisted_env({}, {}, {})
    values = build_generated_env({"LANGWATCH_ENABLED": "false"}, {}, persisted, {})

    assert values["LANGWATCH_ENABLED"] == "true"


def test_build_generated_env_respects_explicit_langwatch_env_override(monkeypatch) -> None:
    monkeypatch.setenv("LANGWATCH_ENABLED", "false")

    persisted = build_persisted_env({}, {}, {})
    values = build_generated_env({}, {}, persisted, {})

    assert values["LANGWATCH_ENABLED"] == "false"


def test_build_generated_env_respects_custom_langwatch_metrics_targets() -> None:
    persisted = build_persisted_env({}, {}, {"JWT_SECRET_KEY": "x" * 32})

    values = build_generated_env(
        {
            "LANGWATCH_APP_METRICS_TARGET": "custom-langwatch-app:7000",
            "LANGWATCH_WORKERS_METRICS_TARGET": "custom-langwatch-workers:7999",
        },
        {},
        persisted,
        {},
    )

    assert values["LANGWATCH_APP_METRICS_TARGET"] == "custom-langwatch-app:7000"
    assert values["LANGWATCH_WORKERS_METRICS_TARGET"] == "custom-langwatch-workers:7999"


def test_build_generated_env_allows_overriding_langwatch_tls_certificate_paths() -> None:
    persisted = build_persisted_env({}, {}, {"JWT_SECRET_KEY": "x" * 32})

    values = build_generated_env(
        {
            "LANGWATCH_TLS_CERT_FILE": "/etc/ssl/certs/langwatch.crt",
            "LANGWATCH_TLS_KEY_FILE": "/etc/ssl/private/langwatch.key",
        },
        {},
        persisted,
        {},
    )

    assert values["LANGWATCH_TLS_CERT_FILE"] == "/etc/ssl/certs/langwatch.crt"
    assert values["LANGWATCH_TLS_KEY_FILE"] == "/etc/ssl/private/langwatch.key"


def test_normalize_public_url_for_https_rewrites_plain_http() -> None:
    assert normalize_public_url_for_https("http://127.0.0.1:5560") == "https://127.0.0.1:5560"
    assert normalize_public_url_for_https("https://127.0.0.1:5560") == "https://127.0.0.1:5560"


def test_build_persisted_env_reuses_existing_strong_secrets() -> None:
    persisted = build_persisted_env(
        {"JWT_SECRET_KEY": "legacy-root-secret-1234567890-abcdefgh"},
        {"NEXTAUTH_SECRET": "legacy-nextauth-secret-1234567890-abcdefgh"},
        {
            "JWT_SECRET_KEY": "persisted-jwt-secret-1234567890-abcdefgh",
            "METRICS_API_KEY": "persisted-metrics-secret-1234567890-abcdefgh",
            "SUMMARIX_POSTGRES_PASSWORD": "persisted-db-password",
        },
    )

    assert persisted["JWT_SECRET_KEY"] == "persisted-jwt-secret-1234567890-abcdefgh"
    assert persisted["NEXTAUTH_SECRET"] == "legacy-nextauth-secret-1234567890-abcdefgh"
    assert persisted["METRICS_API_KEY"] == "persisted-metrics-secret-1234567890-abcdefgh"
    assert persisted["SUMMARIX_POSTGRES_PASSWORD"] == "persisted-db-password"


def test_build_generated_env_without_api_key_falls_back_to_mock() -> None:
    persisted = build_persisted_env({}, {}, {})

    values = build_generated_env({}, {}, persisted, {})

    assert values["CHAT_AGENT_MODE"] == "mock"


def test_build_generated_env_uses_named_volume_for_clickhouse_on_windows(monkeypatch) -> None:
    monkeypatch.setattr("scripts.monitoring_stack.platform.system", lambda: "Windows")

    persisted = build_persisted_env({}, {}, {})
    values = build_generated_env({}, {}, persisted, {})

    assert values["LANGWATCH_CLICKHOUSE_DATA_SOURCE"] == "langwatch-clickhouse-data"


def test_build_generated_env_keeps_bind_mount_for_clickhouse_on_linux(monkeypatch) -> None:
    monkeypatch.setattr("scripts.monitoring_stack.platform.system", lambda: "Linux")

    persisted = build_persisted_env({}, {}, {})
    values = build_generated_env({}, {}, persisted, {})

    assert values["LANGWATCH_CLICKHOUSE_DATA_SOURCE"] == "../data/langwatch/clickhouse"


def test_is_langwatch_api_key_matches_expected_format() -> None:
    assert is_langwatch_api_key("sk-lw-demo-key-1234567890") is True
    assert is_langwatch_api_key("sk-demo") is False
    assert is_langwatch_api_key("") is False


def test_ensure_langwatch_api_key_configured_reuses_existing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitoring_stack, "env_value", lambda name, values, default=None: values.get(name, default))

    api_key = ensure_langwatch_api_key_configured(
        {
            "LANGWATCH_API_KEY": "sk-lw-existing-demo-key",
            "LANGWATCH_PUBLIC_URL": "https://127.0.0.1:5560",
        }
    )

    assert api_key == "sk-lw-existing-demo-key"


def test_ensure_langwatch_api_key_configured_persists_prompted_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    env_file = tmp_path / ".env.api.key"
    monkeypatch.setattr(monitoring_stack, "API_KEY_ENV", env_file)
    monkeypatch.setattr(monitoring_stack, "env_value", lambda name, values, default=None: values.get(name, default))
    monkeypatch.setattr(monitoring_stack.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(monitoring_stack.getpass, "getpass", lambda prompt: "sk-lw-prompted-demo-key")

    api_key = ensure_langwatch_api_key_configured(
        {
            "LANGWATCH_PUBLIC_URL": "https://127.0.0.1:5560",
        }
    )

    assert api_key == "sk-lw-prompted-demo-key"
    assert "LANGWATCH_API_KEY=sk-lw-prompted-demo-key" in env_file.read_text(encoding="utf-8")


def test_ensure_langwatch_api_key_configured_returns_none_when_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(monitoring_stack, "env_value", lambda name, values, default=None: values.get(name, default))
    monkeypatch.setattr(monitoring_stack.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(monitoring_stack.getpass, "getpass", lambda prompt: "skip")

    api_key = ensure_langwatch_api_key_configured(
        {
            "LANGWATCH_PUBLIC_URL": "https://127.0.0.1:5560",
        }
    )

    assert api_key is None


def test_ensure_langwatch_api_key_configured_returns_none_without_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitoring_stack, "env_value", lambda name, values, default=None: values.get(name, default))
    monkeypatch.setattr(monitoring_stack.sys.stdin, "isatty", lambda: False)

    api_key = ensure_langwatch_api_key_configured(
        {
            "LANGWATCH_PUBLIC_URL": "https://127.0.0.1:5560",
        }
    )

    assert api_key is None


def test_upsert_env_value_updates_existing_key(tmp_path) -> None:
    env_file = tmp_path / ".env.api.key"
    env_file.write_text("DASHSCOPE_API_KEY=sk-old\nLANGWATCH_API_KEY=old\n", encoding="utf-8")

    upsert_env_value(env_file, "LANGWATCH_API_KEY", "sk-lw-new")

    assert env_file.read_text(encoding="utf-8") == "DASHSCOPE_API_KEY=sk-old\nLANGWATCH_API_KEY=sk-lw-new\n"


def test_check_plg_rejects_missing_langwatch_rule_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        monitoring_stack,
        "effective_runtime_values",
        lambda: {
            "PROMETHEUS_PORT": "9090",
            "LOKI_PORT": "3100",
            "GRAFANA_PORT": "3000",
            "GRAFANA_ADMIN_USER": "admin",
            "GRAFANA_ADMIN_PASSWORD": "secret",
            "SUMMARIX_METRICS_TARGET": "summarix-backend:8000",
            "LANGWATCH_APP_METRICS_TARGET": "langwatch-app:5560",
            "LANGWATCH_WORKERS_METRICS_TARGET": "langwatch-workers:2999",
        },
    )
    monkeypatch.setattr(monitoring_stack, "wait_http", lambda *args, **kwargs: (200, "ok"))
    monkeypatch.setattr(monitoring_stack, "compose_service_running", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        monitoring_stack,
        "wait_grafana_dashboards",
        lambda *args, **kwargs: {
            dashboard_uid: {"dashboard": {"title": dashboard_uid}}
            for dashboard_uid in kwargs["dashboard_uids"]
        },
    )

    def fake_fetch_json(url: str, **kwargs):
        if url.endswith("/api/v1/targets"):
            return {
                "data": {
                    "activeTargets": [
                        {"labels": {"job": "summarix-backend"}, "health": "up"},
                        {"labels": {"job": "langwatch-app"}, "health": "up"},
                        {"labels": {"job": "langwatch-workers"}, "health": "up"},
                    ]
                }
            }
        if url.endswith("/api/datasources"):
            return [{"name": "Prometheus"}, {"name": "Loki"}]
        if url.endswith("/api/v1/rules"):
            return {"data": {"groups": [{"name": "summarix-only"}]}}
        raise AssertionError(url)

    monkeypatch.setattr(monitoring_stack, "fetch_json", fake_fetch_json)

    with pytest.raises(monitoring_stack.CheckError, match="langwatch-self-hosted"):
        monitoring_stack.check_plg()


def test_check_plg_accepts_langwatch_rule_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        monitoring_stack,
        "effective_runtime_values",
        lambda: {
            "PROMETHEUS_PORT": "9090",
            "LOKI_PORT": "3100",
            "GRAFANA_PORT": "3000",
            "GRAFANA_ADMIN_USER": "admin",
            "GRAFANA_ADMIN_PASSWORD": "secret",
            "SUMMARIX_METRICS_TARGET": "summarix-backend:8000",
            "LANGWATCH_APP_METRICS_TARGET": "langwatch-app:5560",
            "LANGWATCH_WORKERS_METRICS_TARGET": "langwatch-workers:2999",
        },
    )
    monkeypatch.setattr(monitoring_stack, "wait_http", lambda *args, **kwargs: (200, "ok"))
    monkeypatch.setattr(monitoring_stack, "compose_service_running", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        monitoring_stack,
        "wait_grafana_dashboards",
        lambda *args, **kwargs: {
            dashboard_uid: {"dashboard": {"title": dashboard_uid}}
            for dashboard_uid in kwargs["dashboard_uids"]
        },
    )

    def fake_fetch_json(url: str, **kwargs):
        if url.endswith("/api/v1/targets"):
            return {
                "data": {
                    "activeTargets": [
                        {"labels": {"job": "summarix-backend"}, "health": "up"},
                        {"labels": {"job": "langwatch-app"}, "health": "up"},
                        {"labels": {"job": "langwatch-workers"}, "health": "up"},
                    ]
                }
            }
        if url.endswith("/api/datasources"):
            return [{"name": "Prometheus"}, {"name": "Loki"}]
        if url.endswith("/api/v1/rules"):
            return {"data": {"groups": [{"name": "langwatch-self-hosted"}]}}
        raise AssertionError(url)

    monkeypatch.setattr(monitoring_stack, "fetch_json", fake_fetch_json)

    monitoring_stack.check_plg()


def test_start_plg_stack_falls_back_when_host_metrics_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], tuple[str, ...], bool]] = []

    monkeypatch.setattr(monitoring_stack, "host_metrics_profiles", lambda *args, **kwargs: ["host-metrics"])

    def fake_run_compose(compose_files, *args, profiles=None, capture=False, check=True):
        calls.append((tuple(args), tuple(profiles or []), check))
        if args == ("up", "-d", "--remove-orphans") and profiles == ["host-metrics"]:
            raise monitoring_stack.CheckError("cadvisor 拉取失败")
        return None

    monkeypatch.setattr(monitoring_stack, "run_compose", fake_run_compose)

    monitoring_stack.start_plg_stack()

    assert calls == [
        (("up", "-d", "--remove-orphans"), ("host-metrics",), True),
        (("down", "--remove-orphans"), ("host-metrics",), False),
        (("up", "-d", "--remove-orphans"), (), True),
    ]


def test_start_backend_stack_skips_build_when_local_image_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []

    monkeypatch.setattr(monitoring_stack, "docker_image_exists", lambda image_name: True)
    monkeypatch.setattr(monitoring_stack, "env_flag_enabled", lambda *args, **kwargs: False)

    def fake_run_compose(compose_files, *args, **kwargs):
        calls.append((tuple(args), kwargs.get("check", True)))

    monkeypatch.setattr(monitoring_stack, "run_compose", fake_run_compose)

    monitoring_stack.start_backend_stack({"SUMMARIX_BACKEND_IMAGE": "summarix-backend:latest"})

    assert calls == [(("up", "-d", "--remove-orphans"), True)]


def test_start_backend_stack_builds_when_local_image_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []

    monkeypatch.setattr(monitoring_stack, "docker_image_exists", lambda image_name: False)
    monkeypatch.setattr(monitoring_stack, "env_flag_enabled", lambda *args, **kwargs: False)

    def fake_run_compose(compose_files, *args, **kwargs):
        calls.append((tuple(args), kwargs.get("check", True)))

    monkeypatch.setattr(monitoring_stack, "run_compose", fake_run_compose)

    monitoring_stack.start_backend_stack({"SUMMARIX_BACKEND_IMAGE": "summarix-backend:latest"})

    assert calls == [(("up", "-d", "--build", "--remove-orphans"), True)]