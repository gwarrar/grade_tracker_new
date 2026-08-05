"""Notes on students and courses.

Every handler parses, delegates and serialises. No SQL, no business logic — the
architecture test enforces both.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from api.deps import CurrentUser, DbConn, TeacherUser
from api.schemas.domain import NoteCreateRequest, NoteResponse
from services.notes import NotesService

router = APIRouter(tags=["Notes"])

VISIBILITY_NOTE = (
    "\n\nVisibility decides who reads each note: administrators see all of them, a "
    "teacher sees `staff`, `shared` and `course` notes plus their own, a student "
    "sees `shared` and `course` notes plus their own."
)


def notes(conn: DbConn, principal: CurrentUser) -> NotesService:
    """Build the notes service for this request.

    Args:
        conn: The request's connection.
        principal: The authenticated caller.

    Returns:
        The service.
    """
    return NotesService(conn, principal)


Notes = Annotated[NotesService, Depends(notes)]


@router.get(
    "/students/{student_id}/notes",
    response_model=list[NoteResponse],
    summary="List a student's notes",
    tags=["Students"],
    description="A note on a student record is staff-written." + VISIBILITY_NOTE,
    responses={404: {"description": "`STUDENT_NOT_FOUND` — unknown, or outside your scope."}},
)
def list_student_notes(student_id: str, service: Notes, _: TeacherUser) -> list[NoteResponse]:
    """List the notes on one student the caller may read."""
    return [NoteResponse(**row) for row in service.list_student_notes(student_id)]


@router.post(
    "/students/{student_id}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a note to a student",
    tags=["Students"],
    description=(
        "A note on a student record is staff-written, and defaults to `staff` "
        "visibility. There is deliberately no edit: delete and repost."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — staff only."},
        404: {"description": "`STUDENT_NOT_FOUND` — unknown, or outside your scope."},
    },
)
def create_student_note(
    student_id: str, payload: NoteCreateRequest, service: Notes, _: TeacherUser
) -> NoteResponse:
    """Add a note to a student record."""
    return NoteResponse(**service.create_student_note(student_id, payload.body, payload.visibility))


@router.get(
    "/courses/{course_id}/notes",
    response_model=list[NoteResponse],
    summary="List a course's notes",
    tags=["Courses"],
    description=(
        "Students included — a course thread that excluded the class would not be a "
        "thread." + VISIBILITY_NOTE
    ),
    responses={404: {"description": "`COURSE_NOT_FOUND` — unknown, or outside your scope."}},
)
def list_course_notes(course_id: str, service: Notes) -> list[NoteResponse]:
    """List the notes on one course the caller may read."""
    return [NoteResponse(**row) for row in service.list_course_notes(course_id)]


@router.post(
    "/courses/{course_id}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a note to a course",
    tags=["Courses"],
    description=(
        "Students included — a course thread that excluded the class would not be a "
        "thread. Defaults to `course` visibility, since `staff` would hide a "
        "student's note from their classmates. There is deliberately no edit: "
        "delete and repost."
    ),
    responses={404: {"description": "`COURSE_NOT_FOUND` — unknown, or outside your scope."}},
)
def create_course_note(
    course_id: str, payload: NoteCreateRequest, service: Notes, _: CurrentUser
) -> NoteResponse:
    """Add a note to a course."""
    return NoteResponse(**service.create_course_note(course_id, payload.body, payload.visibility))


@router.delete(
    "/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a note",
    description=(
        "The author, or any administrator. The full note is written to the audit log "
        "as the tombstone — there is deliberately no edit, and no soft delete."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — only the author or an administrator."},
        404: {"description": "`NOTE_NOT_FOUND` — unknown, or outside your scope."},
    },
)
def delete_note(note_id: int, service: Notes) -> None:
    """Delete a note."""
    service.delete_note(note_id)
