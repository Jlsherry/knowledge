"""Structured API error codes and helpers."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException

# ---------- Error codes ----------

KB_EMPTY = "KB_EMPTY"
DOCS_PROCESSING = "DOCS_PROCESSING"
KB_NOT_READY = "KB_NOT_READY"
MODEL_TIMEOUT = "MODEL_TIMEOUT"
MODEL_RATE_LIMIT = "MODEL_RATE_LIMIT"
MODEL_ERROR = "MODEL_ERROR"
RERANK_DEGRADED = "RERANK_DEGRADED"
NETWORK_ERROR = "NETWORK_ERROR"
SERVER_ERROR = "SERVER_ERROR"
NOT_FOUND = "NOT_FOUND"

DEFAULT_MESSAGES: dict[str, str] = {
    KB_EMPTY: "知识库中还没有文档，请先上传后再提问。",
    DOCS_PROCESSING: "文档正在解析或向量化，请稍候再试。",
    KB_NOT_READY: "知识库中暂无可用文档，请检查文档处理状态。",
    MODEL_TIMEOUT: "模型响应超时，请稍后重试。",
    MODEL_RATE_LIMIT: "模型调用过于频繁，请稍后再试。",
    MODEL_ERROR: "模型调用失败，请稍后重试。",
    RERANK_DEGRADED: "相关性重排序暂不可用，已使用基础检索结果。",
    NETWORK_ERROR: "网络连接异常，请检查网络后重试。",
    SERVER_ERROR: "服务暂时不可用，请稍后重试。",
    NOT_FOUND: "请求的资源不存在。",
}


def error_detail(
    code: str,
    message: str | None = None,
    *,
    request_id: str | None = None,
) -> dict[str, str]:
    detail = {
        "code": code,
        "message": message or DEFAULT_MESSAGES.get(code, DEFAULT_MESSAGES[SERVER_ERROR]),
    }
    if request_id:
        detail["request_id"] = request_id
    return detail


def raise_api_error(
    code: str,
    status_code: int = 400,
    message: str | None = None,
    *,
    request_id: str | None = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=error_detail(code, message, request_id=request_id),
    )


def classify_chat_exception(exc: Exception) -> tuple[str, str]:
    """Map upstream LLM / network exceptions to user-facing error codes."""
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return MODEL_TIMEOUT, DEFAULT_MESSAGES[MODEL_TIMEOUT]

    msg = str(exc).lower()
    if any(token in msg for token in ("timeout", "timed out", "time out", "deadline")):
        return MODEL_TIMEOUT, DEFAULT_MESSAGES[MODEL_TIMEOUT]
    if any(token in msg for token in ("rate limit", "throttl", "too many requests", "quota")):
        return MODEL_RATE_LIMIT, DEFAULT_MESSAGES[MODEL_RATE_LIMIT]
    if any(token in msg for token in ("connection", "connect", "network", "unreachable")):
        return NETWORK_ERROR, DEFAULT_MESSAGES[NETWORK_ERROR]

    return MODEL_ERROR, DEFAULT_MESSAGES[MODEL_ERROR]
