"""Tests for startup schema migrations."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.migrations import get_applied_revisions, run_migrations
from app.migrations.base import column_exists
from app.migrations.versions import MIGRATIONS


def _legacy_engine():
    """Simulate an older database created before new columns existed."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE knowledge_bases (
                    id VARCHAR(36) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    description TEXT,
                    collection_name VARCHAR(200) NOT NULL UNIQUE,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE documents (
                    id VARCHAR(36) PRIMARY KEY,
                    knowledge_base_id VARCHAR(36) NOT NULL,
                    filename VARCHAR(500) NOT NULL,
                    file_type VARCHAR(20) NOT NULL,
                    file_path VARCHAR(1000) NOT NULL,
                    file_size INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    return engine


def test_run_migrations_adds_missing_columns_on_legacy_db() -> None:
    engine = _legacy_engine()

    assert not column_exists(engine, "documents", "processing_version")
    assert not column_exists(engine, "knowledge_bases", "rebuild_version")

    applied = run_migrations(engine)

    assert applied == [migration.revision for migration in MIGRATIONS]
    assert column_exists(engine, "documents", "processing_version")
    assert column_exists(engine, "knowledge_bases", "rebuild_version")
    assert get_applied_revisions(engine) == {migration.revision for migration in MIGRATIONS}


def test_run_migrations_is_idempotent() -> None:
    engine = _legacy_engine()

    first = run_migrations(engine)
    second = run_migrations(engine)

    assert first == [migration.revision for migration in MIGRATIONS]
    assert second == []


def test_init_db_path_runs_migrations_after_create_all(monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr("app.database.engine", engine)
    monkeypatch.setattr(
        "app.database.SessionLocal",
        sessionmaker(bind=engine),
    )

    calls: list[str] = []

    def fake_run_migrations(db_engine):
        assert db_engine is engine
        calls.append("migrations")
        return []

    def fake_ensure_default(db):
        calls.append("default_kb")

    monkeypatch.setattr("app.migrations.run_migrations", fake_run_migrations)
    monkeypatch.setattr(
        "app.services.knowledge_base_service.ensure_default_knowledge_base",
        fake_ensure_default,
    )

    from app.database import init_db

    init_db()

    assert calls == ["migrations", "default_kb"]
