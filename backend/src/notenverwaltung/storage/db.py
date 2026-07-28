"""Connection management and schema migration.

The coursework version opened a fresh :func:`sqlite3.connect` inside every store
method. That caused three distinct defects, all with the same root cause:

1. ``PRAGMA foreign_keys = ON`` is **per-connection**. Setting it during table
   creation did nothing for the connections that later performed writes, so foreign
   keys were never actually enforced.
2. Loading N grades opened N*2+1 connections, because each row re-fetched its student
   and course through the public API.
3. ``commit()`` could land outside the ``with sqlite3.connect(...)`` block that owned
   the transaction, silently discarding the write.

All three disappear once a connection is created in exactly one place, configured
once, and injected. That is what this module does.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"
"""Repository-level ``backend/migrations`` directory."""


def connect(database: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a correctly configured SQLite connection.

    This is the only place in the codebase that calls :func:`sqlite3.connect`.

    Args:
        database: Path to the database file, or ``":memory:"`` for a transient one.
        read_only: Reserved for future read-replica use. Currently advisory.

    Returns:
        A connection with row access by name, foreign keys enforced, and
        write-ahead logging enabled so readers never block on a writer.
    """
    conn = sqlite3.connect(database, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if database != ":memory:":
        # WAL lets readers proceed during a write. Meaningless for in-memory
        # databases, and SQLite rejects it for them.
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection]:
    """Run a block inside one atomic transaction.

    The connection is opened with ``isolation_level=None`` (autocommit), so
    transactions are explicit and always visible in the code rather than implied by
    driver magic. Services wrap each use case in this, which is what makes a write
    and its audit-log entry commit or roll back together.

    Args:
        conn: The connection to run against.

    Yields:
        The same connection, inside an open transaction.

    Raises:
        Exception: Re-raises anything the block raises, after rolling back.
    """
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def apply_migrations(conn: sqlite3.Connection, directory: Path | None = None) -> list[str]:
    """Apply every migration that has not run yet, in filename order.

    Migrations are plain ``.sql`` files named ``NNN_description.sql``. Applied
    versions are recorded in ``schema_migrations`` so re-running is a no-op.

    Args:
        conn: The connection to migrate.
        directory: Where to read migrations from. Defaults to :data:`MIGRATIONS_DIR`.

    Returns:
        The versions applied by this call, in order. Empty if already up to date.

    Raises:
        FileNotFoundError: If the migrations directory does not exist.
    """
    directory = directory or MIGRATIONS_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"Migrations directory not found: {directory}")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL"
        ")"
    )
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}

    newly_applied: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        # executescript() issues its own COMMIT, so it cannot run inside our
        # transaction() helper. Each migration is therefore its own unit of work —
        # which is the behaviour you want anyway: a failure stops the run with
        # earlier migrations durably applied.
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )
        newly_applied.append(version)

    return newly_applied
