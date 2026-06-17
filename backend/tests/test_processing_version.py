"""Tests for processing_version stale-job protection."""

from __future__ import annotations

from langchain_core.documents import Document

from app.services import document_service as svc


def test_is_job_current_false_when_version_bumped(db_session, sample_doc) -> None:
    sample_doc.processing_version = 2
    db_session.commit()

    assert svc._is_job_current(db_session, sample_doc.id, expected_version=1) is False


def test_is_job_current_false_when_document_deleted(db_session, sample_doc) -> None:
    doc_id = sample_doc.id
    db_session.delete(sample_doc)
    db_session.commit()

    assert svc._is_job_current(db_session, doc_id, expected_version=1) is False


def test_process_document_skips_stale_job(db_session, sample_kb, sample_doc) -> None:
    sample_doc.processing_version = 2
    db_session.commit()

    result = svc.process_document(
        db_session,
        sample_doc,
        sample_kb,
        expected_version=1,
    )

    assert result is False
    db_session.refresh(sample_doc)
    assert sample_doc.status == "pending"


def test_process_document_aborts_after_index_when_version_bumped(
    db_session,
    sample_kb,
    sample_doc,
    monkeypatch,
) -> None:
    sample_doc.processing_version = 1
    db_session.commit()
    cleanup_calls: list[str] = []

    monkeypatch.setattr(
        svc,
        "load_document",
        lambda _path, _file_type: [Document(page_content="chunk text")],
    )

    def fake_add(**kwargs):
        sample_doc.processing_version = 2
        db_session.commit()
        return 3

    monkeypatch.setattr(svc, "add_documents_to_store", fake_add)
    monkeypatch.setattr(
        svc,
        "delete_document_chunks",
        lambda _collection, doc_id: cleanup_calls.append(doc_id),
    )

    result = svc.process_document(
        db_session,
        sample_doc,
        sample_kb,
        expected_version=1,
    )

    assert result is False
    assert cleanup_calls == [sample_doc.id]


def test_process_document_by_id_exits_when_version_stale(
    db_session,
    sample_kb,
    sample_doc,
    patch_session_local,
    monkeypatch,
) -> None:
    sample_doc.processing_version = 5
    db_session.commit()
    called = {"process": False}

    def fake_process(*args, **kwargs):
        called["process"] = True
        return True

    monkeypatch.setattr(svc, "process_document", fake_process)

    svc.process_document_by_id(sample_doc.id, sample_kb.id, expected_version=4)

    assert called["process"] is False
