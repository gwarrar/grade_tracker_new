"""Reading the organisation's configuration.

Two functions, lifted out of :mod:`services.reporting` so that anything needing the
grading scale can have it without importing the report machinery. ``reporting`` pulls
in ``GradeBook``, ``ReportBuilder`` and ``CsvReportGenerator`` at module level, and
``grading`` needs none of those — it needs one row from one table.
"""

from __future__ import annotations

import sqlite3

from notenverwaltung.grading_scale import DEFAULT_SCALE, GradingScale
from notenverwaltung.models import Organization


def load_organization(conn: sqlite3.Connection) -> Organization:
    """Read the organisation configuration.

    Args:
        conn: The connection to query.

    Returns:
        The organisation, or defaults if the row is somehow missing.
    """
    row = conn.execute("SELECT * FROM organization WHERE id = 1").fetchone()
    return Organization.from_row(row) if row else Organization(name="Grade Tracker")


def load_grading_scale(conn: sqlite3.Connection) -> GradingScale:
    """Read the organisation's grading scale.

    Args:
        conn: The connection to query.

    Returns:
        The configured scale, or the specification default.
    """
    try:
        return load_organization(conn).grading_scale
    except Exception:
        return DEFAULT_SCALE
