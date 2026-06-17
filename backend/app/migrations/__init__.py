"""Lightweight schema migrations for SQLite (applied on app startup)."""

from app.migrations.runner import get_applied_revisions, run_migrations

__all__ = ["get_applied_revisions", "run_migrations"]
