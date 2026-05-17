from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.monitoring.trace_context import get_trace_id


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = get_trace_id()
        return True


class SuppressMetricsAccessFilter(logging.Filter):
    def __init__(self, metrics_path: str) -> None:
        super().__init__()
        self._metrics_path = metrics_path

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True
        path = self._extract_path(record)
        if path is None:
            return True
        return path.split("?", 1)[0] != self._metrics_path

    @staticmethod
    def _extract_path(record: logging.LogRecord) -> str | None:
        path = getattr(record, "path", None)
        if isinstance(path, str) and path:
            return path
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            return args[2]
        return None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None),
        }
        for key in (
            "method",
            "path",
            "status_code",
            "duration_ms",
            "user_id",
            "conversation_id",
            "model_name",
            "llm_status",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.getLogger().setLevel(level)
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.filters = [
        log_filter for log_filter in access_logger.filters if not isinstance(log_filter, SuppressMetricsAccessFilter)
    ]
    access_logger.addFilter(SuppressMetricsAccessFilter(settings.prometheus_metrics_path))
    if settings.log_format != "json":
        return

    root_logger = logging.getLogger()
    existing = next((handler for handler in root_logger.handlers if getattr(handler, "_summarix_json", False)), None)
    if existing is None:
        handler = logging.StreamHandler()
        handler._summarix_json = True  # type: ignore[attr-defined]
        handler.addFilter(TraceIdFilter())
        handler.setFormatter(JsonFormatter())
        root_logger.handlers = [handler]
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(level)
