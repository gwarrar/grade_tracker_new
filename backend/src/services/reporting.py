"""Reports, analytics and organisation branding.

Reports return **structured data**, not prose. The frontend renders the wording in
the reader's language, which is what keeps a message catalogue out of the backend.
CSV export is the one exception — a downloaded file has no frontend to render it —
so it takes a translated header map from the caller.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from notenverwaltung.exceptions import ForbiddenError, ValidationError
from notenverwaltung.gradebook import GradeBook, weighted_mean
from notenverwaltung.models import Role
from notenverwaltung.reports import CsvReportGenerator, ReportBuilder
from notenverwaltung.reports.base import grade_point_average
from notenverwaltung.storage import GradeStore
from notenverwaltung.storage.scope import Scope
from services.organization import load_grading_scale, load_organization
from services.scoping import Principal, course_scope, grade_scope, student_scope

__all__ = ["ReportingService", "load_grading_scale", "load_organization"]

# English headers for the reports rendered here rather than by the coursework core's
# CsvReportGenerator. The router passes a per-locale override map, so a German file
# gets German columns while the generator's own DEFAULT_HEADERS stays untouched.
_CSV_HEADERS: dict[str, str] = {
    "course_id": "Course ID",
    "course_name": "Course",
    "term": "Term",
    "teacher_name": "Teacher",
    "student_count": "Students",
    "grade_count": "Grades",
    "average": "Average",
    "pass_rate": "Pass rate",
    "title": "Assessment",
    "count": "Count",
    "average_score": "Average score",
    "average_percentage": "Average %",
    "min_score": "Min",
    "max_score": "Max",
    "capacity": "Capacity",
    "active": "Active",
    "withdrawn": "Withdrawn",
    "completed": "Completed",
    "utilisation": "Utilisation",
    "bucket": "Bucket",
}


def _csv_cell(value: float | int | str | None) -> str:
    """Render one CSV cell, blanking ``None`` rather than writing 0.

    Args:
        value: The value to render.

    Returns:
        The cell text.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _csv_table(
    columns: list[str],
    rows: list[list[Any]],
    headers: dict[str, str],
    delimiter: str,
) -> str:
    """Render rows under translated headers.

    Args:
        columns: The header keys, in column order. Band columns use the
            ``band_{label}`` key, which the translation map deliberately omits —
            a band letter is the same word in every language.
        rows: The data rows, already rendered to strings.
        headers: The merged header map (English defaults plus locale overrides).
        delimiter: Field separator.

    Returns:
        The CSV text.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerow([headers.get(column, column) for column in columns])
    writer.writerows(rows)
    return buffer.getvalue()


def _parse_user_id(entity_id: str) -> int:
    """Parse an ``entity_id`` path segment into a user id.

    Args:
        entity_id: The raw path segment.

    Returns:
        The user id.

    Raises:
        ValidationError: If it is not an integer.
    """
    try:
        return int(entity_id)
    except ValueError:
        raise ValidationError(
            f"Expected a user id, got {entity_id!r}.", field="entity_id"
        ) from None


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
        self._book = GradeBook(GradeStore(conn), load_grading_scale(conn))
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
            # The GPA has to be trimmed on the same pass. Left alone it would be a
            # single number summarising every course the student takes, handed to a
            # teacher who was just refused the marks it was computed from -- the
            # exact leak the filtering above exists to close, in one field instead
            # of a list.
            payload["courses"] = [c for c in payload["courses"] if c["course_id"] in visible]
            payload["gpa"] = grade_point_average(
                [(c["points"], c["credits"]) for c in payload["courses"]]
            )
            payload["courses_graded"] = len(payload["courses"])
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
            ForbiddenError: If the caller is not staff.
        """
        self._assert_may_read_summary()
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
        return [
            student
            for student in self._ranked(descending=False, active_only=True)
            if student["average_percentage"] < threshold
        ]

    def teacher_report(self, user_id: int) -> dict[str, Any]:
        """Build a per-teacher rollup with a course breakdown.

        The most-asked-for admin report and the one thing the previous report set
        could not produce at all.

        Args:
            user_id: Whose rollup.

        Returns:
            The teacher's totals and their courses' figures.

        Raises:
            ForbiddenError: If the caller is below staff, or is a teacher asking
                for somebody else's rollup.
            UserNotFoundError: If no account carries that id.
        """
        self._assert_may_read_teacher_rollup(user_id)
        from services.users import UserNotFoundError

        account = self._conn.execute(
            "SELECT full_name FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if account is None:
            raise UserNotFoundError(f"No account with id {user_id!r}.", user_id=user_id)

        # The caller's own scope AND the requested teacher: a teacher asking for
        # themselves gets their own courses either way, an administrator asking for
        # a colleague gets exactly that colleague's courses and nothing broader.
        teacher_scope = Scope("c.teacher_id = ?", (user_id,))
        c_scope = course_scope(self._principal, "c.course_id") & teacher_scope
        course_rows = self._conn.execute(
            "SELECT c.course_id, c.name, c.term, c.max_grade, c.passing_grade"  # noqa: S608
            f"  FROM courses c WHERE ({c_scope.sql}) ORDER BY c.course_id",
            c_scope.params,
        ).fetchall()

        g_scope = grade_scope(self._principal, "g.student_id", "g.course_id") & teacher_scope
        grade_rows = self._conn.execute(
            "SELECT g.course_id, g.student_id, g.score, g.weight, c.max_grade, c.passing_grade"  # noqa: S608
            "  FROM grades g JOIN courses c ON c.course_id = g.course_id"
            f" WHERE g.deleted_at IS NULL AND ({g_scope.sql})",
            g_scope.params,
        ).fetchall()

        by_course, overall = self._aggregate(grade_rows)
        courses = [
            {
                "course_id": row["course_id"],
                "course_name": row["name"],
                "term": row["term"],
                "student_count": by_course[row["course_id"]]["student_count"]
                if row["course_id"] in by_course
                else 0,
                "grade_count": by_course[row["course_id"]]["grade_count"]
                if row["course_id"] in by_course
                else 0,
                "average_percentage": by_course[row["course_id"]]["average_percentage"]
                if row["course_id"] in by_course
                else None,
                "pass_rate": by_course[row["course_id"]]["pass_rate"]
                if row["course_id"] in by_course
                else None,
            }
            for row in course_rows
        ]
        return {
            "user_id": user_id,
            "teacher_name": account[0],
            "course_count": len(courses),
            "student_count": overall["student_count"],
            "grade_count": overall["grade_count"],
            "average_percentage": overall["average_percentage"],
            "courses": courses,
        }

    def term_report(self, term: str) -> dict[str, Any]:
        """Build a course breakdown for one academic term.

        Scopeable where the institution-wide summary is not: a teacher gets their
        own courses in that term, an administrator the whole institution's.

        Args:
            term: The academic term label, e.g. ``"2026-SS"``.

        Returns:
            The term's totals and each course's figures.

        Raises:
            ForbiddenError: If the caller is below staff.
        """
        self._assert_teacher()
        c_scope = course_scope(self._principal, "c.course_id") & Scope("c.term = ?", (term,))
        course_rows = self._conn.execute(
            "SELECT c.course_id, c.name, c.term, c.max_grade, c.passing_grade,"  # noqa: S608
            "       u.full_name AS teacher_name"
            "  FROM courses c LEFT JOIN users u ON u.id = c.teacher_id"
            f" WHERE ({c_scope.sql}) ORDER BY c.course_id",
            c_scope.params,
        ).fetchall()

        g_scope = grade_scope(self._principal, "g.student_id", "g.course_id") & Scope(
            "c.term = ?", (term,)
        )
        grade_rows = self._conn.execute(
            "SELECT g.course_id, g.student_id, g.score, g.weight, c.max_grade, c.passing_grade"  # noqa: S608
            "  FROM grades g JOIN courses c ON c.course_id = g.course_id"
            f" WHERE g.deleted_at IS NULL AND ({g_scope.sql})",
            g_scope.params,
        ).fetchall()

        by_course, overall = self._aggregate(grade_rows)
        courses = [
            {
                "course_id": row["course_id"],
                "course_name": row["name"],
                "term": row["term"],
                "teacher_name": row["teacher_name"],
                "student_count": by_course[row["course_id"]]["student_count"]
                if row["course_id"] in by_course
                else 0,
                "grade_count": by_course[row["course_id"]]["grade_count"]
                if row["course_id"] in by_course
                else 0,
                "average_percentage": by_course[row["course_id"]]["average_percentage"]
                if row["course_id"] in by_course
                else None,
                "pass_rate": by_course[row["course_id"]]["pass_rate"]
                if row["course_id"] in by_course
                else None,
            }
            for row in course_rows
        ]
        return {
            "term": term,
            "course_count": len(courses),
            "student_count": overall["student_count"],
            "grade_count": overall["grade_count"],
            "average_percentage": overall["average_percentage"],
            "pass_rate": overall["pass_rate"],
            "courses": courses,
        }

    def course_assessments_report(self, course_id: str) -> dict[str, Any]:
        """Group a course's grades by assessment.

        The report that answers "was the midterm too hard": each assessment carries
        its own average, spread and pass rate instead of being averaged away into
        the course total.

        Args:
            course_id: Which course.

        Returns:
            The course and one row per assessment title.

        Raises:
            CourseNotFoundError: If the course is unknown or outside the caller's
                scope.
            ForbiddenError: If the caller is a student — class statistics span
                every student in the course.
        """
        from services.directory import DirectoryService

        course = DirectoryService(self._conn, self._principal).get_course(course_id)
        if not self._principal.can(Role.TEACHER):
            raise ForbiddenError(
                "Class statistics span every student in the course.",
                required_role=str(Role.TEACHER),
                actual_role=str(self._principal.role),
            )

        rows = self._conn.execute(
            "SELECT g.title, g.score, c.max_grade, c.passing_grade"
            "  FROM grades g JOIN courses c ON c.course_id = g.course_id"
            " WHERE g.course_id = ? AND g.deleted_at IS NULL"
            " ORDER BY g.title",
            (course_id,),
        ).fetchall()

        bands = [band.label for band in self._book.scale.bands]
        by_title: dict[str, dict[str, Any]] = {}
        for row in rows:
            group = by_title.setdefault(
                row["title"],
                {"scores": [], "percentages": [], "passing": 0},
            )
            group["scores"].append(row["score"])
            group["percentages"].append(row["score"] / (row["max_grade"] or 1) * 100)
            if row["score"] >= row["passing_grade"]:
                group["passing"] += 1

        assessments = []
        for title, group in by_title.items():
            count = len(group["scores"])
            distribution = dict.fromkeys(bands, 0)
            for percentage in group["percentages"]:
                distribution[self._book.scale.label_for(percentage)] += 1
            assessments.append(
                {
                    "title": title,
                    "count": count,
                    "average_score": round(sum(group["scores"]) / count, 2),
                    "average_percentage": round(sum(group["percentages"]) / count, 2),
                    "min_score": min(group["scores"]),
                    "max_score": max(group["scores"]),
                    "pass_rate": round(group["passing"] / count * 100, 2),
                    "distribution": distribution,
                }
            )

        return {
            "course_id": course_id,
            "course_name": course["name"],
            "max_grade": course["max_grade"],
            "passing_grade": course["passing_grade"],
            "assessments": assessments,
        }

    def enrollment_report(self) -> dict[str, Any]:
        """List every course's enrolment numbers and utilisation.

        Finds both over-subscribed courses and dead ones: capacity against active
        enrolments, with the withdrawn and completed counts a capacity debate needs.

        Returns:
            One row per visible course.

        Raises:
            ForbiddenError: If the caller is below staff.
        """
        self._assert_teacher()
        c_scope = course_scope(self._principal, "c.course_id")
        rows = self._conn.execute(
            "SELECT c.course_id, c.name, c.max_students,"  # noqa: S608
            "       SUM(CASE WHEN e.status = 'active' THEN 1 ELSE 0 END) AS active,"
            "       SUM(CASE WHEN e.status = 'withdrawn' THEN 1 ELSE 0 END) AS withdrawn,"
            "       SUM(CASE WHEN e.status = 'completed' THEN 1 ELSE 0 END) AS completed"
            "  FROM courses c LEFT JOIN enrollments e ON e.course_id = c.course_id"
            f" WHERE ({c_scope.sql})"
            " GROUP BY c.course_id ORDER BY c.course_id",
            c_scope.params,
        ).fetchall()

        report_rows = []
        for row in rows:
            capacity = row["max_students"]
            active = row["active"]
            report_rows.append(
                {
                    "course_id": row["course_id"],
                    "course_name": row["name"],
                    "capacity": capacity,
                    "active": active,
                    "withdrawn": row["withdrawn"],
                    "completed": row["completed"],
                    "utilisation": round(active / capacity * 100, 2) if capacity else 0.0,
                }
            )
        return {"course_count": len(report_rows), "rows": report_rows}

    def distribution_report(self, bucket: str = "month") -> dict[str, Any]:
        """Bucket the grade distribution over time.

        One payload drives a stacked area chart *and* the at-risk-trend question —
        whether pass rates improve month over month is read off the same buckets.

        Args:
            bucket: ``"month"`` groups by the ISO month of the grade date via
                ``substr(date, 1, 7)``; ``"term"`` groups by the course's academic
                term, falling back to the grade's month when a course has none.

        Returns:
            The ordered buckets, each with a zero-filled band distribution.

        Raises:
            ForbiddenError: If the caller is below staff.
            ValidationError: If ``bucket`` is not ``"month"`` or ``"term"``.
        """
        self._assert_teacher()
        if bucket not in ("month", "term"):
            raise ValidationError(f"Unknown distribution bucket {bucket!r}.", field="bucket")
        bucket_sql = (
            "substr(g.date, 1, 7)"
            if bucket == "month"
            else "COALESCE(c.term, substr(g.date, 1, 7))"
        )
        g_scope = grade_scope(self._principal, "g.student_id", "g.course_id")
        rows = self._conn.execute(
            "SELECT g.score, c.max_grade,"  # noqa: S608
            f"       {bucket_sql} AS bucket"
            "  FROM grades g JOIN courses c ON c.course_id = g.course_id"
            f" WHERE g.deleted_at IS NULL AND ({g_scope.sql})",
            g_scope.params,
        ).fetchall()

        bands = [band.label for band in self._book.scale.bands]
        by_bucket: dict[str, dict[str, int]] = {}
        for row in rows:
            distribution = by_bucket.setdefault(row["bucket"], dict.fromkeys(bands, 0))
            percentage = row["score"] / (row["max_grade"] or 1) * 100
            distribution[self._book.scale.label_for(percentage)] += 1

        return {
            "bucket": bucket,
            "buckets": [
                {"bucket": key, "distribution": by_bucket[key]} for key in sorted(by_bucket)
            ],
        }

    def export_csv(
        self,
        kind: str,
        entity_id: str,
        headers: dict[str, str],
        delimiter: str,
        labels: dict[str, str] | None = None,
        bucket: str = "month",
    ) -> str:
        """Render a report as CSV.

        The one place the backend produces human-readable strings, because a
        downloaded file has no frontend to render it.

        Args:
            kind: ``"student"``, ``"course"``, ``"summary"``, ``"teacher"``,
                ``"term"``, ``"assessments"``, ``"enrollment"`` or
                ``"distribution"``.
            entity_id: Which entity. Ignored for ``summary``, ``enrollment`` and
                ``distribution``.
            headers: Translated column headers, supplied by the router from the
                caller's locale.
            delimiter: Field separator. German and French Excel expects ``;``.
            labels: Translated cell values that are words rather than data, such
                as the pass/fail marker.
            bucket: The distribution bucket, only read for the ``distribution``
                kind.

        Returns:
            The CSV text.

        Raises:
            ValidationError: If ``kind`` is unknown or ``bucket`` is invalid.
        """
        generator = CsvReportGenerator(headers=headers, delimiter=delimiter, labels=labels)
        if kind == "student":
            self._assert_visible_student(entity_id)
            return generator.render_student(self._builder.student_report(entity_id))
        if kind == "course":
            self._assert_visible_course(entity_id)
            return generator.render_course(self._builder.course_report(entity_id))
        if kind == "summary":
            self._assert_may_read_summary()
            return generator.render_summary(self._builder.summary_report())
        merged = {**_CSV_HEADERS, **headers}
        if kind == "teacher":
            return _csv_teacher(self.teacher_report(_parse_user_id(entity_id)), merged, delimiter)
        if kind == "term":
            return _csv_term(self.term_report(entity_id), merged, delimiter)
        if kind == "assessments":
            report = self.course_assessments_report(entity_id)
            bands = [band.label for band in self._book.scale.bands]
            return _csv_assessments(report, bands, merged, delimiter)
        if kind == "enrollment":
            return _csv_enrollment(self.enrollment_report(), merged, delimiter)
        if kind == "distribution":
            report = self.distribution_report(bucket)
            bands = [band.label for band in self._book.scale.bands]
            return _csv_distribution(report, bands, merged, delimiter)
        raise ValidationError(f"Unknown report kind {kind!r}.", field="kind")

    # ── Internals ────────────────────────────────────────────────────────────
    def _assert_teacher(self) -> None:
        """Refuse a report that spans other students to anyone below staff.

        These reports cannot be meaningfully scoped to one student — a teacher's
        copy of a term report still contains their classmates' averages — so a role
        check is the only available answer, exactly as with the summary.

        Raises:
            ForbiddenError: If the caller is not a teacher or above.
        """
        if not self._principal.can(Role.TEACHER):
            raise ForbiddenError(
                "This report spans every student in scope and cannot be scoped to one.",
                required_role=str(Role.TEACHER),
                actual_role=str(self._principal.role),
            )

    def _assert_may_read_teacher_rollup(self, user_id: int) -> None:
        """Refuse a teacher rollup the caller may not read.

        Args:
            user_id: Whose rollup was requested.

        Raises:
            ForbiddenError: If the caller is below staff, or is a teacher asking
                for somebody else's rollup.
        """
        self._assert_teacher()
        if not self._principal.is_admin and self._principal.user_id != user_id:
            raise ForbiddenError(
                "A teacher may only read their own rollup.",
                required_role=str(Role.ADMIN),
                actual_role=str(self._principal.role),
            )

    def _aggregate(self, rows: list[Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        """Aggregate grade rows into per-course statistics and overall totals.

        The weighted average and pass rate are computed here, in Python, rather than
        in SQL: the weighted mean needs every grade row anyway, and a course with no
        grades must report ``None`` rather than a division by zero.

        Args:
            rows: Grade rows carrying ``course_id``, ``student_id``, ``score``,
                ``weight``, ``max_grade`` and ``passing_grade``.

        Returns:
            A per-course map and an overall totals map. Both use the same four
            fields: ``student_count``, ``grade_count``, ``average_percentage`` and
            ``pass_rate``.
        """
        by_course: dict[str, dict[str, Any]] = {}
        all_values: list[tuple[float, float]] = []
        all_students: set[str] = set()
        all_passing = 0
        for row in rows:
            stats = by_course.setdefault(
                row["course_id"],
                {"students": set(), "values": [], "passing": 0},
            )
            stats["students"].add(row["student_id"])
            percentage = row["score"] / (row["max_grade"] or 1) * 100
            stats["values"].append((percentage, row["weight"]))
            all_values.append((percentage, row["weight"]))
            all_students.add(row["student_id"])
            if row["score"] >= row["passing_grade"]:
                stats["passing"] += 1
                all_passing += 1

        per_course: dict[str, dict[str, Any]] = {}
        for course_id, stats in by_course.items():
            per_course[course_id] = _course_totals(stats)
        overall = {
            "student_count": len(all_students),
            "grade_count": len(all_values),
            "average_percentage": (round(weighted_mean(all_values), 2) if all_values else None),
            "pass_rate": (round(all_passing / len(all_values) * 100, 2) if all_values else None),
        }
        return per_course, overall

    def _assert_may_read_summary(self) -> None:
        """Refuse a summary to anyone below staff.

        A summary spans every student, so unlike every other report there is no scope
        that could narrow it — which makes a role check the only available answer.

        It is a method rather than a route dependency because **two** paths reach the
        builder: :meth:`summary_report` and the ``summary`` branch of
        :meth:`export_csv`. Only the first had a ``TeacherUser`` route guard, so
        ``/reports/summary/summary/export.csv`` handed any signed-in student the
        institution's ranked averages. Guarding the method the routes share is what
        makes a third caller safe by default.

        Raises:
            ForbiddenError: If the caller is not a teacher or above.
        """
        if not self._principal.can(Role.TEACHER):
            raise ForbiddenError(
                "A summary spans every student and cannot be scoped to one.",
                required_role=str(Role.TEACHER),
                actual_role=str(self._principal.role),
            )

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

    def _ranked(self, *, descending: bool, active_only: bool = False) -> list[dict[str, Any]]:
        """Rank students by weighted average percentage, within scope."""
        g_scope = grade_scope(self._principal, "g.student_id", "g.course_id")
        active_filter = " AND s.is_active = 1" if active_only else ""
        rows = self._conn.execute(
            "SELECT g.student_id, s.first_name, s.last_name, g.score, g.weight, c.max_grade"  # noqa: S608
            "  FROM grades g"
            "  JOIN students s ON s.student_id = g.student_id"
            "  JOIN courses c ON c.course_id = g.course_id"
            f" WHERE g.deleted_at IS NULL AND ({g_scope.sql}){active_filter}",
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


def _course_totals(stats: dict[str, Any]) -> dict[str, Any]:
    """Summarise one course's aggregated grades.

    Args:
        stats: The ``{"students", "values", "passing"}`` aggregation for one course.

    Returns:
        The course's student count, grade count, average percentage and pass rate.
    """
    values = stats["values"]
    return {
        "student_count": len(stats["students"]),
        "grade_count": len(values),
        "average_percentage": round(weighted_mean(values), 2) if values else None,
        "pass_rate": (round(stats["passing"] / len(values) * 100, 2) if values else None),
    }


def _csv_teacher(report: dict[str, Any], headers: dict[str, str], delimiter: str) -> str:
    """Render the teacher rollup as CSV: one row per course."""
    rows = [
        [
            course["course_id"],
            course["course_name"],
            course["term"] or "",
            course["student_count"],
            course["grade_count"],
            _csv_cell(course["average_percentage"]),
            _csv_cell(course["pass_rate"]),
        ]
        for course in report["courses"]
    ]
    return _csv_table(
        [
            "course_id",
            "course_name",
            "term",
            "student_count",
            "grade_count",
            "average",
            "pass_rate",
        ],
        rows,
        headers,
        delimiter,
    )


def _csv_term(report: dict[str, Any], headers: dict[str, str], delimiter: str) -> str:
    """Render the term report as CSV: one row per course."""
    rows = [
        [
            course["course_id"],
            course["course_name"],
            course["term"] or "",
            course["teacher_name"] or "",
            course["student_count"],
            course["grade_count"],
            _csv_cell(course["average_percentage"]),
            _csv_cell(course["pass_rate"]),
        ]
        for course in report["courses"]
    ]
    return _csv_table(
        [
            "course_id",
            "course_name",
            "term",
            "teacher_name",
            "student_count",
            "grade_count",
            "average",
            "pass_rate",
        ],
        rows,
        headers,
        delimiter,
    )


def _csv_assessments(
    report: dict[str, Any],
    bands: list[str],
    headers: dict[str, str],
    delimiter: str,
) -> str:
    """Render the assessment analysis as CSV: one row per assessment."""
    columns = [
        "title",
        "count",
        "average_score",
        "average_percentage",
        "min_score",
        "max_score",
        "pass_rate",
    ]
    columns += [f"band_{label}" for label in bands]
    rows = [
        [
            assessment["title"],
            assessment["count"],
            assessment["average_score"],
            assessment["average_percentage"],
            assessment["min_score"],
            assessment["max_score"],
            assessment["pass_rate"],
            *[assessment["distribution"].get(label, 0) for label in bands],
        ]
        for assessment in report["assessments"]
    ]
    return _csv_table(columns, rows, headers, delimiter)


def _csv_enrollment(report: dict[str, Any], headers: dict[str, str], delimiter: str) -> str:
    """Render the enrolment report as CSV: one row per course."""
    rows = [
        [
            row["course_id"],
            row["course_name"],
            row["capacity"],
            row["active"],
            row["withdrawn"],
            row["completed"],
            row["utilisation"],
        ]
        for row in report["rows"]
    ]
    return _csv_table(
        ["course_id", "course_name", "capacity", "active", "withdrawn", "completed", "utilisation"],
        rows,
        headers,
        delimiter,
    )


def _csv_distribution(
    report: dict[str, Any],
    bands: list[str],
    headers: dict[str, str],
    delimiter: str,
) -> str:
    """Render the time distribution as CSV: one row per bucket."""
    columns = ["bucket"]
    columns += [f"band_{label}" for label in bands]
    rows = [
        [
            bucket["bucket"],
            *[bucket["distribution"].get(label, 0) for label in bands],
        ]
        for bucket in report["buckets"]
    ]
    return _csv_table(columns, rows, headers, delimiter)
