import uvicorn

from app.core.config import get_settings
from app.monitoring.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    uvicorn.run("app.api.app:app", host=settings.host, port=settings.port, reload=settings.should_reload)


if __name__ == "__main__":
    main()
