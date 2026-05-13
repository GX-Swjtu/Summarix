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
        context = (
            {
                "page_url": "https://example.com/history-reference",
                "page_title": "历史参考页面",
                "page_text": "历史详情应保留这段网页正文作为本轮对话依据。",
            }
            if index == 1
            else None
        )
        stream_response = await authenticated_client.post(
            "/api/chat/stream",
            json={"message": f"记录这次对话 {index}", "context": context, "artifact_ids": [artifact["id"]] if index == 0 else []},
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

    page_reference_conversation = next(item for item in [*page["items"], *next_page["items"]] if item["title"] == "历史参考页面")
    page_reference_response = await authenticated_client.get(f"/api/history/{page_reference_conversation['id']}")
    assert page_reference_response.status_code == 200
    page_reference_detail = page_reference_response.json()
    page_reference_artifact = page_reference_detail["messages"][0]["artifacts"][0]
    assert page_reference_artifact["source"] == "page_text"
    assert page_reference_artifact["page_url"] == "https://example.com/history-reference"
    assert page_reference_artifact["page_title"] == "历史参考页面"
    assert "历史详情应保留" in page_reference_artifact["text_excerpt"]
