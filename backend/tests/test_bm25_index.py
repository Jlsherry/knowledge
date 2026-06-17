"""Tests for in-memory BM25 index add/remove/search (no Chroma)."""

from langchain_core.documents import Document

from app.services.bm25_index import (
    BM25Index,
    aggregate_collection_fingerprint,
    chunk_fingerprint,
)


def _doc(
    doc_id: str,
    chunk_index: int,
    text: str,
    *,
    processing_version: int = 1,
) -> Document:
    return Document(
        page_content=text,
        metadata={
            "document_id": doc_id,
            "chunk_index": chunk_index,
            "filename": f"{doc_id}.txt",
            "processing_version": processing_version,
        },
    )


def test_bm25_add_search_remove() -> None:
    index = BM25Index(collection_name="unit-test")
    added = index.add_chunks(
        [
            _doc("d1", 0, "Python programming language tutorial"),
            _doc("d2", 0, "完全无关的中文菜谱内容"),
        ]
    )

    assert added == 2
    assert index.chunk_count == 2
    assert index.collection_fingerprint

    hits = index.search(
        "Python programming",
        top_k=2,
        k1=1.5,
        b=0.75,
    )
    assert hits
    assert hits[0].metadata["document_id"] == "d1"

    removed = index.remove_document("d1")
    assert removed == 1
    assert index.chunk_count == 1

    hits_after_remove = index.search(
        "Python programming",
        top_k=2,
        k1=1.5,
        b=0.75,
    )
    assert all(hit.metadata["document_id"] != "d1" for hit in hits_after_remove)


def test_bm25_fingerprint_changes_with_content_or_version() -> None:
    index = BM25Index(collection_name="unit-test")
    index.add_chunks([_doc("d1", 0, "alpha beta", processing_version=1)])
    first_fp = index.collection_fingerprint

    index.add_chunks([_doc("d1", 0, "alpha gamma", processing_version=1)])
    assert index.collection_fingerprint != first_fp

    index.add_chunks([_doc("d1", 0, "alpha gamma", processing_version=2)])
    assert index.collection_fingerprint != first_fp

    assert chunk_fingerprint("d1", 0, "alpha", 1) != chunk_fingerprint("d1", 0, "alpha", 2)


def test_bm25_clear_resets_fingerprint() -> None:
    index = BM25Index(collection_name="unit-test")
    index.add_chunks([_doc("d1", 0, "hello world")])
    assert index.chunk_count == 1

    index.clear()
    assert index.chunk_count == 0
    assert index.collection_fingerprint == aggregate_collection_fingerprint([])
