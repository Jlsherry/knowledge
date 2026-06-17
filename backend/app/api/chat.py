"""多轮对话 API，支持 SSE 流式输出。"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.errors import NOT_FOUND, classify_chat_exception, error_detail, raise_api_error
from app.models import ChatSession, Message
from app.schemas import (
    ApiResponse,
    ChatRequest,
    ChatResponse,
    ChatStopRequest,
    MessageResponse,
    SessionCreate,
    SessionResponse,
    SourceItem,
)
from app.services.chat_generation import begin_generation, end_generation, persist_generation, stop_generation
from app.services.kb_readiness import ensure_kb_ready_for_chat
from app.services.knowledge_base_service import get_default_knowledge_base
from app.services.rag_chain import chat, chat_stream, normalize_source_items
from app.request_context import bind_request_id, generate_request_id, reset_request_id, set_request_id

router = APIRouter(prefix="/api/sessions", tags=["对话"])
logger = logging.getLogger(__name__)


def _get_session_or_404(session_id: str, db: Session) -> ChatSession:
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise_api_error(NOT_FOUND, status_code=404, message="会话不存在")
    return session


def _load_chat_history(db: Session, session_id: str) -> list[tuple[str, str]]:
    """
    加载会话历史消息，按时间正序排列。

    仅保留最近 N 轮（由 MAX_HISTORY_TURNS 配置），避免 token 超限。
    """
    settings = get_settings()
    max_messages = settings.max_history_turns * 2

    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    if len(messages) > max_messages:
        messages = messages[-max_messages:]

    return [(m.role, m.content) for m in messages]


def _parse_sources(raw: str | None) -> list[SourceItem] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        items = [SourceItem(**item) for item in data]
        return normalize_source_items(items)
    except (json.JSONDecodeError, TypeError):
        return None


def _message_to_response(msg: Message) -> MessageResponse:
    return MessageResponse(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        sources=_parse_sources(msg.sources),
        created_at=msg.created_at,
    )


def _maybe_set_title_from_question(session: ChatSession, question: str, db: Session) -> None:
    """
    首次提问时，用用户问题作为会话标题（替换默认「新对话」）。

    标题最长 200 字符，超出部分截断。
    """
    if session.title != "新对话":
        return
    title = question.strip().replace("\n", " ")
    if not title:
        return
    session.title = title[:200]
    db.commit()


@router.post("", summary="创建对话会话")
def create_session(body: SessionCreate, db: Session = Depends(get_db)) -> ApiResponse:
    """
    创建新的多轮对话会话，自动绑定默认知识库。

    - **title**: 会话标题（默认「新对话」）
    """
    kb = get_default_knowledge_base(db)

    session = ChatSession(
        knowledge_base_id=kb.id,
        title=body.title or "新对话",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return ApiResponse(data=SessionResponse.model_validate(session))


@router.get("", summary="会话列表")
def list_sessions(db: Session = Depends(get_db)) -> ApiResponse:
    """获取所有对话会话列表。"""
    sessions = db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
    return ApiResponse(data=[SessionResponse.model_validate(s) for s in sessions])


@router.get("/{session_id}/messages", summary="会话历史消息")
def get_messages(session_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    """获取指定会话的全部历史消息。"""
    _get_session_or_404(session_id, db)
    messages = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return ApiResponse(data=[_message_to_response(m) for m in messages])


@router.delete("/{session_id}", summary="删除对话会话")
def delete_session(session_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    """
    删除指定对话会话及其全部历史消息。

    关联消息会级联删除。
    """
    session = _get_session_or_404(session_id, db)
    db.delete(session)
    db.commit()
    return ApiResponse(message="对话已删除")


@router.post("/{session_id}/chat/stop", summary="停止流式生成并保存")
async def stop_chat_stream(
    session_id: str,
    body: ChatStopRequest,
    db: Session = Depends(get_db),
) -> ApiResponse:
    """
    停止当前会话进行中的 SSE 生成，并将已生成内容持久化为 assistant 消息。

    前端在用户点击「停止生成」时应调用此接口，然后再 abort SSE 连接。
    """
    _get_session_or_404(session_id, db)
    sources_payload = (
        [item.model_dump() for item in body.sources]
        if body.sources
        else None
    )
    saved, message = await stop_generation(
        session_id,
        request_id=body.request_id,
        content=body.content,
        sources=sources_payload,
    )
    logger.info(
        "chat stream stopped request_id=%s session_id=%s saved=%s content_len=%s sources=%s",
        body.request_id,
        session_id,
        saved,
        len(body.content or ""),
        len(body.sources or []),
    )
    return ApiResponse(message=message, data={"saved": saved})


@router.post("/{session_id}/chat", summary="发送消息（支持 SSE 流式）")
async def send_message(
    session_id: str,
    body: ChatRequest,
    db: Session = Depends(get_db),
):
    """
    向指定会话发送用户消息，基于 RAG 生成回答。

    - **stream=true**（默认）：返回 `text/event-stream`，事件 data 为 JSON
      - `{"type":"token","content":"..."}` 增量文本
      - `{"type":"sources","data":[...]}` 引用来源
      - `{"type":"done"}` 结束
    - **stream=false**：返回完整 JSON 响应
    """
    session = _get_session_or_404(session_id, db)
    kb = get_default_knowledge_base(db)
    request_id = generate_request_id()
    request_start = time.perf_counter()

    try:
        ensure_kb_ready_for_chat(db, kb.id)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        detail["request_id"] = request_id
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc

    # 先加载历史（不含当前问题），再保存用户消息
    history = _load_chat_history(db, session_id)
    logger.info(
        "chat request received request_id=%s session_id=%s stream=%s question_len=%s history_messages=%s",
        request_id,
        session_id,
        body.stream,
        len(body.message),
        len(history),
    )

    user_msg = Message(session_id=session_id, role="user", content=body.message)
    db.add(user_msg)
    db.commit()

    # 首次提问：用用户问题更新会话标题
    _maybe_set_title_from_question(session, body.message, db)

    if body.stream:
        return StreamingResponse(
            _sse_generator(session_id, kb.collection_name, body.message, history, request_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Request-ID": request_id,
            },
        )

    with bind_request_id(request_id):
        try:
            answer, sources = chat(kb.collection_name, body.message, history)
        except Exception as exc:
            logger.exception(
                "chat request failed session_id=%s elapsed=%.3fs",
                session_id,
                time.perf_counter() - request_start,
            )
            code, message = classify_chat_exception(exc)
            raise HTTPException(
                status_code=500,
                detail=error_detail(code, message, request_id=request_id),
            ) from exc

        sources_json = json.dumps([s.model_dump() for s in sources], ensure_ascii=False)

        assistant_msg = Message(
            session_id=session_id,
            role="assistant",
            content=answer,
            sources=sources_json,
        )
        db.add(assistant_msg)
        db.commit()
        logger.info(
            "chat request finished session_id=%s stream=false answer_len=%s sources=%s elapsed=%.3fs",
            session_id,
            len(answer),
            len(sources),
            time.perf_counter() - request_start,
        )

        return ApiResponse(
            data=ChatResponse(answer=answer, sources=sources),
        )


async def _sse_generator(
    session_id: str,
    collection_name: str,
    question: str,
    history: list[tuple[str, str]],
    request_id: str,
):
    """
    SSE 事件生成器：流式推送 token，结束后持久化 assistant 消息。

    流式响应生命周期较长，此处单独创建 DB 会话，避免请求级 session 提前关闭。
    客户端断开或调用 /chat/stop 时，也会尽量保存已生成内容。
    """
    token = set_request_id(request_id)
    state = await begin_generation(session_id, request_id)
    start = time.perf_counter()
    stream_error_code: str | None = None
    stream_error_message: str | None = None

    yield (
        "data: "
        + json.dumps(
            {"type": "start", "request_id": request_id},
            ensure_ascii=False,
        )
        + "\n\n"
    )

    try:
        async for event_json in chat_stream(collection_name, question, history):
            event = json.loads(event_json)
            event_type = event.get("type")

            if event_type == "token":
                state.append_token(event.get("content", ""))
            elif event_type == "sources":
                state.set_sources(event.get("data", []))
            elif event_type == "done":
                state.mark_completed()

            yield f"data: {event_json}\n\n"
    except asyncio.CancelledError:
        state.mark_cancelled()
        logger.info(
            "chat stream cancelled request_id=%s session_id=%s answer_len=%s elapsed=%.3fs",
            request_id,
            session_id,
            len(state.answer_text),
            time.perf_counter() - start,
        )
        raise
    except Exception as exc:
        logger.exception(
            "chat stream failed request_id=%s session_id=%s answer_len=%s elapsed=%.3fs",
            request_id,
            session_id,
            len(state.answer_text),
            time.perf_counter() - start,
        )
        stream_error_code, stream_error_message = classify_chat_exception(exc)
        error_json = json.dumps(
            {
                "type": "error",
                "code": stream_error_code,
                "message": stream_error_message,
                "request_id": request_id,
            },
            ensure_ascii=False,
        )
        yield f"data: {error_json}\n\n"
    finally:
        if not state.persisted:
            if not state.completed and not state.cancelled:
                state.mark_cancelled()
            await persist_generation(state, error_message=stream_error_message)
            logger.info(
                "chat stream persisted request_id=%s session_id=%s completed=%s cancelled=%s answer_len=%s sources=%s elapsed=%.3fs",
                request_id,
                session_id,
                state.completed,
                state.cancelled,
                len(state.answer_text),
                len(state.sources),
                time.perf_counter() - start,
            )
        await end_generation(request_id)
        reset_request_id(token)
