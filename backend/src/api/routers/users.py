"""Account administration.

Admin and above. The interesting rules — no self-demotion, no granting a role at
or above your own, no removing the last superadmin — live in the service, not
here, so a second caller cannot arrive later and skip them.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from api.deps import AdminUser, CurrentUser, DbConn
from notenverwaltung.models.user import Role
from notenverwaltung.storage import transaction
from services.users import UserService

router = APIRouter(prefix="/admin/users", tags=["Users"])


class UserResponse(BaseModel):
    """One account.

    Carries no password material at all — the service's record type has no such
    field, so there is nothing here to forget to exclude.
    """

    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    locale: str | None
    created_at: str
    updated_at: str | None
    student_id: str | None = Field(description="The student record linked to this account, if any.")
    session_count: int = Field(description="How many unexpired sessions this account has.")


class CreateUserRequest(BaseModel):
    """A new account."""

    email: str = Field(min_length=3, max_length=255, examples=["k.weber@school.test"])
    full_name: str = Field(min_length=1, max_length=120, examples=["Katrin Weber"])
    role: Role = Field(examples=["teacher"])


class CreatedUserResponse(BaseModel):
    """A newly created account and its one-time password."""

    user: UserResponse
    initial_password: str = Field(
        description=(
            "Shown once and never retrievable. Hand it to the person; they change "
            "it from their profile."
        )
    )


class RoleRequest(BaseModel):
    """A role change."""

    role: Role


class ActiveRequest(BaseModel):
    """An activation change."""

    is_active: bool


class PasswordResetResponse(BaseModel):
    """A freshly issued temporary password."""

    temporary_password: str = Field(
        description="Shown once. Every session for the account has been revoked."
    )


def service(conn: DbConn, user: CurrentUser) -> UserService:
    """Build the user service for this request.

    Args:
        conn: The request's connection.
        user: The acting administrator, held by the service so the
            self-modification rules cannot be bypassed.

    Returns:
        The service.
    """
    return UserService(conn, user)


Users = Annotated[UserService, Depends(service)]


@router.get("", response_model=list[UserResponse], summary="List accounts")
def list_users(
    _: AdminUser,
    users: Users,
    q: Annotated[str, Query(description="Substring of name or email.")] = "",
    include_inactive: Annotated[
        bool, Query(description="Include deactivated accounts. On by default.")
    ] = True,
) -> list[UserResponse]:
    """List accounts.

    Args:
        _: Enforces the admin role.
        users: The service.
        q: Search term.
        include_inactive: Whether deactivated accounts appear.

    Returns:
        Matching accounts, ordered by name.
    """
    # asdict rather than vars: UserRecord is a slots dataclass and has no __dict__.
    return [
        UserResponse(**asdict(record))
        for record in users.list(query=q, include_inactive=include_inactive)
    ]


@router.post(
    "",
    response_model=CreatedUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    description=(
        "The initial password is generated and returned once. An administrator "
        "choosing it would mean the password is known to two people from the "
        "moment it exists."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — you cannot grant a role at or above your own."},
        409: {"description": "`DUPLICATE_ENTRY` — that email already has an account."},
    },
)
def create_user(
    body: CreateUserRequest, _: AdminUser, users: Users, conn: DbConn
) -> CreatedUserResponse:
    """Create an account.

    Args:
        body: Email, name and role.
        _: Enforces the admin role.
        users: The service.
        conn: The request's connection, for the transaction.

    Returns:
        The account and its one-time password.
    """
    with transaction(conn):
        record, password = users.create(email=body.email, full_name=body.full_name, role=body.role)
    return CreatedUserResponse(user=UserResponse(**asdict(record)), initial_password=password)


@router.put(
    "/{user_id}/role",
    response_model=UserResponse,
    summary="Change an account's role",
    responses={
        403: {"description": "`FORBIDDEN` — outside what you may grant or act on."},
        409: {
            "description": (
                "`CANNOT_MODIFY_SELF` — you cannot change your own role. "
                "`LAST_SUPERADMIN` — someone must be able to configure the system."
            )
        },
    },
)
def set_role(
    user_id: int, body: RoleRequest, _: AdminUser, users: Users, conn: DbConn
) -> UserResponse:
    """Change what an account may do.

    Args:
        user_id: Which account.
        body: The new role.
        _: Enforces the admin role.
        users: The service.
        conn: The request's connection.

    Returns:
        The updated account.
    """
    with transaction(conn):
        record = users.set_role(user_id, body.role)
    return UserResponse(**asdict(record))


@router.put(
    "/{user_id}/active",
    response_model=UserResponse,
    summary="Activate or deactivate an account",
    description=(
        "Deactivating also revokes every session for the account. An account that "
        "cannot sign in but stays signed in is not deactivated in any useful sense."
    ),
    responses={
        409: {"description": "`CANNOT_MODIFY_SELF` or `LAST_SUPERADMIN`."},
    },
)
def set_active(
    user_id: int, body: ActiveRequest, _: AdminUser, users: Users, conn: DbConn
) -> UserResponse:
    """Activate or deactivate an account.

    Args:
        user_id: Which account.
        body: The desired state.
        _: Enforces the admin role.
        users: The service.
        conn: The request's connection.

    Returns:
        The updated account.
    """
    with transaction(conn):
        record = users.set_active(user_id, active=body.is_active)
    return UserResponse(**asdict(record))


@router.post(
    "/{user_id}/reset-password",
    response_model=PasswordResetResponse,
    summary="Issue a temporary password",
    description=(
        "Mints a replacement and revokes every session. An administrator never "
        "sees an existing password — a reset is what you do when you suspect the "
        "account is compromised, and leaving the intruder signed in defeats it."
    ),
)
def reset_password(user_id: int, _: AdminUser, users: Users, conn: DbConn) -> PasswordResetResponse:
    """Issue a temporary password.

    Args:
        user_id: Which account.
        _: Enforces the admin role.
        users: The service.
        conn: The request's connection.

    Returns:
        The one-time password.
    """
    with transaction(conn):
        temporary = users.reset_password(user_id)
    return PasswordResetResponse(temporary_password=temporary)
