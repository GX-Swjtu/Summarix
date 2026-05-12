import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_history_list_and_detail(authenticated_client: AsyncClient):
    for index in range(3):
        stream_response = await authenticated_client.post(
            "/api/chat/stream",
            json={"message": f"记录这次对话 {index}", "context": None, "artifact_ids": []},
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
