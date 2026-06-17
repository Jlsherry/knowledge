"""Tests for chat stop/persist keyed by request_id."""

from __future__ import annotations

import pytest

from app.models import Message
from app.services.chat_generation import (
    begin_generation,
    get_generation,
    stop_generation,
)


@pytest.mark.asyncio
async def test_stop_persists_partial_answer(
    patch_session_local,
    db_session,
    sample_chat,
) -> None:
    session, _user_msg = sample_chat
    request_id = "req-stop-1"

    state = await begin_generation(session.id, request_id)
    state.append_token("hello")

    saved, message = await stop_generation(
        session.id,
        request_id=request_id,
        content="hello world",
        sources=[{"content": "source", "filename": "a.txt"}],
    )

    assert saved is True
    assert "已停止" in message
    assert await get_generation(request_id) is None

    assistant = (
        db_session.query(Message)
        .filter(Message.session_id == session.id, Message.role == "assistant")
        .one()
    )
    assert assistant.content == "hello world"
    assert assistant.sources is not None


@pytest.mark.asyncio
async def test_stop_rejects_mismatched_session(patch_session_local) -> None:
    await begin_generation("session-a", "req-1")

    saved, message = await stop_generation(
        "session-b",
        request_id="req-1",
        content="partial",
    )

    assert saved is False
    assert "不匹配" in message
    assert await get_generation("req-1") is not None


@pytest.mark.asyncio
async def test_stop_without_active_generation_and_empty_content() -> None:
    saved, message = await stop_generation(
        "missing-session",
        request_id="missing-req",
        content="",
    )

    assert saved is False
    assert message == "没有进行中的生成"


@pytest.mark.asyncio
async def test_stop_fallback_persists_when_stream_already_ended(
    patch_session_local,
    db_session,
    sample_chat,
) -> None:
    session, _user_msg = sample_chat

    saved, message = await stop_generation(
        session.id,
        request_id="already-finished",
        content="client snapshot",
    )

    assert saved is True
    assert "已停止" in message

    assistant = (
        db_session.query(Message)
        .filter(Message.session_id == session.id, Message.role == "assistant")
        .one()
    )
    assert assistant.content == "client snapshot"
