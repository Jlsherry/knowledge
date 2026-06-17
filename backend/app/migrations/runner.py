"""Apply versioned schema migrations and track them in ``schema_migrations``."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.migrations.versions import MIGRATIONS

logger = logging.getLogger(__name__)

MIGRATIONS_TABLE = "schema_migrations"


def _ensure_migrations_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                revision VARCHAR(64) PRIMARY KEY,
                description VARCHAR(500) NOT NULL,
                applied_at DATETIME NOT NULL
            )
            """
        )
    )


def get_applied_revisions(engine: Engine) -> set[str]:
    inspector = inspect(engine)
    if not inspector.has_table(MIGRATIONS_TABLE):
        return set()

    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT revision FROM {MIGRATIONS_TABLE}")).fetchall()
    return {row[0] for row in rows}


def run_migrations(engine: Engine) -> list[str]:
    """
    Apply pending migrations in revision order.

    Returns the list of newly applied revision ids.
    """
    applied_now: list[str] = []

    with engine.begin() as conn:
        _ensure_migrations_table(conn)
        applied = {
            row[0]
            for row in conn.execute(text(f"SELECT revision FROM {MIGRATIONS_TABLE}")).fetchall()
        }

        for migration in MIGRATIONS:
            if migration.revision in applied:
                continue

            logger.info(
                "Applying migration %s: %s",
                migration.revision,
                migration.description,
            )
            migration.upgrade(engine, conn)
            conn.execute(
                text(
                    f"""
                    INSERT INTO {MIGRATIONS_TABLE} (revision, description, applied_at)
                    VALUES (:revision, :description, :applied_at)
                    """
                ),
                {
                    "revision": migration.revision,
                    "description": migration.description,
                    "applied_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(
                        sep=" ", timespec="seconds"
                    ),
                },
            )
            applied_now.append(migration.revision)

    if applied_now:
        logger.info("Schema migrations applied: %s", ", ".join(applied_now))
    return applied_now
