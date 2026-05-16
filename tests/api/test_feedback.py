import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import MessageFeedback
from app.db.session import AsyncSessionLocal
from app.monitoring.feedback import LangWatchAnnotationResult


def parse_sse_events(body: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        payload: dict[str, str] = {}
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event: "):
                payload["event"] = line.removeprefix("event: ")
            if line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
        if payload:
            payload["data"] = "\n".join(data_lines)
            events.append(payload)
    return events


async def create_feedback_target(authenticated_client: AsyncClient) -> tuple[str, str, str, str]:
    response = await authenticated_client.post("/api/chat/stream", json={"message": "请总结页面", "context": None, "artifact_ids": []})
    assert response.status_code == 200
    events = parse_sse_events(response.text)
    conversation_payload = json.loads(next(event for event in events if event["event"] == "conversation")["data"])
    persisted_payload = json.loads(next(event for event in events if event["event"] == "persisted")["data"])
    return (
        conversation_payload["id"],
        conversation_payload["user_message_id"],
        persisted_payload["assistant_message_id"],
        persisted_payload["trace_id"],
    )


@pytest.mark.asyncio
async def test_feedback_requires_authentication(client: AsyncClient):
    response = await client.post("/api/feedback", json={"message_id": "missing", "rating": "like"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_feedback_records_and_updates_assistant_message(authenticated_client: AsyncClient):
    conversation_id, _, assistant_message_id, trace_id = await create_feedback_target(authenticated_client)

    response = await authenticated_client.post(
        "/api/feedback",
        json={"message_id": assistant_message_id, "rating": "like", "trace_id": trace_id, "comment": "回答有帮助"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message_id"] == assistant_message_id
    assert payload["rating"] == "like"
    assert payload["score"] == 1
    assert payload["trace_id"] == trace_id
    assert payload["langwatch_synced"] is False
    assert payload["langwatch_sync_status"] == "disabled"

    update_response = await authenticated_client.post(
        "/api/feedback",
        json={"message_id": assistant_message_id, "rating": "dislike", "trace_id": trace_id},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["id"] == payload["id"]
    assert updated["rating"] == "dislike"
    assert updated["score"] == -1

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(MessageFeedback).where(MessageFeedback.message_id == assistant_message_id))
        feedback_items = result.scalars().all()
    assert len(feedback_items) == 1
    assert feedback_items[0].rating == "dislike"

    detail_response = await authenticated_client.get(f"/api/history/{conversation_id}")
    assert detail_response.status_code == 200
    assistant = detail_response.json()["messages"][1]
    assert assistant["feedback"]["rating"] == "dislike"
    assert assistant["feedback"]["trace_id"] == trace_id


@pytest.mark.asyncio
async def test_feedback_rejects_user_message(authenticated_client: AsyncClient):
    _, user_message_id, _, trace_id = await create_feedback_target(authenticated_client)

    response = await authenticated_client.post(
        "/api/feedback",
        json={"message_id": user_message_id, "rating": "like", "trace_id": trace_id},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "只能评价助手回复"


@pytest.mark.asyncio
async def test_feedback_uses_langwatch_annotation_result(authenticated_client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _, _, assistant_message_id, trace_id = await create_feedback_target(authenticated_client)
    captured: dict[str, object] = {}

    async def fake_annotation(*args, **kwargs):
        captured.update(kwargs)
        return LangWatchAnnotationResult(status="synced", annotation_id="annotation-1")

    monkeypatch.setattr("app.api.routers.feedback.create_langwatch_annotation", fake_annotation)

    response = await authenticated_client.post(
        "/api/feedback",
        json={"message_id": assistant_message_id, "rating": "like", "trace_id": trace_id, "comment": "很好"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["langwatch_synced"] is True
    assert payload["langwatch_annotation_id"] == "annotation-1"
    assert captured["trace_id"] == trace_id
    assert captured["is_thumbs_up"] is True
    assert captured["comment"] == "很好"
