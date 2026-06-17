"""Migration types and SQLite helper utilities."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

SchemaBind = Engine | Connection


@dataclass(frozen=True)
class Migration:
    revision: str
    description: str
    upgrade: Callable[[Engine, Connection], None]


def table_exists(bind: SchemaBind, table_name: str) -> bool:
    return inspect(bind).has_table(table_name)


def column_exists(bind: SchemaBind, table_name: str, column_name: str) -> bool:
    if not table_exists(bind, table_name):
        return False
    columns = {col["name"] for col in inspect(bind).get_columns(table_name)}
    return column_name in columns


def add_sqlite_column_if_missing(
    engine: Engine,
    conn: Connection,
    table_name: str,
    column_name: str,
    column_ddl: str,
) -> bool:
    """
    Add a column when missing.

    Returns True when ALTER TABLE was executed.
    """
    if column_exists(conn, table_name, column_name):
        return False
    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_ddl}"))
    logger.info("migration added column %s.%s", table_name, column_name)
    return True
