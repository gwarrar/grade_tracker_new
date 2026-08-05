"""Notes on students and courses.

A note is a scoped remark attached to a student record or a course — staff
observations on one side, a course thread the class writes together on the other.

There is deliberately no edit: nobody edits anyone's note, including their own. A
wrong note is deleted and reposted, and the audit entry the delete writes is the
tombstone — which is also why there is no soft delete, and every read is spared a
``deleted_at`` filter.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from notenverwaltung.exceptions import ForbiddenError, NoteNotFoundError, ValidationError
from notenverwaltung.models import Role
from notenverwaltung.storage import transaction
from services import audit
from services.directory import DirectoryService
from services.scoping import Principal, note_scope

_NOTE_SELECT = "id, entity, entity_id, body, visibility, author_id, author_name, created_at"


class NotesService:
    """Scoped notes attached to a student record or a course."""

    def __init__(self, conn: sqlite3.Connection, principal: Principal) -> None:
        """Bind the service to a request.

        Args:
            conn: The request's connection.
            principal: The authenticated caller.
        """
        self._conn = conn
        self._principal = principal
        # Entity visibility is proven by the directory's scoped fetches: a note on a
        # student or course the caller cannot see does not exist as far as they do.
        self._directory = DirectoryService(conn, principal)

    def list_student_notes(self, student_id: str) -> list[dict[str, Any]]:
        """List the notes on a student record the caller may read.

        Args:
            student_id: Which student.

        Returns:
            One entry per visible note, newest first.

        Raises:
            StudentNotFoundError: If the student is outside the caller's scope.
        """
        self._directory.get_student(student_id)
        return self._list("student", student_id)

    def list_course_notes(self, course_id: str) -> list[dict[str, Any]]:
        """List the notes on a course the caller may read.

        Args:
            course_id: Which course.

        Returns:
            One entry per visible note, newest first.

        Raises:
            CourseNotFoundError: If the course is outside the caller's scope.
        """
        self._directory.get_course(course_id)
        return self._list("course", course_id)

    def create_student_note(
        self, student_id: str, body: str, visibility: str | None = None
    ) -> dict[str, Any]:
        """Add a note to a student record.

        Args:
            student_id: Which student.
            body: The note text.
            visibility: Who may read it. Defaults to ``staff`` — a note on a student
                record is staff-written.

        Returns:
            The stored note.

        Raises:
            ForbiddenError: If the caller is not staff.
            StudentNotFoundError: If the student is outside the caller's scope.
            ValidationError: If the visibility is unknown.
        """
        if not self._principal.can(Role.TEACHER):
            raise ForbiddenError("A note on a student record is staff-written.")
        self._directory.get_student(student_id)
        return self._create("student", student_id, body, visibility or "staff")

    def create_course_note(
        self, course_id: str, body: str, visibility: str | None = None
    ) -> dict[str, Any]:
        """Add a note to a course.

        Args:
            course_id: Which course.
            body: The note text.
            visibility: Who may read it. Defaults to ``course`` — ``staff`` would hide
                a student's note from their classmates, defeating the purpose.

        Returns:
            The stored note.

        Raises:
            CourseNotFoundError: If the course is outside the caller's scope.
            ValidationError: If the visibility is unknown.
        """
        self._directory.get_course(course_id)
        return self._create("course", course_id, body, visibility or "course")

    def delete_note(self, note_id: int) -> None:
        """Delete a note, keeping a full snapshot in the audit log.

        Args:
            note_id: Which note.

        Raises:
            NoteNotFoundError: If it does not exist **or** the caller may not read it.
            ForbiddenError: If the caller is neither the author nor an administrator.
        """
        scope = note_scope(self._principal)
        row = self._conn.execute(
            f"SELECT {_NOTE_SELECT} FROM notes"  # noqa: S608
            f" WHERE id = ? AND ({scope.sql})",
            (note_id, *scope.params),
        ).fetchone()
        if row is None:
            raise NoteNotFoundError(f"No note with id {note_id!r}.", note_id=note_id)
        if not self._principal.is_admin and row["author_id"] != self._principal.user_id:
            raise ForbiddenError(
                "Only the author or an administrator may delete a note.", note_id=note_id
            )

        with transaction(self._conn):
            self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            audit.record(
                self._conn,
                actor_user_id=self._principal.user_id,
                entity="note",
                entity_id=str(note_id),
                action="delete",
                before=dict(row),
            )

    def _list(self, entity: str, entity_id: str) -> list[dict[str, Any]]:
        """List the visible notes on one entity, newest first."""
        scope = note_scope(self._principal)
        rows = self._conn.execute(
            f"SELECT {_NOTE_SELECT} FROM notes"  # noqa: S608
            f" WHERE entity = ? AND entity_id = ? AND ({scope.sql})"
            " ORDER BY created_at DESC, id DESC",
            (entity, entity_id, *scope.params),
        )
        return [dict(row) for row in rows]

    def _create(self, entity: str, entity_id: str, body: str, visibility: str) -> dict[str, Any]:
        """Insert one note and return it as stored.

        The author's name is copied into the row so it survives their account.
        """
        try:
            cursor = self._conn.execute(
                "INSERT INTO notes (entity, entity_id, body, visibility, author_id, author_name)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entity,
                    entity_id,
                    body,
                    visibility,
                    self._principal.user_id,
                    self._principal.full_name,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(
                f"Unknown note visibility {visibility!r}.",
                field="visibility",
                allowed=["private", "staff", "shared", "course"],
            ) from exc

        row = self._conn.execute(
            f"SELECT {_NOTE_SELECT} FROM notes WHERE id = ?",  # noqa: S608
            (cursor.lastrowid or 0,),
        ).fetchone()
        return dict(row)
