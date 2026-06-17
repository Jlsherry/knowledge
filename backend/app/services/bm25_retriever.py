"""Lightweight BM25 keyword retriever backed by cached inverted index."""

from langchain_core.documents import Document

from app.config import get_settings
from app.services.bm25_index import get_bm25_manager


def bm25_search(collection_name: str, query: str, top_k: int | None = None) -> list[Document]:
    """Return top BM25 chunks using the in-memory index (no per-query Chroma scan)."""
    settings = get_settings()
    limit = top_k or settings.bm25_top_k
    return get_bm25_manager().search(
        collection_name,
        query,
        limit,
        k1=settings.bm25_k1,
        b=settings.bm25_b,
    )
