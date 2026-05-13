import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_and_update_model_settings(authenticated_client: AsyncClient):
    get_response = await authenticated_client.get("/api/settings/models")
    assert get_response.status_code == 200
    defaults = get_response.json()["defaults"]
    assert defaults["conversation_model"] == "dashscope/qwen3.5-flash"
    assert defaults["xiaohongshu_model"] == "dashscope/qwen3.5-flash"
    assert defaults["short_video_script_model"] == "dashscope/qwen3.5-flash"

    update_response = await authenticated_client.put(
        "/api/settings/models",
        json={
            "text_summary_model": "dashscope/qwen3.5-flash",
            "vision_analysis_model": "dashscope/qwen3.5-flash",
            "conversation_model": "dashscope/qwen3.5-flash",
            "xiaohongshu_model": "dashscope/qwen-xhs",
            "short_video_script_model": "dashscope/qwen-video",
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["vision_analysis_model"] == "dashscope/qwen3.5-flash"
    assert payload["xiaohongshu_model"] == "dashscope/qwen-xhs"
    assert payload["short_video_script_model"] == "dashscope/qwen-video"
