from pathlib import Path

from app.core.config import get_settings


def get_chat_artifact_root() -> str:
    settings = get_settings()
    root = Path(settings.chat_artifact_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return str(root)
