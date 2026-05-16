import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_and_update_model_settings(authenticated_client: AsyncClient):
    get_response = await authenticated_client.get("/api/settings/models")
    assert get_response.status_code == 200
    initial_payload = get_response.json()
    assert initial_payload["theme"] == "default"
    defaults = initial_payload["defaults"]
    assert defaults["theme"] == "default"
    assert defaults["conversation_model"] == "dashscope/qwen3.5-flash"
    assert "vision_analysis_model" not in defaults
    assert defaults["xiaohongshu_model"] == "dashscope/qwen3.5-flash"
    assert defaults["short_video_script_model"] == "dashscope/qwen3.5-flash"
    assert defaults["suggested_questions_model"] == "dashscope/qwen3.5-flash"
    assert defaults["conversation_thinking_mode"] == "default"
    assert defaults["text_summary_thinking_mode"] == "default"
    assert defaults["xiaohongshu_thinking_mode"] == "default"
    assert defaults["short_video_script_thinking_mode"] == "default"
    assert defaults["suggested_questions_thinking_mode"] == "disabled"

    update_response = await authenticated_client.put(
        "/api/settings/models",
        json={
            "theme": "dark",
            "text_summary_model": "dashscope/qwen3.5-flash",
            "conversation_model": "dashscope/qwen3.5-flash",
            "xiaohongshu_model": "dashscope/qwen-xhs",
            "short_video_script_model": "dashscope/qwen-video",
            "suggested_questions_model": "dashscope/qwen-suggestions",
            "conversation_thinking_mode": "enabled",
            "text_summary_thinking_mode": "disabled",
            "xiaohongshu_thinking_mode": "default",
            "short_video_script_thinking_mode": "enabled",
            "suggested_questions_thinking_mode": "disabled",
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert "vision_analysis_model" not in payload
    assert payload["theme"] == "dark"
    assert payload["xiaohongshu_model"] == "dashscope/qwen-xhs"
    assert payload["short_video_script_model"] == "dashscope/qwen-video"
    assert payload["suggested_questions_model"] == "dashscope/qwen-suggestions"
    assert payload["conversation_thinking_mode"] == "enabled"
    assert payload["text_summary_thinking_mode"] == "disabled"
    assert payload["xiaohongshu_thinking_mode"] == "default"
    assert payload["short_video_script_thinking_mode"] == "enabled"
    assert payload["suggested_questions_thinking_mode"] == "disabled"

    persisted_response = await authenticated_client.get("/api/settings/models")
    assert persisted_response.status_code == 200
    assert persisted_response.json()["theme"] == "dark"


@pytest.mark.asyncio
async def test_reject_invalid_theme(authenticated_client: AsyncClient):
    response = await authenticated_client.put(
        "/api/settings/models",
        json={
            "theme": "sepia",
            "conversation_thinking_mode": "default",
            "text_summary_thinking_mode": "default",
            "xiaohongshu_thinking_mode": "default",
            "short_video_script_thinking_mode": "default",
            "suggested_questions_thinking_mode": "disabled",
        },
    )
    assert response.status_code == 422
