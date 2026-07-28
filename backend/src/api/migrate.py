"""Apply pending database migrations.

Usage:
    uv run python -m api.migrate
"""

from __future__ import annotations

import sys

from api.config import get_settings
from notenverwaltung.storage import apply_migrations, connect


def main() -> int:
    """Run every migration that has not been applied yet.

    Returns:
        A process exit code: 0 on success, 1 if a migration failed.
    """
    settings = get_settings()
    settings.database_file.parent.mkdir(parents=True, exist_ok=True)

    conn = connect(settings.database_file)
    try:
        applied = apply_migrations(conn)
    except Exception as exc:  # a CLI reports failures, it does not re-raise them at the user
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if applied:
        for version in applied:
            print(f"applied {version}")
    else:
        print("database is up to date")
    print(f"database: {settings.database_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
