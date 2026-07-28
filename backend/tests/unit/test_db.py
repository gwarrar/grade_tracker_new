"""Connection configuration, transactions and the migration runner.

These cover the root cause of three defects in the coursework version: foreign keys
that were never enforced, N+1 connection churn, and a commit outside its transaction.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from notenverwaltung.storage import apply_migrations, connect, transaction


class TestConnect:
    def test_foreign_keys_are_actually_enforced(self) -> None:
        """The pragma is per-connection. Setting it during table creation did nothing
        for the connections that later performed writes, so the coursework version
        accepted grades referencing students that did not exist."""
        conn = connect(":memory:")
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        conn.close()

    def test_rows_are_accessible_by_column_name(self) -> None:
        conn = connect(":memory:")
        row = conn.execute("SELECT 1 AS answer").fetchone()
        assert row["answer"] == 1
        conn.close()

    def test_wal_is_enabled_for_file_databases(self, tmp_path: Path) -> None:
        """WAL lets readers proceed during a write — the reason SQLite is sufficient here."""
        conn = connect(tmp_path / "test.db")
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        conn.close()

    def test_in_memory_databases_skip_wal(self) -> None:
        """SQLite rejects WAL for in-memory databases; requesting it would raise."""
        conn = connect(":memory:")
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "memory"
        conn.close()


class TestTransaction:
    def test_commits_on_success(self, sqlite_conn: sqlite3.Connection) -> None:
        with transaction(sqlite_conn):
            sqlite_conn.execute(
                "INSERT INTO students (student_id, first_name, last_name, email)"
                " VALUES ('S1', 'A', 'B', 'a@b.co')"
            )
        assert sqlite_conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 1

    def test_rolls_back_on_failure(self, sqlite_conn: sqlite3.Connection) -> None:
        """A use case that fails halfway must leave nothing behind — this is what makes
        a write and its audit-log entry atomic."""
        with pytest.raises(RuntimeError), transaction(sqlite_conn):
            sqlite_conn.execute(
                "INSERT INTO students (student_id, first_name, last_name, email)"
                " VALUES ('S1', 'A', 'B', 'a@b.co')"
            )
            raise RuntimeError("use case failed")

        assert sqlite_conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0

    def test_foreign_key_violation_is_raised_not_silently_accepted(
        self, sqlite_conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO grades (student_id, course_id, score, date)"
                " VALUES ('ghost', 'ghost', 50, '2026-01-01')"
            )


class TestMigrations:
    def test_applies_every_file_once(self) -> None:
        conn = connect(":memory:")
        first = apply_migrations(conn)
        second = apply_migrations(conn)

        assert "001_core" in first
        assert second == [], "re-running must be a no-op"
        conn.close()

    def test_records_what_it_applied(self, sqlite_conn: sqlite3.Connection) -> None:
        versions = {
            row["version"] for row in sqlite_conn.execute("SELECT version FROM schema_migrations")
        }
        assert "001_core" in versions

    def test_creates_the_core_tables(self, sqlite_conn: sqlite3.Connection) -> None:
        tables = {
            row["name"]
            for row in sqlite_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"students", "courses", "grades"} <= tables

    def test_check_constraints_are_active(self, sqlite_conn: sqlite3.Connection) -> None:
        """Defence in depth: the model validates, and so does the database."""
        with pytest.raises(sqlite3.IntegrityError):
            sqlite_conn.execute(
                "INSERT INTO courses (course_id, name, max_grade) VALUES ('X', 'Bad', -1)"
            )

    def test_applies_in_filename_order(self, tmp_path: Path) -> None:
        """002 may reference a table 001 creates, so ordering is load-bearing."""
        (tmp_path / "002_second.sql").write_text("INSERT INTO t (v) VALUES (1);", encoding="utf-8")
        (tmp_path / "001_first.sql").write_text("CREATE TABLE t (v INTEGER);", encoding="utf-8")

        conn = connect(":memory:")
        assert apply_migrations(conn, tmp_path) == ["001_first", "002_second"]
        conn.close()

    def test_missing_directory_is_reported_clearly(self, tmp_path: Path) -> None:
        conn = connect(":memory:")
        with pytest.raises(FileNotFoundError):
            apply_migrations(conn, tmp_path / "does-not-exist")
        conn.close()
