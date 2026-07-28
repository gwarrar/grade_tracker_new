"""Per-organisation UI string overrides."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from pydantic import BaseModel, Field

from api.deps import AdminUser, CurrentUser, DbConn
from notenverwaltung.storage import transaction
from services.localization import MAX_VALUE_LENGTH, LocalizationService

router = APIRouter(prefix="/org/i18n", tags=["Localization"])

LocalePath = Annotated[
    str, Path(description="Language tag.", examples=["de"], pattern="^[a-z]{2}$")
]


class OverrideRequest(BaseModel):
    """A replacement for one shipped string."""

    value: str = Field(
        min_length=1,
        max_length=MAX_VALUE_LENGTH,
        description="The replacement text. Delete the override to restore the shipped value.",
        examples=["Auszubildende"],
    )


class OverrideResponse(BaseModel):
    """A stored override."""

    locale: str
    key: str = Field(description="Dotted message key.", examples=["nav.students"])
    value: str


def service(conn: DbConn) -> LocalizationService:
    """Build the localization service for this request.

    Args:
        conn: The request's connection.

    Returns:
        The service.
    """
    return LocalizationService(conn)


Localization = Annotated[LocalizationService, Depends(service)]


@router.get(
    "/{locale}",
    response_model=dict[str, str],
    summary="Overrides for one locale",
    description=(
        "**Public** — the sign-in page needs its labels before anyone has signed in.\n\n"
        "Returns only the keys this organisation has overridden, usually none. The "
        "client merges them over its shipped translations, so a rename takes effect "
        "without a rebuild.\n\n"
        "The backend ships no message catalogue: the frontend owns every string, and "
        "this endpoint exists solely for the per-organisation overrides it cannot know "
        "about at build time."
    ),
    responses={422: {"description": "`VALIDATION_ERROR` — no translation ships for that locale."}},
)
def get_overrides(locale: LocalePath, svc: Localization) -> dict[str, str]:
    """Return every override for a locale."""
    return svc.overrides(locale)


@router.get(
    "",
    response_model=dict[str, dict[str, str]],
    summary="Overrides for every locale",
    description="Administrators only. Powers the localization editor's grid.",
)
def get_all_overrides(svc: Localization, _: AdminUser) -> dict[str, dict[str, str]]:
    """Return overrides for every supported locale."""
    return svc.all_overrides()


@router.put(
    "/{locale}/{key}",
    response_model=OverrideResponse,
    summary="Override one string",
    description=(
        "Creates or replaces an override. Keys are dotted lower-case paths so the "
        "override table stays a namespace rather than accumulating typos that look "
        "like real keys and never match anything."
    ),
    responses={
        403: {"description": "`FORBIDDEN` — administrators only."},
        422: {"description": "`VALIDATION_ERROR` — bad locale, malformed key, or empty value."},
    },
)
def set_override(
    locale: LocalePath,
    key: Annotated[str, Path(description="Dotted message key.", examples=["nav.students"])],
    payload: OverrideRequest,
    svc: Localization,
    principal: CurrentUser,
    conn: DbConn,
) -> OverrideResponse:
    """Create or replace one override."""
    with transaction(conn):
        stored = svc.set_override(principal, locale, key, payload.value)
    return OverrideResponse(**stored)


@router.delete(
    "/{locale}/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Restore the shipped string",
    description="Removes the override so the client falls back to its own translation.",
    responses={
        403: {"description": "`FORBIDDEN` — administrators only."},
        404: {"description": "`OVERRIDE_NOT_FOUND` — nothing overridden at that key."},
    },
)
def delete_override(
    locale: LocalePath,
    key: str,
    svc: Localization,
    principal: CurrentUser,
    conn: DbConn,
) -> None:
    """Remove an override."""
    with transaction(conn):
        svc.delete_override(principal, locale, key)
