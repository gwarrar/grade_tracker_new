"""FastAPI dependencies: database connections, the current principal, role gates."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request

from api.config import Settings, get_settings
from notenverwaltung.exceptions import (
    ForbiddenError,
    NotAuthenticatedError,
    PasswordChangeRequiredError,
)
from notenverwaltung.models import Role
from notenverwaltung.storage import connect
from services.auth import AuthService, LoginThrottle
from services.scoping import Principal

SESSION_COOKIE = "gt_session"


def get_throttle(request: Request) -> LoginThrottle:
    """Return the sign-in throttle for this application.

    Held on the application rather than in a module-level global. It has to outlive a
    request -- a per-request throttle would count to five and forget -- but a
    process-level one outlives the *application*, so two apps in the same process
    share a lockout. That is invisible in production and produces baffling failures
    anywhere more than one app is constructed.

    Args:
        request: The incoming request, which carries the application.

    Returns:
        The application's throttle.
    """
    return request.app.state.login_throttle


def get_db(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Generator[sqlite3.Connection]:
    """Open a connection for the duration of one request.

    Args:
        settings: Application settings.

    Yields:
        A configured connection, closed when the request finishes.
    """
    conn = connect(settings.database_file)
    try:
        yield conn
    finally:
        conn.close()


DbConn = Annotated[sqlite3.Connection, Depends(get_db)]


def get_auth(
    conn: DbConn,
    throttle: Annotated[LoginThrottle, Depends(get_throttle)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    """Return the authentication service for this request.

    Args:
        conn: The request's connection.
        throttle: The shared sign-in throttle.
        settings: Application settings.

    Returns:
        The service.
    """
    return AuthService(conn, throttle, settings.session_ttl_hours)


def get_optional_principal(
    request: Request, auth: Annotated[AuthService, Depends(get_auth)]
) -> Principal | None:
    """Resolve the caller, or ``None`` if they are not signed in.

    Args:
        request: The incoming request.
        auth: The authentication service.

    Returns:
        The principal, or ``None``.
    """
    token = request.cookies.get(SESSION_COOKIE)
    return auth.resolve(token) if token else None


#: Paths a caller may still reach while holding a password they have not chosen.
#: Exactly the three needed to get out of that state: read who you are, change it,
#: or leave. Anything else is refused, which is what makes the flag a gate rather
#: than a suggestion.
_PASSWORD_CHANGE_EXEMPT = frozenset({"/auth/me", "/auth/logout", "/profile/password"})


def get_principal(
    request: Request,
    principal: Annotated[Principal | None, Depends(get_optional_principal)],
) -> Principal:
    """Require a signed-in caller who is not still holding a generated password.

    The second half is the point. ``must_change_password`` was written on account
    creation and on reset, carried on the principal and published at ``/auth/me``,
    and then read by nobody — so an administrator who imported four hundred students
    handed out four hundred passwords that stayed valid for as long as nobody got
    round to changing them. Migration 008 says the application "must insist on the
    change rather than suggest it"; only the interface was suggesting it.

    Enforced here rather than on each route because here it cannot be forgotten on
    the endpoint added next month.

    Args:
        request: The incoming request, for the exemption check.
        principal: The resolved principal, if any.

    Returns:
        The principal.

    Raises:
        NotAuthenticatedError: If nobody is signed in.
        ForbiddenError: If the caller must change their password first.
    """
    if principal is None:
        raise NotAuthenticatedError("Sign-in required.")
    if principal.must_change_password and request.url.path not in _PASSWORD_CHANGE_EXEMPT:
        raise PasswordChangeRequiredError(
            "The initial password must be changed before anything else."
        )
    return principal


CurrentUser = Annotated[Principal, Depends(get_principal)]
MaybeUser = Annotated[Principal | None, Depends(get_optional_principal)]


def require_role(minimum: Role):  # noqa: ANN201 - returns an opaque FastAPI dependency
    """Build a dependency asserting a minimum role.

    This gates the **action**, never the rows. "May this user record grades at all"
    is answered here; "may this user record a grade for *this* student" is answered
    by :mod:`services.scoping`, in the query. Mixing the two is how row checks get
    forgotten on the endpoint added next month.

    Args:
        minimum: The least privileged role permitted.

    Returns:
        A dependency callable that returns the principal or raises.
    """

    def dependency(principal: CurrentUser) -> Principal:
        if not principal.can(minimum):
            raise ForbiddenError(
                f"This action requires the {minimum} role.",
                required_role=str(minimum),
                actual_role=str(principal.role),
            )
        return principal

    return dependency


TeacherUser = Annotated[Principal, Depends(require_role(Role.TEACHER))]
AdminUser = Annotated[Principal, Depends(require_role(Role.ADMIN))]
SuperAdminUser = Annotated[Principal, Depends(require_role(Role.SUPERADMIN))]
