import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_history_list_and_detail(authenticated_client: AsyncClient):
    artifact_response = await authenticated_client.post(
        "/api/chat/artifacts",
        data={"source": "upload"},
        files={"file": ("screen.png", b"png-bytes", "image/png")},
    )
    assert artifact_response.status_code == 201
    artifact = artifact_response.json()

    for index in range(3):
        stream_response = await authenticated_client.post(
            "/api/chat/stream",
            json={"message": f"记录这次对话 {index}", "context": None, "artifact_ids": [artifact["id"]] if index == 0 else []},
        )
        assert stream_response.status_code == 200

    list_response = await authenticated_client.get("/api/history?offset=0&limit=2")
    assert list_response.status_code == 200
    page = list_response.json()
    assert page["limit"] == 2
    assert page["offset"] == 0
    assert page["has_more"] is True
    assert len(page["items"]) == 2

    next_page_response = await authenticated_client.get("/api/history?offset=2&limit=2")
    assert next_page_response.status_code == 200
    next_page = next_page_response.json()
    assert next_page["has_more"] is False
    assert len(next_page["items"]) == 1

    detail_response = await authenticated_client.get(f"/api/history/{page['items'][0]['id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert len(detail["messages"]) == 2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][1]["role"] == "assistant"

    artifact_conversation = next(item for item in [*page["items"], *next_page["items"]] if item["title"] == "记录这次对话 0")
    artifact_detail_response = await authenticated_client.get(f"/api/history/{artifact_conversation['id']}")
    assert artifact_detail_response.status_code == 200
    artifact_detail = artifact_detail_response.json()
    assert artifact_detail["messages"][0]["artifacts"][0]["id"] == artifact["id"]
