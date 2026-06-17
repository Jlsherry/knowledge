"""Per-request retrieval warnings (e.g. rerank degradation)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

from app.errors import DEFAULT_MESSAGES, RERANK_DEGRADED


@dataclass
class RetrievalContext:
    warnings: list[dict[str, str]] = field(default_factory=list)

    def add_warning(self, code: str, message: str | None = None) -> None:
        payload = {"code": code, "message": message or DEFAULT_MESSAGES.get(code, code)}
        if payload not in self.warnings:
            self.warnings.append(payload)


_context: ContextVar[RetrievalContext | None] = ContextVar("retrieval_context", default=None)


def begin_retrieval() -> RetrievalContext:
    ctx = RetrievalContext()
    _context.set(ctx)
    return ctx


def get_retrieval_context() -> RetrievalContext | None:
    return _context.get()


def add_retrieval_warning(code: str, message: str | None = None) -> None:
    ctx = _context.get()
    if ctx is not None:
        ctx.add_warning(code, message)


def consume_retrieval_warnings() -> list[dict[str, str]]:
    ctx = _context.get()
    _context.set(None)
    if not ctx:
        return []
    return list(ctx.warnings)


def mark_rerank_degraded() -> None:
    add_retrieval_warning(RERANK_DEGRADED)
