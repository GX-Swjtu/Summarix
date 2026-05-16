from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, chat, feedback, history, settings as settings_router
from app.core.config import Settings, get_settings
from app.db.init import create_all_tables
from app.monitoring.langwatch import setup_langwatch
from app.monitoring.logging import configure_logging
from app.monitoring.metrics import configure_fastapi_metrics


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.database_auto_create_tables:
        await create_all_tables()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    setup_langwatch(settings)
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        responses={401: {"description": "未登录或登录已过期"}},
    )
    configure_fastapi_metrics(app, settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.effective_cors_allow_origins,
        allow_origin_regex=settings.effective_cors_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(chat.router, prefix=settings.api_prefix)
    app.include_router(feedback.router, prefix=settings.api_prefix)
    app.include_router(history.router, prefix=settings.api_prefix)
    app.include_router(settings_router.router, prefix=settings.api_prefix)
    return app


app = create_app()
