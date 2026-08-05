"""API tests for the bulk import endpoints.

The import service writes through the same use cases a form would, so its tests
assert the interesting guarantees: a preview changes nothing, a commit audits each
row, a malformed row costs only itself, the app's own `;`-delimited exports read
back, and the two caps (size and row count) refuse.
"""

from __future__ import annotations

import io
import json
import sqlite3
from typing import Any

from openpyxl import Workbook

STUDENTS_MAPPING = {
    "student_id": "student_id",
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
}
GRADES_MAPPING = {
    "student_id": "student_id",
    "course_id": "course_id",
    "score": "score",
    "date": "date",
}


_IMPORT_TABLES = (
    "audit_log",
    "course_prerequisites",
    "courses",
    "enrollments",
    "grades",
    "notes",
    "students",
)
"""Tables an import could write, restricted to those.

`sessions` is excluded because *every* authenticated request touches it
(``last_seen_at``), so it changes regardless of whether the preview wrote anything.
"""


def _snapshot(conn: sqlite3.Connection) -> tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]:
    """Return every row of the tables an import could write.

    Comparing the full content rather than counts means a preview that wrote and
    rolled back *and* one that left a stray row or audit entry both fail here.
    """
    return tuple(
        (
            table,
            tuple(tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1')),  # noqa: S608
        )
        for table in _IMPORT_TABLES
    )


def _workbook(*rows: tuple[Any, ...], headers: tuple[Any, ...]) -> bytes:
    """Build an .xlsx file in memory."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class TestRoleGating:
    def test_a_teacher_cannot_import_students(self, as_teacher: Any) -> None:
        """Students change the register itself, so they are administrators only."""
        content = b"student_id,first_name,last_name,email\nS100,A,B,a@b.c\n"
        response = as_teacher.post(
            "/import/students",
            files={"file": ("students.csv", content, "text/csv")},
            data={"mapping": json.dumps(STUDENTS_MAPPING)},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_a_teacher_cannot_preview_students(self, as_teacher: Any) -> None:
        content = b"student_id,first_name,last_name,email\nS100,A,B,a@b.c\n"
        response = as_teacher.post(
            "/import/students/preview",
            files={"file": ("students.csv", content, "text/csv")},
            data={"mapping": json.dumps(STUDENTS_MAPPING)},
        )
        assert response.status_code == 403

    def test_an_admin_can_import_courses(self, as_admin: Any) -> None:
        content = b"course_id,name\nCS200,Operating Systems\n"
        response = as_admin.post(
            "/import/courses",
            files={"file": ("courses.csv", content, "text/csv")},
            data={"mapping": json.dumps({"course_id": "course_id", "name": "name"})},
        )
        assert response.status_code == 200, response.text
        assert response.json()["imported"] == 1


class TestPreview:
    def test_preview_leaves_the_database_untouched(
        self, as_teacher: Any, seeded_db: sqlite3.Connection
    ) -> None:
        """A dry run must change nothing — not even the audit trail."""
        before = _snapshot(seeded_db)
        content = (
            b"student_id,course_id,score,date\nS001,CS101,85,2026-01-15\nS001,CS101,90,2026-01-17\n"
        )
        response = as_teacher.post(
            "/import/grades/preview",
            files={"file": ("grades.csv", content, "text/csv")},
            data={"mapping": json.dumps(GRADES_MAPPING)},
        )
        assert response.status_code == 200, response.text
        assert response.json()["report"]["imported"] == 2
        assert _snapshot(seeded_db) == before

    def test_preview_reports_the_same_outcome_a_commit_would(self, as_teacher: Any) -> None:
        """The report is produced by running the real import inside a rolled-back
        savepoint, so the two endpoints cannot drift apart."""
        content = (
            b"student_id,course_id,score,date\n"
            b"S001,CS101,85,2026-01-15\n"
            b"S001,CS101,nope,2026-01-17\n"
        )
        preview = as_teacher.post(
            "/import/grades/preview",
            files={"file": ("grades.csv", content, "text/csv")},
            data={"mapping": json.dumps(GRADES_MAPPING)},
        )
        committed = as_teacher.post(
            "/import/grades",
            files={"file": ("grades.csv", content, "text/csv")},
            data={"mapping": json.dumps(GRADES_MAPPING)},
        )
        assert preview.status_code == 200
        assert committed.status_code == 200
        assert preview.json()["report"] == committed.json()

    def test_preview_without_mapping_returns_headers_and_samples_for_xlsx(
        self, as_teacher: Any
    ) -> None:
        """The browser cannot read .xlsx, so the preview doubles as the inspection
        step: with no mapping it reports every row as unmapped and hands back the
        headers and sample rows the mapping and AI steps need."""
        blob = _workbook(
            ("S001", "CS101", 91, "2026-03-01"),
            ("S001", "CS101", 88, "2026-03-02"),
            headers=("student_id", "course_id", "score", "date"),
        )
        response = as_teacher.post(
            "/import/grades/preview",
            files={
                "file": (
                    "grades.xlsx",
                    blob,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["headers"] == ["student_id", "course_id", "score", "date"]
        assert body["sample_rows"][0] == ["S001", "CS101", "91", "2026-03-01"]
        assert body["report"]["imported"] == 0
        assert body["report"]["skipped"] == 2
        assert {error["code"] for error in body["report"]["errors"]} == {"UNMAPPED_FIELD"}


class TestCommit:
    def test_commit_writes_one_audit_row_per_record(
        self, as_admin: Any, seeded_db: sqlite3.Connection
    ) -> None:
        """The trail records every row the import wrote, through the same audit path
        a form would use."""
        before = seeded_db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE entity = 'student'"
        ).fetchone()[0]
        content = (
            b"student_id,first_name,last_name,email\n"
            b"S100,Nina,Nowak,nina@test.local\n"
            b"S101,Omar,Khalil,omar@test.local\n"
        )
        response = as_admin.post(
            "/import/students",
            files={"file": ("students.csv", content, "text/csv")},
            data={"mapping": json.dumps(STUDENTS_MAPPING)},
        )
        assert response.status_code == 200, response.text
        assert response.json()["imported"] == 2

        after = seeded_db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE entity = 'student'"
        ).fetchone()[0]
        assert after - before == 2
        for student_id in ("S100", "S101"):
            assert (
                seeded_db.execute(
                    "SELECT COUNT(*) FROM students WHERE student_id = ?", (student_id,)
                ).fetchone()[0]
                == 1
            )

    def test_malformed_row_is_reported_while_the_rest_imports(
        self, as_teacher: Any, seeded_db: sqlite3.Connection
    ) -> None:
        """One bad row must not cost the file: 2 of 3 import, and the rejected row
        is named by line and code."""
        content = (
            b"student_id,course_id,score,date\n"
            b"S001,CS101,85,2026-01-15\n"
            b"S001,CS101,nope,2026-01-16\n"
            b"S001,CS101,90,2026-01-17\n"
        )
        response = as_teacher.post(
            "/import/grades",
            files={"file": ("grades.csv", content, "text/csv")},
            data={"mapping": json.dumps(GRADES_MAPPING)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["imported"] == 2
        assert body["skipped"] == 1
        assert body["errors"] == [{"line": 3, "code": "INVALID_NUMBER"}]

        after = seeded_db.execute(
            "SELECT COUNT(*) FROM grades WHERE student_id = 'S001' AND course_id = 'CS101'"
        ).fetchone()[0]
        assert after == 3  # the seeded grade plus the two good rows

    def test_teacher_cannot_import_grades_into_a_colleagues_course(
        self, as_teacher: Any, seeded_db: sqlite3.Connection
    ) -> None:
        """Ownership applies per row: the teacher's own course imports, the
        colleague's is refused with FORBIDDEN."""
        content = (
            b"student_id,course_id,score,date\nS001,CS101,80,2026-02-01\nS002,CS999,60,2026-02-01\n"
        )
        response = as_teacher.post(
            "/import/grades",
            files={"file": ("grades.csv", content, "text/csv")},
            data={"mapping": json.dumps(GRADES_MAPPING)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["imported"] == 1
        assert body["skipped"] == 1
        assert body["errors"] == [{"line": 3, "code": "FORBIDDEN"}]

        rows = seeded_db.execute(
            "SELECT score FROM grades WHERE course_id IN ('CS101', 'CS999') AND date = '2026-02-01'"
        ).fetchall()
        assert [row["score"] for row in rows] == [80.0]

    def test_xlsx_imports_via_the_server_side_extractor(self, as_teacher: Any) -> None:
        """The browser cannot read .xlsx, so the raw file travels to openpyxl here."""
        blob = _workbook(
            ("S001", "CS101", 91, "2026-03-01"),
            ("S001", "CS101", 88, "2026-03-02"),
            headers=("student_id", "course_id", "score", "date"),
        )
        response = as_teacher.post(
            "/import/grades",
            files={
                "file": (
                    "grades.xlsx",
                    blob,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={"mapping": json.dumps(GRADES_MAPPING)},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["imported"] == 2
        assert body["skipped"] == 0


class TestCaps:
    def test_size_cap_rejects_an_oversized_file(self, as_admin: Any) -> None:
        content = b"student_id,first_name,last_name,email\n" + b"x" * (2 * 1024 * 1024)
        response = as_admin.post(
            "/import/students",
            files={"file": ("big.csv", content, "text/csv")},
            data={"mapping": json.dumps(STUDENTS_MAPPING)},
        )
        assert response.status_code == 413
        assert response.json()["code"] == "PAYLOAD_TOO_LARGE"

    def test_row_cap_rejects_a_file_above_the_limit(self, as_admin: Any) -> None:
        lines = [f"S{i},First{i},Last{i},s{i}@test.local" for i in range(5001)]
        content = ("student_id,first_name,last_name,email\n" + "\n".join(lines)).encode()
        response = as_admin.post(
            "/import/students",
            files={"file": ("big.csv", content, "text/csv")},
            data={"mapping": json.dumps(STUDENTS_MAPPING)},
        )
        assert response.status_code == 413
        assert response.json()["code"] == "IMPORT_TOO_MANY_ROWS"


class TestOwnExportRoundTrip:
    def test_the_apps_own_semicolon_export_imports_back(self, as_admin: Any) -> None:
        """The German report export is BOM-prefixed and `;`-delimited, and every
        column it carries maps onto course fields — so the file this application
        produces is a file this application can read back."""
        created = as_admin.post(
            "/students",
            json={
                "student_id": "S100",
                "first_name": "Nina",
                "last_name": "Nowak",
                "email": "nina@test.local",
            },
        )
        assert created.status_code == 201, created.text
        course = as_admin.post("/courses", json={"course_id": "CS200", "name": "Operating Systems"})
        assert course.status_code == 201, course.text
        grade = as_admin.post(
            "/grades",
            json={"student_id": "S100", "course_id": "CS200", "score": 88, "date": "2026-03-01"},
        )
        assert grade.status_code == 201, grade.text

        exported = as_admin.get("/reports/student/S100/export.csv?locale=de")
        assert exported.status_code == 200
        text = exported.text
        assert text.startswith("\ufeff")
        assert ";" in text

        # The course is deleted so the re-import is clean rather than a duplicate.
        removed = as_admin.delete("/courses/CS200")
        assert removed.status_code == 204

        response = as_admin.post(
            "/import/courses",
            files={"file": ("export.csv", exported.content, "text/csv")},
            data={
                "mapping": json.dumps(
                    {"course_id": "Kurs-ID", "name": "Kurs", "max_grade": "Maximum"}
                )
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["imported"] == 1
        assert body["skipped"] == 0

        rebuilt = as_admin.get("/courses/CS200")
        assert rebuilt.status_code == 200
        assert rebuilt.json()["name"] == "Operating Systems"
        assert rebuilt.json()["max_grade"] == 100.0
