"""Request-scoped context for correlating logs and client-facing errors."""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def generate_request_id() -> str:
    """Create a short correlation id for one chat request."""
    return uuid.uuid4().hex[:12]


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(request_id: str) -> Token:
    return _request_id.set(request_id)


def reset_request_id(token: Token) -> None:
    _request_id.reset(token)


@contextmanager
def bind_request_id(request_id: str):
    """Bind request_id to the current context (sync or async task)."""
    token = set_request_id(request_id)
    try:
        yield request_id
    finally:
        reset_request_id(token)


class RequestIdFilter(logging.Filter):
    """Inject ``record.request_id`` for log formatters."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


def setup_request_logging() -> None:
    """Attach request_id filter and formatter to root handlers."""
    log_format = "%(asctime)s %(levelname)s [%(request_id)s] [%(name)s] %(message)s"
    formatter = logging.Formatter(log_format)
    request_filter = RequestIdFilter()

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        handler = logging.StreamHandler()
        root.addHandler(handler)
    for handler in root.handlers:
        handler.setFormatter(formatter)
        if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
            handler.addFilter(request_filter)
