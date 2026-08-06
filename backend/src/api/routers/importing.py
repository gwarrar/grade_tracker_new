"""Bulk import of students, courses and grades.

Parses, gates, delegates and serialises — no SQL, no business logic. The row-level
decisions (is this course in scope, is this row valid) live in the import service,
which applies the same checks a form would.

Two endpoints share one parser and one service:
``POST /import/{kind}/preview`` dry-runs the file inside a rolled-back transaction
and returns exactly what a commit would write, with per-row error codes; ``POST
/import/{kind}`` performs the import for real. Both take the raw file and the
column mapping the client built — optionally prefilled by the AI import-map
feature. The AI and import services stay decoupled: the mapping travels with the
request, and each side can change without the other noticing.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Request, UploadFile, status
from pydantic import BaseModel, Field

from api.config import Settings, get_settings
from api.deps import CurrentUser, DbConn
from notenverwaltung.exceptions import ForbiddenError, PayloadTooLargeError, ValidationError
from notenverwaltung.models import Role
from services.importing import ImportService
from services.scoping import Principal

router = APIRouter(prefix="/import", tags=["Import"])

#: Who may import each kind. Students and courses change the register itself, so
#: only administrators may; grades are a teacher's ordinary work.
_ROLE_BY_KIND = {"students": Role.ADMIN, "courses": Role.ADMIN, "grades": Role.TEACHER}

ImportKind = Annotated[
    str,
    Path(
        description="`students`, `courses` or `grades`.",
        examples=["grades"],
    ),
]

MappingForm = Annotated[
    str | None,
    Form(
        description=(
            "The column mapping as JSON: gradebook field name to source column "
            'name, e.g. `{"student_id": "Matrikelnummer"}`. Omit to have every '
            "row reported as unmapped — the preview also serves as the file "
            "inspection step for .xlsx uploads."
        )
    ),
]

AccountsForm = Annotated[
    bool,
    Form(
        description=(
            "Whether each imported student also gets a sign-in account, returned "
            "with a one-time password. Ignored for courses and grades. Turn it "
            "off for an archive of past cohorts, which should not become several "
            "hundred live credentials."
        )
    ),
]


class ImportRowError(BaseModel):
    """One rejected row in an import report."""

    line: int = Field(description="Data row number, the header counting as line 1.")
    code: str = Field(description="Stable error code, e.g. `DUPLICATE_ENTRY`.")


class ImportReportModel(BaseModel):
    """Outcome of an import, previewed or committed."""

    imported: int = Field(description="Rows written successfully.")
    skipped: int = Field(description="Rows rejected.")
    errors: list[ImportRowError] = Field(description="One entry per rejected row.")


class ImportedCredential(BaseModel):
    """A sign-in account minted by an import, and its one-time password."""

    student_id: str
    full_name: str
    email: str
    initial_password: str


class ImportCommitModel(ImportReportModel):
    """A committed import: the report, plus any accounts it created."""

    credentials: list[ImportedCredential] = Field(
        default_factory=list,
        description=(
            "One entry per sign-in account created, in row order. **This is the "
            "only time these passwords exist in readable form** — they are stored "
            "hashed and cannot be fetched again. Hand them out, then use the "
            "reset endpoint for anyone who loses theirs. Every account is flagged "
            "to require a change at first sign-in."
        ),
    )


class ImportPreviewModel(BaseModel):
    """What a preview reveals about the file and its dry run."""

    kind: str = Field(description="The import kind requested.")
    headers: list[str] = Field(description="The file's header row.")
    sample_rows: list[list[str]] = Field(
        description="A few data rows, for the mapping step before the AI call."
    )
    report: ImportReportModel = Field(description="The report the real import would have produced.")


def _require_kind_role(request: Request, principal: CurrentUser) -> Principal:
    """Gate an import by the kind named in the path.

    A route cannot pick a role dependency from a path parameter, so the check
    reads the kind here instead. This asserts the *action* — "may this user import
    students at all". Whether a specific row is in scope is answered by the
    services the import delegates to, exactly as it is for a form.

    Args:
        request: The incoming request, whose path carries the kind.
        principal: The authenticated caller.

    Returns:
        The principal, once its role passes.

    Raises:
        ValidationError: If the kind is not one of the three supported.
        ForbiddenError: If the caller lacks the kind's minimum role.
    """
    kind = request.path_params["kind"]
    minimum = _ROLE_BY_KIND.get(kind)
    if minimum is None:
        raise ValidationError(f"Unknown import kind {kind!r}.", field="kind", value=kind)
    if not principal.can(minimum):
        raise ForbiddenError(
            f"Importing {kind} requires the {minimum} role.",
            required_role=str(minimum),
            actual_role=str(principal.role),
        )
    return principal


KindRole = Annotated[Principal, Depends(_require_kind_role)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _mapping(raw: str | None) -> dict[str, str]:
    """Decode the optional mapping form field.

    Args:
        raw: The JSON text, or None.

    Returns:
        Field name to source column name.

    Raises:
        ValidationError: If the field is present but not a JSON object.
    """
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("The mapping field is not valid JSON.", field="mapping") from exc
    if not isinstance(value, dict):
        raise ValidationError("The mapping must be a JSON object.", field="mapping")
    return {str(key): str(item) for key, item in value.items()}


def _service(conn: DbConn, principal: KindRole, settings: SettingsDep) -> ImportService:
    """Build the import service for this request.

    Args:
        conn: The request's connection.
        principal: The gated caller.
        settings: Application settings, for the row cap.

    Returns:
        The service.
    """
    return ImportService(conn, principal, max_import_rows=settings.max_import_rows)


Importing = Annotated[ImportService, Depends(_service)]


@router.post(
    "/{kind}/preview",
    response_model=ImportPreviewModel,
    summary="Dry-run an import",
    description=(
        "Parse the file and run the entire import inside a transaction that is "
        "then rolled back. The response shows the headers, a few sample rows, and "
        "the report a commit would produce — how many rows would land, how many "
        "would be rejected, and the line number plus error code of each rejected "
        "row. Nothing is written.\n\n"
        "Send the file without a mapping to use this as the inspection step for "
        ".xlsx uploads: the headers and sample rows come back, and every data row "
        "is reported as unmapped.\n\n"
        "Students and courses require the administrator role; grades require a "
        "teacher."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — below the kind's minimum role."},
        413: {"description": "`PAYLOAD_TOO_LARGE` or `IMPORT_TOO_MANY_ROWS`."},
        422: {
            "description": "`VALIDATION_ERROR` — unreadable file, unknown kind, "
            "bad mapping, or a row that would be rejected."
        },
    },
)
async def preview_import(
    kind: ImportKind,
    file: Annotated[UploadFile, File(description="CSV, TSV or .xlsx file.")],
    service: Importing,
    settings: SettingsDep,
    mapping: MappingForm = None,
    create_accounts: AccountsForm = True,
) -> ImportPreviewModel:
    """Preview an import without changing the database.

    Args:
        kind: Which kind of record the file holds.
        file: The uploaded spreadsheet.
        service: The import service.
        settings: Application settings, for the upload ceiling.
        mapping: The column mapping as JSON, if the caller has one.
        create_accounts: Whether student rows would also mint accounts, so the
            dry run counts the same address collisions a commit would.

    Returns:
        Headers, sample rows and the dry-run report.

    Raises:
        PayloadTooLargeError: If the file exceeds the configured ceiling.
    """
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            "Import exceeds the configured size limit.", limit=settings.max_upload_bytes
        )
    return ImportPreviewModel(
        **service.preview(
            kind=kind,
            filename=file.filename or "",
            content=content,
            column_mapping=_mapping(mapping),
            create_accounts=create_accounts,
        )
    )


@router.post(
    "/{kind}",
    response_model=ImportCommitModel,
    status_code=status.HTTP_200_OK,
    summary="Import a file",
    description=(
        "Parse the file and write every valid row. The whole batch and its audit "
        "entries commit together, so an import that fails halfway leaves nothing "
        "behind. Rows that would not survive the same checks a form applies are "
        "rejected individually and reported with their line number and error "
        "code — one bad row does not cost the rest of the file.\n\n"
        "Each successfully imported row produces its own audit entry. Students and "
        "courses require the administrator role; grades require a teacher.\n\n"
        "Student rows also mint a sign-in account unless `create_accounts` is "
        "false. Their one-time passwords come back in `credentials` and are "
        "available nowhere else."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — below the kind's minimum role."},
        413: {"description": "`PAYLOAD_TOO_LARGE` or `IMPORT_TOO_MANY_ROWS`."},
        422: {"description": "`VALIDATION_ERROR` — unreadable file, unknown kind, or bad mapping."},
    },
)
async def import_file(
    kind: ImportKind,
    file: Annotated[UploadFile, File(description="CSV, TSV or .xlsx file.")],
    service: Importing,
    settings: SettingsDep,
    mapping: MappingForm = None,
    create_accounts: AccountsForm = True,
) -> ImportCommitModel:
    """Import a file for real.

    Args:
        kind: Which kind of record the file holds.
        file: The uploaded spreadsheet.
        service: The import service.
        settings: Application settings, for the upload ceiling.
        mapping: The column mapping as JSON, if the caller has one.
        create_accounts: Whether each imported student also gets an account.

    Returns:
        The import report, and the credentials of any accounts created.

    Raises:
        PayloadTooLargeError: If the file exceeds the configured ceiling.
    """
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            "Import exceeds the configured size limit.", limit=settings.max_upload_bytes
        )
    return ImportCommitModel(
        **service.commit(
            kind=kind,
            filename=file.filename or "",
            content=content,
            column_mapping=_mapping(mapping),
            create_accounts=create_accounts,
        )
    )
