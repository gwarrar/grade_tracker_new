"""Reports, analytics and organisation branding.

Reports return **structured data**, not prose. The frontend renders the wording in
the reader's language, which is what keeps a message catalogue out of the backend.
CSV export is the one exception — a downloaded file has no frontend to render it —
so it takes a translated header map from the caller.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from notenverwaltung.gradebook import GradeBook, weighted_mean
from notenverwaltung.grading_scale import DEFAULT_SCALE, GradingScale
from notenverwaltung.models import Organization
from notenverwaltung.reports import CsvReportGenerator, ReportBuilder
from notenverwaltung.storage import SqliteGradeStore
from notenverwaltung.storage.scope import Scope
from services.scoping import Principal, course_scope, grade_scope, student_scope


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


class ReportingService:
    """Scoped reports and dashboard analytics."""

    def __init__(self, conn: sqlite3.Connection, principal: Principal) -> None:
        """Bind the service to a request.

        Args:
            conn: The request's connection.
            principal: The authenticated caller.
        """
        self._conn = conn
        self._principal = principal
        self._book = GradeBook(SqliteGradeStore(conn), load_grading_scale(conn))
        self._builder = ReportBuilder(self._book)

    def student_report(self, student_id: str) -> dict[str, Any]:
        """Build a student's report.

        Args:
            student_id: Which student.

        Returns:
            The structured report.

        Raises:
            StudentNotFoundError: If they are outside the caller's scope.
        """
        self._assert_visible_student(student_id)
        report = self._builder.student_report(student_id)
        payload = _as_dict(report)
        # A student's own report is theirs in full. A teacher's copy is trimmed to
        # the grades from their own courses -- the report must not become a way to
        # read marks a scoped list endpoint would have hidden.
        if not self._principal.is_admin and self._principal.role != "student":
            visible = self._visible_course_ids()
            payload["grades"] = [g for g in payload["grades"] if g["course_id"] in visible]
            payload["average_percentage"] = _recompute(payload["grades"])
        return payload

    def course_report(self, course_id: str) -> dict[str, Any]:
        """Build a course's report.

        Args:
            course_id: Which course.

        Returns:
            The structured report.

        Raises:
            CourseNotFoundError: If it is outside the caller's scope.
        """
        self._assert_visible_course(course_id)
        payload = _as_dict(self._builder.course_report(course_id))
        # A student may see the course they sit in, but not their classmates' marks.
        if self._principal.role == "student":
            payload["grades"] = [
                g for g in payload["grades"] if g["student_id"] == self._principal.student_id
            ]
        return payload

    def summary_report(self, at_risk_threshold: float = 60.0) -> dict[str, Any]:
        """Build the institution-wide summary.

        Args:
            at_risk_threshold: Percentage below which a student counts as at risk.

        Returns:
            The structured report.

        Raises:
            ForbiddenError: Never here — the router restricts this to staff, since a
                summary over every student is not scopeable in a meaningful way.
        """
        return _as_dict(self._builder.summary_report(at_risk_threshold))

    def dashboard(self) -> dict[str, Any]:
        """Return headline numbers for the caller's dashboard.

        Every count is scoped, so a teacher's dashboard describes their own courses
        rather than the institution.

        Returns:
            Totals, average percentage and grade distribution within scope.
        """
        s_scope = student_scope(self._principal, "student_id")
        c_scope = course_scope(self._principal, "course_id")
        g_scope = grade_scope(self._principal, "g.student_id", "g.course_id")

        students = self._count("students", s_scope)
        courses = self._count("courses", c_scope)

        rows = self._conn.execute(
            "SELECT g.score, g.weight, c.max_grade, c.passing_grade"  # noqa: S608
            "  FROM grades g JOIN courses c ON c.course_id = g.course_id"
            f" WHERE g.deleted_at IS NULL AND ({g_scope.sql})",
            g_scope.params,
        ).fetchall()

        percentages = [(r["score"] / (r["max_grade"] or 1) * 100, r["weight"]) for r in rows]
        distribution = {band.label: 0 for band in self._book.scale.bands}
        for percentage, _ in percentages:
            distribution[self._book.scale.label_for(percentage)] += 1

        return {
            "student_count": students,
            "course_count": courses,
            "grade_count": len(rows),
            "average_percentage": (round(weighted_mean(percentages), 2) if percentages else None),
            "pass_rate": (
                round(sum(1 for r in rows if r["score"] >= r["passing_grade"]) / len(rows) * 100, 2)
                if rows
                else None
            ),
            "distribution": distribution,
        }

    def top_students(self, limit: int = 5) -> list[dict[str, Any]]:
        """Rank the highest-averaging students within the caller's scope.

        Args:
            limit: How many to return.

        Returns:
            ``student_id``, ``name`` and ``average_percentage``, best first.
        """
        return self._ranked(descending=True)[:limit]

    def at_risk_students(self, threshold: float = 60.0) -> list[dict[str, Any]]:
        """List students averaging below a threshold, worst first.

        Students with no grades are excluded: no data is not the same as poor
        performance, and ranking them as zero would put an unassessed student at the
        top of an intervention list.

        Args:
            threshold: The percentage below which a student counts as at risk.

        Returns:
            ``student_id``, ``name`` and ``average_percentage``, worst first.
        """
        return [s for s in self._ranked(descending=False) if s["average_percentage"] < threshold]

    def export_csv(
        self,
        kind: str,
        entity_id: str,
        headers: dict[str, str],
        delimiter: str,
        labels: dict[str, str] | None = None,
    ) -> str:
        """Render a report as CSV.

        The one place the backend produces human-readable strings, because a
        downloaded file has no frontend to render it.

        Args:
            kind: ``"student"``, ``"course"`` or ``"summary"``.
            entity_id: Which entity, ignored for ``summary``.
            headers: Translated column headers, supplied by the router from the
                caller's locale.
            delimiter: Field separator. German and French Excel expects ``;``.
            labels: Translated cell values that are words rather than data, such
                as the pass/fail marker.

        Returns:
            The CSV text.

        Raises:
            ValidationError: If ``kind`` is unknown.
        """
        from notenverwaltung.exceptions import ValidationError

        generator = CsvReportGenerator(headers=headers, delimiter=delimiter, labels=labels)
        if kind == "student":
            self._assert_visible_student(entity_id)
            return generator.render_student(self._builder.student_report(entity_id))
        if kind == "course":
            self._assert_visible_course(entity_id)
            return generator.render_course(self._builder.course_report(entity_id))
        if kind == "summary":
            return generator.render_summary(self._builder.summary_report())
        raise ValidationError(f"Unknown report kind {kind!r}.", field="kind")

    # ── Internals ────────────────────────────────────────────────────────────
    def _count(self, table: str, scope: Scope) -> int:
        """Count rows in a table within a scope."""
        allowed = {"students", "courses"}
        if table not in allowed:
            raise ValueError(f"Unexpected table: {table!r}")
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {scope.sql}",  # noqa: S608
            scope.params,
        ).fetchone()
        return row[0] if row else 0

    def _visible_course_ids(self) -> set[str]:
        """Return the course ids the caller may see."""
        scope = course_scope(self._principal, "course_id")
        rows = self._conn.execute(
            f"SELECT course_id FROM courses WHERE {scope.sql}",  # noqa: S608
            scope.params,
        )
        return {row[0] for row in rows}

    def _ranked(self, *, descending: bool) -> list[dict[str, Any]]:
        """Rank students by weighted average percentage, within scope."""
        g_scope = grade_scope(self._principal, "g.student_id", "g.course_id")
        rows = self._conn.execute(
            "SELECT g.student_id, s.first_name, s.last_name, g.score, g.weight, c.max_grade"  # noqa: S608
            "  FROM grades g"
            "  JOIN students s ON s.student_id = g.student_id"
            "  JOIN courses c ON c.course_id = g.course_id"
            f" WHERE g.deleted_at IS NULL AND ({g_scope.sql})",
            g_scope.params,
        ).fetchall()

        by_student: dict[str, tuple[str, list[tuple[float, float]]]] = {}
        for row in rows:
            name = f"{row['first_name']} {row['last_name']}"
            entry = by_student.setdefault(row["student_id"], (name, []))
            entry[1].append((row["score"] / (row["max_grade"] or 1) * 100, row["weight"]))

        ranked = [
            {
                "student_id": student_id,
                "name": name,
                "average_percentage": round(weighted_mean(values), 2),
            }
            for student_id, (name, values) in by_student.items()
            if values
        ]
        ranked.sort(key=lambda entry: entry["average_percentage"], reverse=descending)
        return ranked

    def _assert_visible_student(self, student_id: str) -> None:
        """Raise unless the student is within the caller's scope."""
        from services.directory import DirectoryService

        DirectoryService(self._conn, self._principal).get_student(student_id)

    def _assert_visible_course(self, course_id: str) -> None:
        """Raise unless the course is within the caller's scope."""
        from services.directory import DirectoryService

        DirectoryService(self._conn, self._principal).get_course(course_id)


def _as_dict(report: Any) -> dict[str, Any]:
    """Convert a report dataclass into a plain dictionary."""
    from dataclasses import asdict

    return asdict(report)


def _recompute(grades: list[dict[str, Any]]) -> float | None:
    """Recompute a weighted average after grades were filtered out of a report."""
    if not grades:
        return None
    return round(weighted_mean([(g["percentage"], g["weight"]) for g in grades]), 2)
