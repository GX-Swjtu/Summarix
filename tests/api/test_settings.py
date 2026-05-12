import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_and_update_model_settings(authenticated_client: AsyncClient):
    get_response = await authenticated_client.get("/api/settings/models")
    assert get_response.status_code == 200
    assert get_response.json()["defaults"]["conversation_model"] == "qwen3.5-flash"

    update_response = await authenticated_client.put(
        "/api/settings/models",
        json={
            "text_summary_model": "qwen3.5-flash",
            "vision_analysis_model": "qwen3.5-vl-flash",
            "conversation_model": "qwen3.5-flash",
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["vision_analysis_model"] == "qwen3.5-vl-flash"
