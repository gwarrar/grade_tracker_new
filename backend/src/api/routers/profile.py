"""The signed-in user's own account: preferences, password, active sessions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from api.deps import SESSION_COOKIE, CurrentUser, DbConn, get_auth
from api.routers.auth import to_response
from api.schemas.auth import (
    MessageResponse,
    PasswordChangeRequest,
    PreferencesRequest,
    PrincipalResponse,
    SessionResponse,
)
from api.security import hash_token, utc_now
from notenverwaltung.exceptions import ValidationError
from notenverwaltung.models import SUPPORTED_LOCALES, Theme
from notenverwaltung.storage import transaction
from services.auth import AuthService

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.patch(
    "",
    response_model=PrincipalResponse,
    summary="Update your own preferences",
    description=(
        "Changes display name, language or colour scheme for the signed-in user.\n\n"
        "Preferences are stored on the account rather than only in the browser, so "
        "they follow the user to another device. Passing `null` for locale or theme "
        "clears the preference and falls back to the organisation default."
    ),
    responses={422: {"description": "`VALIDATION_ERROR` — unsupported locale or theme."}},
)
def update_preferences(
    payload: PreferencesRequest, principal: CurrentUser, conn: DbConn
) -> PrincipalResponse:
    """Update the caller's own preferences.

    Args:
        payload: The requested changes. Omitted fields are left alone.
        principal: The authenticated caller.
        conn: The request's database connection.

    Returns:
        The refreshed principal.

    Raises:
        ValidationError: If the locale has no translation file or the theme is unknown.
    """
    fields = payload.model_dump(exclude_unset=True)

    if fields.get("locale") is not None and fields["locale"] not in SUPPORTED_LOCALES:
        raise ValidationError(
            f"No translation ships for {fields['locale']!r}.",
            field="locale",
            supported=list(SUPPORTED_LOCALES),
        )
    if "theme" in fields and fields["theme"] is not None:
        try:
            Theme(fields["theme"])
        except ValueError as exc:
            raise ValidationError(f"Unknown theme {fields['theme']!r}.", field="theme") from exc

    assignments = {
        "locale": fields.get("locale"),
        "theme_preference": fields.get("theme"),
        "full_name": fields.get("full_name"),
    }
    # Only touch what the caller actually sent. Writing every column would turn an
    # omitted field into an explicit null.
    updates = {
        column: value
        for column, value in assignments.items()
        if column.replace("theme_preference", "theme") in fields
    }

    if updates:
        clause = ", ".join(f"{column} = ?" for column in updates)
        with transaction(conn):
            conn.execute(
                f"UPDATE users SET {clause}, updated_at = ? WHERE id = ?",  # noqa: S608
                (*updates.values(), utc_now(), principal.user_id),
            )

    row = conn.execute(
        "SELECT id, email, role, full_name, is_active, locale, theme_preference"
        " FROM users WHERE id = ?",
        (principal.user_id,),
    ).fetchone()
    refreshed = principal.__class__(
        user_id=row["id"],
        role=principal.role,
        email=row["email"],
        full_name=row["full_name"],
        student_id=principal.student_id,
        locale=row["locale"] or principal.locale,
        theme=Theme(row["theme_preference"]) if row["theme_preference"] else principal.theme,
    )
    return to_response(refreshed)


@router.post(
    "/password",
    response_model=MessageResponse,
    summary="Change your password",
    description=(
        "Requires the current password even though you are signed in — an unattended "
        "browser should not be enough to take an account over permanently.\n\n"
        "**Every session is closed, including this one.** A password change is how "
        "someone responds to a suspected compromise; leaving the attacker's session "
        "alive would defeat the point. The client must sign in again."
    ),
    responses={
        401: {"description": "`INVALID_CREDENTIALS` — the current password is wrong."},
        422: {"description": "`VALIDATION_ERROR` — the replacement is too short or unchanged."},
    },
)
def change_password(
    payload: PasswordChangeRequest,
    principal: CurrentUser,
    conn: DbConn,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth)],
) -> MessageResponse:
    """Change the caller's password.

    Args:
        payload: Current and replacement passwords.
        principal: The authenticated caller.
        conn: The request's database connection.
        response: The outgoing response, which clears the now-invalid cookie.
        auth: The authentication service.

    Returns:
        An acknowledgement.
    """
    with transaction(conn):
        auth.change_password(principal.user_id, payload.current_password, payload.new_password)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return MessageResponse(code="PASSWORD_CHANGED")


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    summary="List your active sessions",
    description=(
        "Every device currently signed in as you, most recently active first. The "
        "session making the request is flagged `is_current`.\n\n"
        "`token_sha256` identifies a session for revocation; the session token itself "
        "cannot be recovered from it."
    ),
)
def list_sessions(
    principal: CurrentUser,
    request: Request,
    auth: Annotated[AuthService, Depends(get_auth)],
) -> list[SessionResponse]:
    """List the caller's live sessions.

    Args:
        principal: The authenticated caller.
        request: The incoming request, used to flag the current session.
        auth: The authentication service.

    Returns:
        One entry per live session.
    """
    current = request.cookies.get(SESSION_COOKIE)
    current_hash = hash_token(current) if current else ""

    return [
        SessionResponse(
            token_sha256=str(row["token_sha256"]),
            created_at=str(row["created_at"]),
            last_seen_at=str(row["last_seen_at"]) if row["last_seen_at"] else None,
            user_agent=str(row["user_agent"]),
            ip_address=str(row["ip_address"]),
            is_current=row["token_sha256"] == current_hash,
        )
        for row in auth.list_sessions(principal.user_id)
    ]


@router.delete(
    "/sessions/{token_sha256}",
    response_model=MessageResponse,
    summary="Revoke one session",
    description=(
        "Signs one device out. The lookup is scoped to your own account, so a caller "
        "cannot revoke somebody else's session by guessing a hash."
    ),
    responses={404: {"description": "`SESSION_NOT_FOUND` — no such session on this account."}},
)
def revoke_session(
    token_sha256: str,
    principal: CurrentUser,
    conn: DbConn,
    auth: Annotated[AuthService, Depends(get_auth)],
) -> MessageResponse:
    """Revoke one of the caller's sessions.

    Args:
        token_sha256: Which session to close.
        principal: The authenticated caller.
        conn: The request's database connection.
        auth: The authentication service.

    Returns:
        An acknowledgement.

    Raises:
        ValidationError: If no such session belongs to this account.
    """
    with transaction(conn):
        removed = auth.revoke_session(principal.user_id, token_sha256)
    if not removed:
        error = ValidationError("No such session on this account.", field="token_sha256")
        error.code = "SESSION_NOT_FOUND"
        error.http_status = 404
        raise error
    return MessageResponse(code="SESSION_REVOKED", count=1)


@router.post(
    "/sessions/revoke-others",
    response_model=MessageResponse,
    summary="Sign out your other devices",
    description="Closes every session except the one making the request.",
)
def revoke_other_sessions(
    principal: CurrentUser,
    request: Request,
    conn: DbConn,
    auth: Annotated[AuthService, Depends(get_auth)],
) -> MessageResponse:
    """Close every session except the caller's own.

    Args:
        principal: The authenticated caller.
        request: The incoming request, whose session is preserved.
        conn: The request's database connection.
        auth: The authentication service.

    Returns:
        How many sessions were closed.
    """
    with transaction(conn):
        closed = auth.logout_everywhere(
            principal.user_id, keep_token=request.cookies.get(SESSION_COOKIE)
        )
    return MessageResponse(code="SESSIONS_REVOKED", count=closed)
