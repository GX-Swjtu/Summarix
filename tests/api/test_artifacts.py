import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_upload_artifact(authenticated_client: AsyncClient):
    response = await authenticated_client.post(
        "/api/chat/artifacts",
        data={"source": "screenshot"},
        files={"file": ("screen.png", b"png-bytes", "image/png")},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["id"]
    assert payload["filename"] == "screen.png"
    assert payload["mime_type"] == "image/png"
    assert payload["size_bytes"] == 9


@pytest.mark.asyncio
async def test_upload_artifact_rejects_unknown_source(authenticated_client: AsyncClient):
    response = await authenticated_client.post(
        "/api/chat/artifacts",
        data={"source": "unknown"},
        files={"file": ("screen.png", b"png-bytes", "image/png")},
    )
    assert response.status_code == 422
