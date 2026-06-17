"""Track in-flight SSE chat generations for stop/disconnect persistence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from app.database import SessionLocal
from app.models import Message
from app.schemas import SourceItem
from app.services.rag_chain import normalize_source_items

STOPPED_FALLBACK = "已停止生成。"


@dataclass
class ChatGenerationState:
    session_id: str
    request_id: str
    tokens: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    completed: bool = False
    cancelled: bool = False
    persisted: bool = False

    def append_token(self, text: str) -> None:
        if text:
            self.tokens.append(text)

    def set_sources(self, data: list[dict]) -> None:
        self.sources = list(data or [])

    @property
    def answer_text(self) -> str:
        return "".join(self.tokens)

    def mark_completed(self) -> None:
        self.completed = True

    def mark_cancelled(self) -> None:
        self.cancelled = True

    def apply_client_snapshot(self, content: str, sources: list[dict] | None) -> None:
        """Merge frontend snapshot when backend buffer is still empty or shorter."""
        client_text = (content or "").strip()
        if client_text and len(client_text) > len(self.answer_text.strip()):
            self.tokens = [client_text]
        if sources and not self.sources:
            self.sources = list(sources)


_lock = asyncio.Lock()
_active: dict[str, ChatGenerationState] = {}


async def begin_generation(session_id: str, request_id: str) -> ChatGenerationState:
    async with _lock:
        state = ChatGenerationState(session_id=session_id, request_id=request_id)
        _active[request_id] = state
        return state


async def get_generation(request_id: str) -> ChatGenerationState | None:
    async with _lock:
        return _active.get(request_id)


async def end_generation(request_id: str) -> None:
    async with _lock:
        _active.pop(request_id, None)


def _sources_to_json(sources: list[dict]) -> str | None:
    if not sources:
        return None
    items = [SourceItem(**item) for item in sources]
    normalized = normalize_source_items(items)
    if not normalized:
        return None
    return json.dumps([item.model_dump() for item in normalized], ensure_ascii=False)


def _resolve_answer_text(state: ChatGenerationState, *, error_message: str | None) -> str:
    if error_message:
        return error_message

    answer_text = state.answer_text
    if answer_text.strip():
        return answer_text
    if state.cancelled or not state.completed:
        return STOPPED_FALLBACK
    return answer_text


def _persist_state_locked(state: ChatGenerationState, *, error_message: str | None = None) -> bool:
    if state.persisted:
        return False

    answer_text = _resolve_answer_text(state, error_message=error_message)
    sources_json = None if error_message else _sources_to_json(state.sources)

    db = SessionLocal()
    try:
        db.add(
            Message(
                session_id=state.session_id,
                role="assistant",
                content=answer_text,
                sources=sources_json,
            )
        )
        db.commit()
        state.persisted = True
        return True
    finally:
        db.close()


async def persist_generation(
    state: ChatGenerationState,
    *,
    error_message: str | None = None,
) -> bool:
    async with _lock:
        return _persist_state_locked(state, error_message=error_message)


async def stop_generation(
    session_id: str,
    *,
    request_id: str,
    content: str = "",
    sources: list[dict] | None = None,
) -> tuple[bool, str]:
    """
    Mark an active generation as cancelled and persist partial output.

    Targets a specific in-flight generation by ``request_id`` so concurrent
    streams for the same session do not clobber each other.

    Returns (saved, message).
    """
    async with _lock:
        state = _active.get(request_id)
        if state:
            if state.session_id != session_id:
                return False, "请求 ID 与会话不匹配"
            state.mark_cancelled()
            state.apply_client_snapshot(content, sources)
            saved = _persist_state_locked(state)
            _active.pop(request_id, None)
            return saved, "已停止并保存" if saved else "生成结果已保存"

        client_text = (content or "").strip()
        if not client_text and not sources:
            return False, "没有进行中的生成"

        return await asyncio.to_thread(
            _persist_client_fallback,
            session_id,
            client_text,
            sources,
        )


def _persist_client_fallback(
    session_id: str,
    content: str,
    sources: list[dict] | None,
) -> tuple[bool, str]:
    """
    Fallback when SSE already ended: save client snapshot if the latest message
    is still a user message without a matching assistant reply.
    """
    db = SessionLocal()
    try:
        last_msg = (
            db.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .first()
        )
        if not last_msg or last_msg.role != "user":
            return False, "生成结果已保存"

        answer_text = content or STOPPED_FALLBACK
        sources_json = _sources_to_json(sources or [])

        db.add(
            Message(
                session_id=session_id,
                role="assistant",
                content=answer_text,
                sources=sources_json,
            )
        )
        db.commit()
        return True, "已停止并保存"
    finally:
        db.close()
