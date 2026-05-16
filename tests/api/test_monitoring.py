import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.core.config import get_settings
from app.monitoring.logging import JsonFormatter, SuppressMetricsAccessFilter, TraceIdFilter
from app.monitoring.trace_context import reset_trace_id, set_trace_id


@pytest.mark.asyncio
async def test_metrics_endpoint_is_disabled_by_default(client: AsyncClient):
    response = await client.get("/metrics")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_metrics_endpoint_is_available_when_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROMETHEUS_ENABLED", "true")
    get_settings.cache_clear()
    try:
        app = create_app(get_settings())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            response = await http_client.get("/metrics")

        assert response.status_code == 200
        assert "python_info" in response.text
    finally:
        get_settings.cache_clear()


def test_json_formatter_includes_trace_id():
    token = set_trace_id("trace-test")
    try:
        record = logging.LogRecord("summarix", logging.INFO, __file__, 1, "hello %s", ("world",), None)
        TraceIdFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_trace_id(token)

    assert payload["message"] == "hello world"
    assert payload["trace_id"] == "trace-test"


def test_metrics_access_log_is_suppressed_only_for_metrics_path():
    access_filter = SuppressMetricsAccessFilter("/metrics")
    metrics_record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:12345", "GET", "/metrics", "1.1", 200),
        None,
    )
    health_record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:12345", "GET", "/health", "1.1", 200),
        None,
    )

    assert access_filter.filter(metrics_record) is False
    assert access_filter.filter(health_record) is True
