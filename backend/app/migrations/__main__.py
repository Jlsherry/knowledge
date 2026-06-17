"""CLI entry: python -m app.migrations"""

from __future__ import annotations

import argparse

from app.database import engine
from app.migrations import get_applied_revisions, run_migrations
from app.migrations.versions import MIGRATIONS


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage SQLite schema migrations")
    parser.add_argument(
        "command",
        nargs="?",
        default="upgrade",
        choices=["upgrade", "status"],
        help="upgrade: apply pending migrations; status: show migration state",
    )
    args = parser.parse_args()

    if args.command == "status":
        applied = get_applied_revisions(engine)
        for migration in MIGRATIONS:
            state = "applied" if migration.revision in applied else "pending"
            print(f"[{state}] {migration.revision} - {migration.description}")
        return

    applied = run_migrations(engine)
    if applied:
        print("Applied migrations:")
        for revision in applied:
            print(f"  - {revision}")
    else:
        print("No pending migrations.")


if __name__ == "__main__":
    main()
