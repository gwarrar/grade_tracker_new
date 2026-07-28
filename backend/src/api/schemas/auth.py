"""Request and response models for authentication and the profile page."""

from __future__ import annotations

from pydantic import BaseModel, Field

from api.security import MIN_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    """Credentials submitted at sign-in.

    The address is **not** format-validated here, for two reasons. Sign-in only looks
    an address up, so a malformed one simply fails to match — rejecting it earlier
    achieves nothing except a different error for "malformed" than for "unknown",
    which tells an attacker something. And `EmailStr` refuses reserved TLDs such as
    `.local` and `.test`, which self-hosted deployments legitimately use; the domain
    models own the one email rule this system has, and a second stricter rule at the
    boundary would reject addresses the domain considers valid.
    """

    email: str = Field(
        min_length=1, description="The account's sign-in address.", examples=["a@b.co"]
    )
    password: str = Field(
        min_length=1,
        description="The account password. Never logged and never echoed back.",
        examples=["demo-password-2026"],
    )


class PrincipalResponse(BaseModel):
    """The signed-in user, as the frontend needs them.

    Returned by sign-in and by ``GET /auth/me``. Carries the resolved locale and
    theme so the first render is already correct, rather than flashing the default
    and then correcting itself.
    """

    user_id: int = Field(description="The account id.")
    email: str = Field(description="Sign-in address.")
    full_name: str = Field(description="Display name.")
    role: str = Field(description="One of: student, teacher, admin, superadmin.")
    student_id: str | None = Field(
        default=None,
        description="The linked student record, if this account has one. Only set for students.",
    )
    locale: str = Field(description="Resolved language, after the organisation fallback.")
    theme: str = Field(description="Resolved colour scheme: light, dark or system.")


class PasswordChangeRequest(BaseModel):
    """A password change.

    The current password is required even though the caller is already signed in: an
    unattended browser should not be enough to take an account over permanently.
    """

    current_password: str = Field(min_length=1, description="The existing password.")
    new_password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        description=(
            f"The replacement, at least {MIN_PASSWORD_LENGTH} characters. Length is the "
            "only rule: composition requirements measurably push people towards "
            "Password1! and a sticky note."
        ),
    )


class PreferencesRequest(BaseModel):
    """A change to the caller's own display preferences."""

    locale: str | None = Field(
        default=None,
        description="Language tag, or null to follow the organisation default.",
        examples=["de"],
    )
    theme: str | None = Field(
        default=None,
        description="light, dark, system, or null to follow the organisation default.",
        examples=["dark"],
    )
    full_name: str | None = Field(default=None, min_length=1, description="Display name.")


class SessionResponse(BaseModel):
    """One live session, for the profile page's device list."""

    token_sha256: str = Field(
        description=(
            "Identifies the session for revocation. This is a hash — the session "
            "token itself cannot be recovered from it."
        )
    )
    created_at: str = Field(description="When the session began, ISO-8601 UTC.")
    last_seen_at: str | None = Field(default=None, description="Last request on this session.")
    user_agent: str = Field(description="Client user agent, for labelling the device.")
    ip_address: str = Field(description="Client address at sign-in.")
    is_current: bool = Field(description="Whether this is the session making the request.")


class MessageResponse(BaseModel):
    """A bare acknowledgement.

    Carries a machine code rather than a sentence, for the same reason errors do:
    the frontend owns the wording.
    """

    code: str = Field(description="Machine-readable outcome, e.g. SIGNED_OUT.")
    count: int | None = Field(default=None, description="Affected rows, where relevant.")
