from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from app.core.config import Settings


logger = logging.getLogger(__name__)

# 指标对象默认为 None；仅在 Prometheus 首次启用时通过 _init_metrics() 懒注册。
# 所有 record_* / observe_* 函数在 None 时均为无操作，无需额外判断。
LLM_REQUESTS_TOTAL: Any = None
LLM_TTFT_SECONDS: Any = None
LLM_DURATION_SECONDS: Any = None
LLM_TOKENS_TOTAL: Any = None
FEEDBACK_TOTAL: Any = None
_metrics_initialized = False


def _metric_or_none(factory: Any, *args: Any, **kwargs: Any) -> Any | None:
    if factory is None:
        return None
    try:
        return factory(*args, **kwargs)
    except ValueError:
        return None


def _init_metrics() -> None:
    """注册所有 prometheus_client 指标对象。只在 Prometheus 启用时调用，且只执行一次。"""
    global _metrics_initialized, LLM_REQUESTS_TOTAL, LLM_TTFT_SECONDS, LLM_DURATION_SECONDS, LLM_TOKENS_TOTAL, FEEDBACK_TOTAL
    if _metrics_initialized:
        return
    _metrics_initialized = True
    try:
        from prometheus_client import Counter, Histogram
    except ImportError:  # pragma: no cover - 依赖缺失时跳过
        return
    LLM_REQUESTS_TOTAL = _metric_or_none(
        Counter,
        "summarix_llm_requests_total",
        "LLM 调用次数。",
        ["operation", "provider", "model", "status"],
    )
    LLM_TTFT_SECONDS = _metric_or_none(
        Histogram,
        "summarix_llm_ttft_seconds",
        "LLM 首字延迟。",
        ["operation", "provider", "model"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    )
    LLM_DURATION_SECONDS = _metric_or_none(
        Histogram,
        "summarix_llm_duration_seconds",
        "LLM 调用总耗时。",
        ["operation", "provider", "model", "status"],
        buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
    )
    LLM_TOKENS_TOTAL = _metric_or_none(
        Counter,
        "summarix_llm_tokens_total",
        "LLM token 使用量。",
        ["operation", "provider", "model", "kind"],
    )
    FEEDBACK_TOTAL = _metric_or_none(
        Counter,
        "summarix_feedback_total",
        "用户反馈提交次数。",
        ["rating", "langwatch_status"],
    )


def model_provider(model_name: str | None) -> str:
    if not model_name:
        return "unknown"
    return model_name.split("/", 1)[0] if "/" in model_name else "unknown"


def configure_fastapi_metrics(app: FastAPI, settings: Settings) -> None:
    if not settings.prometheus_enabled or getattr(app.state, "summarix_prometheus_enabled", False):
        return
    _init_metrics()
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
    except ImportError:  # pragma: no cover - 仅在依赖缺失且显式启用时发生
        logger.warning("Prometheus 已启用，但 prometheus-fastapi-instrumentator 未安装")
        return

    excluded = {"/health", settings.prometheus_metrics_path}
    Instrumentator(excluded_handlers=list(excluded)).instrument(app).expose(
        app,
        endpoint=settings.prometheus_metrics_path,
        include_in_schema=False,
    )
    app.state.summarix_prometheus_enabled = True


def record_llm_request(operation: str, model_name: str | None, status: str) -> None:
    if LLM_REQUESTS_TOTAL is not None:
        LLM_REQUESTS_TOTAL.labels(operation, model_provider(model_name), model_name or "unknown", status).inc()


def observe_llm_ttft(operation: str, model_name: str | None, seconds: float) -> None:
    if LLM_TTFT_SECONDS is not None:
        LLM_TTFT_SECONDS.labels(operation, model_provider(model_name), model_name or "unknown").observe(seconds)


def observe_llm_duration(operation: str, model_name: str | None, status: str, seconds: float) -> None:
    if LLM_DURATION_SECONDS is not None:
        LLM_DURATION_SECONDS.labels(operation, model_provider(model_name), model_name or "unknown", status).observe(seconds)


def record_llm_tokens(operation: str, model_name: str | None, *, prompt_tokens: int | None, completion_tokens: int | None, total_tokens: int | None) -> None:
    if LLM_TOKENS_TOTAL is None:
        return
    labels = (operation, model_provider(model_name), model_name or "unknown")
    if prompt_tokens is not None:
        LLM_TOKENS_TOTAL.labels(*labels, "prompt").inc(prompt_tokens)
    if completion_tokens is not None:
        LLM_TOKENS_TOTAL.labels(*labels, "completion").inc(completion_tokens)
    if total_tokens is not None:
        LLM_TOKENS_TOTAL.labels(*labels, "total").inc(total_tokens)


def record_feedback(rating: str, langwatch_status: str) -> None:
    if FEEDBACK_TOTAL is not None:
        FEEDBACK_TOTAL.labels(rating, langwatch_status).inc()
