"""Tests for SSE stream error events and persistence."""

from __future__ import annotations

import json

import pytest

from app.api.chat import _sse_generator
from app.errors import MODEL_TIMEOUT
from app.models import Message
from app.services.chat_generation import get_generation


async def _collect_sse_events(**kwargs) -> list[dict]:
    events: list[dict] = []
    async for chunk in _sse_generator(**kwargs):
        for line in chunk.strip().splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_sse_emits_start_and_error_with_request_id(
    monkeypatch,
    patch_session_local,
    sample_chat,
) -> None:
    session, _user_msg = sample_chat
    request_id = "req-sse-error"

    async def failing_stream(*_args, **_kwargs):
        yield json.dumps({"type": "token", "content": "partial "}, ensure_ascii=False)
        raise TimeoutError("model timed out")

    monkeypatch.setattr("app.api.chat.chat_stream", failing_stream)

    events = await _collect_sse_events(
        session_id=session.id,
        collection_name="kb_test_collection",
        question="hello",
        history=[],
        request_id=request_id,
    )

    assert events[0] == {"type": "start", "request_id": request_id}

    error_event = next(event for event in events if event.get("type") == "error")
    assert error_event["code"] == MODEL_TIMEOUT
    assert error_event["request_id"] == request_id
    assert error_event["message"]

    assert await get_generation(request_id) is None


@pytest.mark.asyncio
async def test_sse_error_persists_assistant_message(
    monkeypatch,
    patch_session_local,
    db_session,
    sample_chat,
) -> None:
    session, _user_msg = sample_chat
    request_id = "req-sse-persist"

    async def failing_stream(*_args, **_kwargs):
        yield json.dumps({"type": "token", "content": "partial"}, ensure_ascii=False)
        raise TimeoutError("model timed out")

    monkeypatch.setattr("app.api.chat.chat_stream", failing_stream)

    await _collect_sse_events(
        session_id=session.id,
        collection_name="kb_test_collection",
        question="hello",
        history=[],
        request_id=request_id,
    )

    assistant = (
        db_session.query(Message)
        .filter(Message.session_id == session.id, Message.role == "assistant")
        .one()
    )
    assert "超时" in assistant.content
