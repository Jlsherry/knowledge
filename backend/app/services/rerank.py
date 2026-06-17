"""DashScope rerank service for retrieved document chunks."""

import logging
from http import HTTPStatus

from dashscope import TextReRank
from langchain_core.documents import Document

from app.config import get_settings

logger = logging.getLogger(__name__)


def _mark_rerank_score(doc: Document, score: float | None) -> Document:
    """Attach rerank score to metadata without replacing the Document object."""
    doc.metadata = dict(doc.metadata or {})
    if score is not None:
        doc.metadata["rerank_score"] = score
    return doc


def _fallback_candidates(
    candidate_docs: list[Document],
    *,
    reason: str,
    query: str,
    model: str,
    candidate_count: int,
    status_code: int | None = None,
    exc: BaseException | None = None,
) -> tuple[list[Document], bool]:
    """Return recall-order fallback and emit a warning for observability."""
    settings = get_settings()
    extra = (
        f"query_len={len(query)} candidates={candidate_count} model={model} "
        f"top_n={settings.rerank_top_n}"
    )
    if status_code is not None:
        extra += f" status_code={status_code}"
    if exc is not None:
        logger.warning(
            "rerank degraded (%s): %s; %s; error_type=%s error=%s",
            reason,
            "using recall order",
            extra,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
    else:
        logger.warning(
            "rerank degraded (%s): %s; %s",
            reason,
            "using recall order",
            extra,
        )
    return candidate_docs[: settings.rerank_top_n], True


def rerank_documents(query: str, documents: list[Document]) -> tuple[list[Document], bool]:
    """
    Rerank candidate chunks with DashScope TextReRank.

    Returns (documents, degraded). ``degraded=True`` when falling back to recall order.
    """
    settings = get_settings()
    if not settings.rerank_enabled or not documents:
        return documents[: settings.rerank_top_n], False

    candidate_docs = documents[: settings.rerank_candidate_limit]
    candidate_texts = [doc.page_content for doc in candidate_docs]
    model = settings.rerank_model
    candidate_count = len(candidate_docs)

    try:
        response = TextReRank.call(
            model=model,
            query=query,
            documents=candidate_texts,
            top_n=settings.rerank_top_n,
            api_key=settings.dashscope_api_key,
        )
    except Exception as exc:
        return _fallback_candidates(
            candidate_docs,
            reason="remote_call_failed",
            query=query,
            model=model,
            candidate_count=candidate_count,
            exc=exc,
        )

    status_code = getattr(response, "status_code", None)
    if status_code != HTTPStatus.OK:
        return _fallback_candidates(
            candidate_docs,
            reason="non_ok_status",
            query=query,
            model=model,
            candidate_count=candidate_count,
            status_code=status_code,
        )

    output = getattr(response, "output", None)
    results = getattr(output, "results", None) if output else None
    if not results:
        return _fallback_candidates(
            candidate_docs,
            reason="empty_results",
            query=query,
            model=model,
            candidate_count=candidate_count,
            status_code=status_code,
        )

    reranked: list[Document] = []
    for result in results:
        index = getattr(result, "index", None)
        score = getattr(result, "relevance_score", None)
        if isinstance(index, int) and 0 <= index < len(candidate_docs):
            reranked.append(_mark_rerank_score(candidate_docs[index], score))

    if not reranked:
        return _fallback_candidates(
            candidate_docs,
            reason="no_valid_indexes",
            query=query,
            model=model,
            candidate_count=candidate_count,
            status_code=status_code,
        )
    return reranked, False
