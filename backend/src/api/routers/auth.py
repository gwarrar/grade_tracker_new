"""Sign in, sign out, and identify the current user."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from api.config import Settings, get_settings
from api.deps import SESSION_COOKIE, CurrentUser, DbConn, get_auth
from api.schemas.auth import LoginRequest, MessageResponse, PrincipalResponse
from notenverwaltung.storage import transaction
from services.auth import AuthService
from services.scoping import Principal

router = APIRouter(prefix="/auth", tags=["Authentication"])


def to_response(principal: Principal) -> PrincipalResponse:
    """Convert a principal into its wire representation."""
    return PrincipalResponse(
        user_id=principal.user_id,
        email=principal.email,
        full_name=principal.full_name,
        role=str(principal.role),
        student_id=principal.student_id,
        locale=principal.locale,
        theme=str(principal.theme),
        must_change_password=principal.must_change_password,
    )


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """Attach the session cookie.

    ``HttpOnly`` so script on the page cannot read it, which is what turns an XSS
    from "session stolen" into "session not stolen". ``SameSite=Lax`` blocks the
    cookie on cross-site POSTs, which is CSRF protection without a token dance.
    ``Secure`` everywhere except a purely local deployment, where there is no HTTPS
    to require — that judgement lives on the settings, which explains it.

    Args:
        response: The outgoing response.
        token: The raw session token.
        settings: Application settings, for the TTL and the cookie policy.
    """
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


@router.post(
    "/login",
    response_model=PrincipalResponse,
    summary="Sign in",
    description=(
        "Verifies credentials and opens a session, returned as an HttpOnly cookie.\n\n"
        "A wrong password and an unknown email produce the same `INVALID_CREDENTIALS` "
        "response and take the same time, so neither reveals whether an account exists. "
        "Repeated failures from one email and address are locked out temporarily."
    ),
    responses={
        401: {"description": "`INVALID_CREDENTIALS` — email or password is wrong."},
        403: {"description": "`ACCOUNT_DISABLED` — the account has been deactivated."},
        429: {
            "description": "`TOO_MANY_ATTEMPTS` — locked out; see `context.retry_after_seconds`."
        },
    },
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    conn: DbConn,
    auth: Annotated[AuthService, Depends(get_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PrincipalResponse:
    """Verify credentials and open a session.

    Args:
        payload: The submitted credentials.
        request: The incoming request, for the client address and user agent.
        response: The outgoing response, which receives the cookie.
        conn: The request's database connection.
        auth: The authentication service.
        settings: Application settings.

    Returns:
        The signed-in principal.
    """
    with transaction(conn):
        token, principal = auth.login(
            payload.email,
            payload.password,
            address=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
        )
    _set_session_cookie(response, token, settings)
    return to_response(principal)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Sign out",
    description="Closes the current session and clears the cookie.",
)
def logout(
    request: Request,
    response: Response,
    conn: DbConn,
    auth: Annotated[AuthService, Depends(get_auth)],
) -> MessageResponse:
    """Close the caller's session.

    Deliberately succeeds even when no session is present: a client clearing a
    session it already lost should not be handed an error.

    Args:
        request: The incoming request.
        response: The outgoing response, which clears the cookie.
        conn: The request's database connection.
        auth: The authentication service.

    Returns:
        An acknowledgement.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with transaction(conn):
            auth.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return MessageResponse(code="SIGNED_OUT")


@router.get(
    "/me",
    response_model=PrincipalResponse,
    summary="Identify the current user",
    description=(
        "Returns the signed-in user together with their resolved locale and theme, so "
        "the first render is already correct rather than flashing a default."
    ),
    responses={401: {"description": "`NOT_AUTHENTICATED` — no valid session."}},
    status_code=status.HTTP_200_OK,
)
def me(principal: CurrentUser) -> PrincipalResponse:
    """Return the signed-in user.

    Args:
        principal: The authenticated caller.

    Returns:
        Their identity and resolved preferences.
    """
    return to_response(principal)
