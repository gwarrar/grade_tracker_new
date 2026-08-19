"""Bulk import of students, courses and grades.

Two verbs over one code path:

``preview`` parses the upload and runs the whole import inside a savepoint that is
then rolled back, so the caller sees exactly what would land — including per-row
error codes — without any of it landing. ``commit`` runs the same import and keeps
it. There is deliberately no staging table, temp file or preview token to clean up:
the dry run *is* the real import, undone.

Both take the file and the column mapping the client built, optionally prefilled by
the AI import-map feature. The mapping travels with the request rather than being
re-derived here, which keeps the AI and import services decoupled — each can change
without the other noticing.

Rows are written through the same services a form would use, so validation, scope
and capacity apply per row, and every successful row produces its own audit entry in
the same unit of work. A malformed row is reported with its line and error code
while the rest of the file imports — the shape :class:`ImportReport` exists for.

SQLite is a single writer. An import therefore runs in one transaction, so the whole
batch and its audit trail commit or roll back together, and the row cap passed in
stops one request from holding the write lock long enough to starve everyone else.
Lifting the cap is a background job over a staging table, not a bigger number.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import openpyxl

from notenverwaltung.exceptions import (
    GradeBookError,
    ImportTooManyRowsError,
    ValidationError,
)
from notenverwaltung.gradebook import ImportReport
from notenverwaltung.models.user import Role
from notenverwaltung.storage import transaction
from services.directory import DirectoryService
from services.grading import GradingService
from services.scoping import Principal
from services.users import UserService

SAMPLE_ROWS = 5
"""How many data rows a preview carries back for disambiguation."""


def _cell_text(cell: Any) -> str:
    """Render one spreadsheet cell as the text the importer expects.

    openpyxl hands back a ``datetime`` for any date-formatted cell, and
    ``str(datetime(2026, 1, 15))`` is ``'2026-01-15 00:00:00'`` — which matches none
    of the accepted date formats, so every row carrying a real date column was
    rejected as invalid. A teacher exporting marks from Excel got
    ``imported: 0, skipped: 300`` and no indication that the file was fine.

    Args:
        cell: The value openpyxl produced.

    Returns:
        The cell as text, with dates in ISO form.
    """
    if cell is None:
        return ""
    if isinstance(cell, datetime):
        # A time component means a timestamp column; the date is the part that
        # matters and the rest would fail the same parse the bug was about.
        return cell.date().isoformat()
    if isinstance(cell, date):
        return cell.isoformat()
    return str(cell)


class _UnmappedFieldError(GradeBookError):
    """A required field has no source column mapped to it."""

    code = "UNMAPPED_FIELD"
    http_status = 422


class _MissingValueError(GradeBookError):
    """A mapped column exists but its cell in this row is empty."""

    code = "MISSING_VALUE"
    http_status = 422


class _DryRunRollbackError(Exception):
    """Sentinel raised to undo an import preview.

    The import has already completed at this point; the exception is the signal for
    :func:`notenverwaltung.storage.transaction` to roll the savepoint back. The
    report rides along inside the exception so the caller can return it afterwards.
    """

    def __init__(self, report: ImportReport) -> None:
        """Store the report.

        Args:
            report: The outcome of the dry run, computed before the rollback.
        """
        super().__init__("roll the import preview back")
        self.report = report


@dataclass
class ParsedTable:
    """A parsed spreadsheet upload.

    Attributes:
        headers: The header row, used for the mapping table and the AI proposal.
        rows: One dictionary per data row, keyed by header.
    """

    headers: list[str]
    rows: list[dict[str, str]]


class ImportService:
    """Parsing, previewing and committing bulk imports.

    Args:
        conn: The request's connection.
        principal: The authenticated caller. Importing students or courses needs an
            administrator; importing grades needs a teacher. The router enforces
            that; this service also applies it per row through the services it
            delegates to, so a teacher cannot grade into a colleague's course.
        max_import_rows: Hard cap on the number of data rows in one file.
    """

    def __init__(
        self, conn: sqlite3.Connection, principal: Principal, *, max_import_rows: int
    ) -> None:
        """Bind the service to a request."""
        self._conn = conn
        self._principal = principal
        self._max_rows = max_import_rows
        self._directory = DirectoryService(conn, principal)
        self._grading = GradingService(conn, principal)
        self._create_accounts = True
        #: One-time passwords minted by the run in progress, in row order. Held on
        #: the service rather than in the report because ``ImportReport`` is a
        #: domain type shared with the offline importer, which has nobody to show
        #: a password to.
        self._credentials: list[dict[str, str]] = []

    def preview(
        self,
        *,
        kind: str,
        filename: str,
        content: bytes,
        column_mapping: dict[str, str],
        create_accounts: bool = True,
    ) -> dict[str, Any]:
        """Dry-run an import without changing the database.

        Args:
            kind: ``students``, ``courses`` or ``grades``.
            filename: The upload's name, used to pick the parser.
            content: The raw bytes.
            column_mapping: Field name to source column name.
            create_accounts: Whether student rows would also mint sign-in accounts.
                Honoured here so a preview counts the same duplicate-address
                failures the commit would; the passwords themselves are rolled
                back with everything else and never returned.

        Returns:
            The headers, a few sample rows, and the report the real import would
            have produced.

        Raises:
            ValidationError: If the file cannot be parsed.
            ImportTooManyRowsError: If the file exceeds the row cap.
        """
        table = self._read_table(filename, content)
        self._check_row_cap(len(table.rows))
        self._create_accounts = create_accounts
        try:
            with transaction(self._conn):
                dry_run = _DryRunRollbackError(self._run(kind, table.rows, column_mapping))
                raise dry_run
        except _DryRunRollbackError as rollback:
            report = rollback.report
        return {
            "kind": kind,
            "headers": table.headers,
            "sample_rows": [list(row.values()) for row in table.rows[:SAMPLE_ROWS]],
            "report": report.to_dict(),
        }

    def commit(
        self,
        *,
        kind: str,
        filename: str,
        content: bytes,
        column_mapping: dict[str, str],
        create_accounts: bool = True,
    ) -> dict[str, Any]:
        """Import the file for real.

        Every row and its audit entry commit together; the caller sees the same
        report a preview showed.

        Args:
            kind: ``students``, ``courses`` or ``grades``.
            filename: The upload's name, used to pick the parser.
            content: The raw bytes.
            column_mapping: Field name to source column name.
            create_accounts: Whether each imported student also gets a sign-in
                account. Off for an archive of past cohorts, which should not
                become four hundred live credentials.

        Returns:
            The import report, plus ``credentials``: one entry per account
            created, carrying the password. This is the only time those values
            exist in readable form — they are not stored and cannot be fetched
            again, so a lost one is replaced by a reset rather than recovered.

        Raises:
            ValidationError: If the file cannot be parsed.
            ImportTooManyRowsError: If the file exceeds the row cap.
        """
        table = self._read_table(filename, content)
        self._check_row_cap(len(table.rows))
        self._create_accounts = create_accounts
        self._credentials = []
        with transaction(self._conn):
            report = self._run(kind, table.rows, column_mapping)
        return {**report.to_dict(), "credentials": self._credentials}

    # ── Parsing ──────────────────────────────────────────────────────────────

    def _read_table(self, filename: str, content: bytes) -> ParsedTable:
        """Route an upload to the right parser.

        Args:
            filename: The upload's name.
            content: The raw bytes.

        Returns:
            The parsed table.

        Raises:
            ValidationError: If the file cannot be parsed as a spreadsheet.
        """
        if filename.lower().endswith((".xlsx", ".xlsm")):
            return self._read_xlsx(content)
        return self._read_csv(content)

    def _read_csv(self, content: bytes) -> ParsedTable:
        """Parse a CSV file, whatever delimiter its locale uses.

        The delimiter is sniffed from the first two kilobytes with a comma
        fallback — a German or French export opens as one column if the comma is
        assumed. Files are read as ``utf-8-sig`` so a BOM, which Excel writes, is
        not mistaken for part of the first header.

        Args:
            content: The raw bytes.

        Returns:
            The parsed table.

        Raises:
            ValidationError: If the file has no usable header row.
        """
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            # Excel on a German or French Windows still writes cp1252 by default, so
            # this is an ordinary file rather than a broken one. Unguarded it raised
            # past the domain handlers as a 500 -- "the server failed to handle this
            # request" — for a file whose only sin was an umlaut. The .xlsx path
            # beside it already reported its parse failures as 422.
            raise ValidationError(
                "The file is not UTF-8. Save it as UTF-8 (or CSV UTF-8) and retry.",
                field="file",
            ) from error
        try:
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=";,\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise ValidationError("The file has no header row.", field="file")
        headers = [str(header) for header in reader.fieldnames]
        rows = [dict(row) for row in reader]
        return ParsedTable(headers=headers, rows=rows)

    def _read_xlsx(self, content: bytes) -> ParsedTable:
        """Parse an .xlsx workbook, which a browser cannot do.

        ``read_only`` keeps the whole file from being materialised in memory and
        ``data_only`` reads cached values rather than formulas.

        Args:
            content: The raw bytes.

        Returns:
            The first sheet as a table.

        Raises:
            ValidationError: If the bytes are not a readable workbook.
        """
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except openpyxl.utils.exceptions.InvalidFileException as exc:  # type: ignore[attr-defined]
            raise ValidationError("The file is not a readable workbook.", field="file") from exc
        try:
            sheet = workbook.active
            if sheet is None:
                raise ValidationError("The workbook has no data.", field="file")
            iterator = sheet.iter_rows(values_only=True)
            header_row = next(iterator, None)
            if header_row is None:
                raise ValidationError("The workbook has no data.", field="file")
            headers = [
                f"column_{index}" if value is None else str(value).strip()
                for index, value in enumerate(header_row)
            ]
            if not any(headers):
                raise ValidationError("The workbook has no header row.", field="file")
            rows = [
                {headers[index]: _cell_text(cell) for index, cell in enumerate(row)}
                for row in iterator
                if any(cell is not None for cell in row)
            ]
            return ParsedTable(headers=headers, rows=rows)
        finally:
            workbook.close()

    # ── Importing ────────────────────────────────────────────────────────────

    def _run(
        self, kind: str, rows: list[dict[str, str]], column_mapping: dict[str, str]
    ) -> ImportReport:
        """Run one import, collecting per-row failures.

        Each row is its own try, and a rejected row is reported with its line number
        and a machine-readable code while the rest carry on — a teacher pasting three
        hundred rows wants the good ones recorded, not the file refused.

        Args:
            kind: ``students``, ``teachers``, ``courses`` or ``grades``.
            rows: The data rows.
            column_mapping: Field name to source column name.

        Returns:
            Counts and per-row failures.

        Raises:
            ValidationError: If the kind is not one this service imports. This used
                to be an ``else`` that ran the grade importer, so a typo in the path
                silently wrote a file of students as grades and reported success.
        """
        importers = {
            "students": self._import_student,
            "teachers": self._import_teacher,
            "courses": self._import_course,
            "grades": self._import_grade,
        }
        one = importers.get(kind)
        if one is None:
            raise ValidationError(f"Unknown import kind {kind!r}.", field="kind", value=kind)

        report = ImportReport()
        self._import_rows(rows, column_mapping, report, one)
        return report

    def _import_rows(
        self,
        rows: list[dict[str, str]],
        column_mapping: dict[str, str],
        report: ImportReport,
        one: Callable[[dict[str, str], dict[str, str]], None],
    ) -> None:
        """Apply a per-row importer, counting outcomes.

        Args:
            rows: The data rows.
            column_mapping: Field name to source column name.
            report: Accumulates imported/skipped counts and errors.
            one: The kind-specific importer, one row at a time.
        """
        for line_number, row in enumerate(rows, start=2):  # line 1 is the header
            try:
                one(row, column_mapping)
            except ValueError as exc:
                # Covers every domain error — the *NotFoundError family, validation,
                # duplicates, forbidden writes — plus the plain ValueError float()
                # and int() raise on unparseable numbers.
                report.skipped += 1
                report.errors.append((line_number, getattr(exc, "code", "INVALID_NUMBER")))
            else:
                report.imported += 1

    def _import_student(self, row: dict[str, str], column_mapping: dict[str, str]) -> None:
        """Import one student row through the directory service."""
        student, password = self._directory.create_student(
            student_id=self._required(row, column_mapping, "student_id"),
            first_name=self._required(row, column_mapping, "first_name"),
            last_name=self._required(row, column_mapping, "last_name"),
            email=self._required(row, column_mapping, "email"),
            is_active=self._boolean(row, column_mapping, "is_active", default=True),
            phone=self._optional(row, column_mapping, "phone") or None,
            date_of_birth=self._iso_date(row, column_mapping, "date_of_birth"),
            cohort=self._optional(row, column_mapping, "cohort") or None,
            create_account=self._create_accounts,
        )
        if password is not None:
            self._credentials.append(
                {
                    "student_id": str(student["student_id"]),
                    "full_name": f"{student['first_name']} {student['last_name']}",
                    "email": str(student["email"]),
                    "initial_password": password,
                }
            )

    def _import_teacher(self, row: dict[str, str], column_mapping: dict[str, str]) -> None:
        """Import one teacher row as a sign-in account.

        Shorter than its student counterpart because there is nothing else to write:
        a teacher has no directory record, only an account. ``create_account`` is not
        honoured here for the same reason — an account is the entire import.
        """
        full_name = self._required(row, column_mapping, "full_name")
        email = self._required(row, column_mapping, "email")
        _, password = UserService(self._conn, self._principal).create(
            email=email, full_name=full_name, role=Role.TEACHER
        )
        # No `student_id` key at all rather than an empty one: the field is optional
        # on the wire, and a blank string would render as a trailing separator next
        # to every teacher's name.
        self._credentials.append(
            {"full_name": full_name, "email": email, "initial_password": password}
        )

    def _import_course(self, row: dict[str, str], column_mapping: dict[str, str]) -> None:
        """Import one course row through the directory service."""
        payload: dict[str, Any] = {
            "course_id": self._required(row, column_mapping, "course_id"),
            "name": self._required(row, column_mapping, "name"),
        }
        for field in ("max_grade", "passing_grade", "max_students", "credits"):
            value = self._optional(row, column_mapping, field)
            if value:
                payload[field] = float(value)
        for field in ("term", "description", "room", "schedule", "department"):
            value = self._optional(row, column_mapping, field)
            if value:
                payload[field] = value
        for field in ("start_date", "end_date"):
            value = self._iso_date(row, column_mapping, field)
            if value is not None:
                payload[field] = value
        self._directory.create_course(payload)

    def _import_grade(self, row: dict[str, str], column_mapping: dict[str, str]) -> None:
        """Import one grade row through the grading service.

        The service checks that the caller may grade the course, so a teacher
        cannot import marks into a colleague's course — that row fails with
        ``FORBIDDEN`` while the rest of the file imports.
        """
        weight = self._optional(row, column_mapping, "weight")
        self._grading.record(
            student_id=self._required(row, column_mapping, "student_id"),
            course_id=self._required(row, column_mapping, "course_id"),
            score=float(self._required(row, column_mapping, "score")),
            date=self._required(row, column_mapping, "date"),
            title=self._optional(row, column_mapping, "title"),
            weight=float(weight) if weight else 1.0,
            notes=self._optional(row, column_mapping, "notes"),
        )

    # ── Field helpers ────────────────────────────────────────────────────────

    def _required(self, row: dict[str, str], column_mapping: dict[str, str], field: str) -> str:
        """Return a required field's trimmed value.

        Args:
            row: One data row.
            column_mapping: Field name to source column name.
            field: The gradebook field being read.

        Returns:
            The trimmed value.

        Raises:
            _UnmappedFieldError: If no column is mapped to the field.
            _MissingValueError: If the mapped column's cell is empty.
        """
        column = column_mapping.get(field)
        if not column:
            raise _UnmappedFieldError(f"No column mapped to {field!r}.", field=field)
        value = (row.get(column) or "").strip()
        if not value:
            raise _MissingValueError(
                f"Column {column!r} is empty in this row.", field=field, column=column
            )
        return value

    def _optional(self, row: dict[str, str], column_mapping: dict[str, str], field: str) -> str:
        """Return an optional field's trimmed value, or an empty string."""
        column = column_mapping.get(field)
        if not column:
            return ""
        return (row.get(column) or "").strip()

    def _iso_date(
        self, row: dict[str, str], column_mapping: dict[str, str], field: str
    ) -> date | None:
        """Parse an optional ISO date.

        Args:
            row: One data row.
            column_mapping: Field name to source column name.
            field: The date field being read.

        Returns:
            The date, or None when the column is unmapped or empty.

        Raises:
            ValidationError: If the value is not ISO ``YYYY-MM-DD``.
        """
        value = self._optional(row, column_mapping, field)
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError(
                f"{field} must be ISO YYYY-MM-DD.", field=field, value=value
            ) from exc

    def _boolean(
        self, row: dict[str, str], column_mapping: dict[str, str], field: str, *, default: bool
    ) -> bool:
        """Parse an optional boolean field.

        Args:
            row: One data row.
            column_mapping: Field name to source column name.
            field: The boolean field being read.
            default: Value when the column is unmapped or empty.

        Returns:
            The parsed boolean.

        Raises:
            ValidationError: If the value is not a recognised boolean.
        """
        value = self._optional(row, column_mapping, field)
        if not value:
            return default
        lowered = value.lower()
        if lowered in {"1", "true", "yes", "y"}:
            return True
        if lowered in {"0", "false", "no", "n"}:
            return False
        raise ValidationError(f"{field} must be true or false.", field=field, value=value)

    def _check_row_cap(self, row_count: int) -> None:
        """Enforce the row cap.

        Args:
            row_count: How many data rows the file has.

        Raises:
            ImportTooManyRowsError: If the count exceeds the configured cap.
        """
        if row_count > self._max_rows:
            raise ImportTooManyRowsError(
                f"Import has {row_count} rows; the cap is {self._max_rows}.",
                rows=row_count,
                limit=self._max_rows,
            )
