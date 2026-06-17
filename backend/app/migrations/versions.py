"""Registered schema migrations (append-only, ordered by revision)."""

from __future__ import annotations

from sqlalchemy.engine import Connection, Engine

from app.migrations.base import Migration, add_sqlite_column_if_missing


def _upgrade_001_documents_processing_version(engine: Engine, conn: Connection) -> None:
    add_sqlite_column_if_missing(
        engine,
        conn,
        "documents",
        "processing_version",
        "processing_version INTEGER NOT NULL DEFAULT 0",
    )


def _upgrade_002_kb_rebuild_version(engine: Engine, conn: Connection) -> None:
    add_sqlite_column_if_missing(
        engine,
        conn,
        "knowledge_bases",
        "rebuild_version",
        "rebuild_version INTEGER NOT NULL DEFAULT 0",
    )


MIGRATIONS: list[Migration] = [
    Migration(
        revision="001_documents_processing_version",
        description="Add documents.processing_version for stale job protection",
        upgrade=_upgrade_001_documents_processing_version,
    ),
    Migration(
        revision="002_knowledge_bases_rebuild_version",
        description="Add knowledge_bases.rebuild_version for async full rebuild jobs",
        upgrade=_upgrade_002_kb_rebuild_version,
    ),
]
