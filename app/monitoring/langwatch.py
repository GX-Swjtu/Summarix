from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from app.core.config import Settings


logger = logging.getLogger(__name__)
_langwatch_initialized = False


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool = True
    message: str | None = None


def is_langwatch_enabled(settings: Settings) -> bool:
    return settings.langwatch_enabled and bool(settings.langwatch_api_key)


def setup_langwatch(settings: Settings) -> bool:
    global _langwatch_initialized
    if _langwatch_initialized:
        return True
    if not is_langwatch_enabled(settings):
        return False
    try:
        import langwatch
        from openinference.instrumentation.google_adk import GoogleADKInstrumentor
    except ImportError:
        logger.warning("LangWatch 已启用，但 langwatch 或 Google ADK instrumentor 未安装")
        return False

    setup_kwargs: dict[str, Any] = {
        "api_key": settings.langwatch_api_key,
        "instrumentors": [GoogleADKInstrumentor()],
        "debug": settings.langwatch_debug,
    }
    if settings.langwatch_endpoint:
        setup_kwargs["endpoint_url"] = settings.langwatch_endpoint
    langwatch.setup(**setup_kwargs)
    _langwatch_initialized = True
    return True


@contextmanager
def maybe_langwatch_trace(
    settings: Settings,
    *,
    name: str,
    metadata: dict[str, Any],
    input_data: dict[str, Any] | str | None = None,
) -> Iterator[Any | None]:
    if not setup_langwatch(settings):
        yield None
        return
    import langwatch

    with langwatch.trace(name=name, metadata=metadata, input=input_data) as current_trace:
        yield current_trace


def get_langwatch_trace_id(trace: Any | None) -> str | None:
    if trace is None:
        return None
    trace_id = getattr(trace, "trace_id", None)
    if trace_id:
        return str(trace_id)
    span = getattr(trace, "root_span", None) or getattr(trace, "span", None)
    span_context_getter = getattr(span, "get_span_context", None)
    if span_context_getter is None:
        return None
    span_context = span_context_getter()
    raw_trace_id = getattr(span_context, "trace_id", None)
    return format(raw_trace_id, "032x") if raw_trace_id else None


async def evaluate_input_guardrail(settings: Settings, user_input: str) -> GuardrailResult:
    if not (settings.langwatch_guardrails_enabled and settings.langwatch_input_guardrail_slug and setup_langwatch(settings)):
        return GuardrailResult()

    def run_guardrail() -> GuardrailResult:
        import langwatch

        result = langwatch.evaluation.evaluate(
            settings.langwatch_input_guardrail_slug,
            name="Summarix 输入护栏",
            as_guardrail=True,
            data={"input": user_input},
        )
        passed = bool(getattr(result, "passed", True))
        details = getattr(result, "details", None) or getattr(result, "message", None)
        return GuardrailResult(allowed=passed, message=str(details) if details else None)

    try:
        return await asyncio.to_thread(run_guardrail)
    except Exception as exc:
        logger.exception("LangWatch 输入护栏执行失败")
        if settings.langwatch_guardrails_fail_open:
            return GuardrailResult()
        return GuardrailResult(allowed=False, message=str(exc))
