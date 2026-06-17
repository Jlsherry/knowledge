"""Shared pytest fixtures (in-memory SQLite, no real KB data)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import ChatSession, Document, KnowledgeBase, Message


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    session = sessionmaker(bind=db_engine)()
    yield session
    session.close()


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine)


@pytest.fixture
def patch_session_local(session_factory, monkeypatch):
    """Route service-layer DB access to the in-memory test database."""
    monkeypatch.setattr("app.database.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.chat_generation.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.document_service.SessionLocal", session_factory)


@pytest.fixture(autouse=True)
def reset_chat_generations():
    import app.services.chat_generation as chat_generation

    chat_generation._active.clear()
    yield
    chat_generation._active.clear()


@pytest.fixture
def sample_kb(db_session) -> KnowledgeBase:
    kb = KnowledgeBase(
        id="kb-test",
        name="测试知识库",
        collection_name="kb_test_collection",
    )
    db_session.add(kb)
    db_session.commit()
    return kb


@pytest.fixture
def sample_doc(db_session, sample_kb, tmp_path) -> Document:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("sample content", encoding="utf-8")
    doc = Document(
        id="doc-test",
        knowledge_base_id=sample_kb.id,
        filename="notes.txt",
        file_type="txt",
        file_path=str(file_path),
        file_size=file_path.stat().st_size,
        status="pending",
        processing_version=0,
    )
    db_session.add(doc)
    db_session.commit()
    return doc


@pytest.fixture
def sample_chat(db_session, sample_kb) -> tuple[ChatSession, Message]:
    session = ChatSession(
        id="session-test",
        knowledge_base_id=sample_kb.id,
        title="测试会话",
    )
    user_message = Message(
        id="msg-user",
        session_id=session.id,
        role="user",
        content="你好",
    )
    db_session.add(session)
    db_session.add(user_message)
    db_session.commit()
    return session, user_message
