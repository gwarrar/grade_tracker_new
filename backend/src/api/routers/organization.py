"""Superadmin writes for organisation branding and grading policy."""

from __future__ import annotations

from typing import Annotated, Self

from fastapi import APIRouter, Depends, File, Path, UploadFile
from pydantic import BaseModel, model_validator

from api.config import Settings, get_settings
from api.deps import DbConn, SuperAdminUser
from notenverwaltung.models import Organization, Theme
from services.organization import AssetKind, remove_asset, update, upload_asset

router = APIRouter(prefix="/org", tags=["Organisation"])


class BrandColors(BaseModel):
    """Brand colours for both display modes."""

    light: str
    dark: str


class OrganizationColors(BaseModel):
    """Primary and accent colour pairs."""

    primary: BrandColors
    accent: BrandColors


class GradeBandResponse(BaseModel):
    """One configured grading band."""

    min_percentage: float
    label: str


class OrganizationResponse(BaseModel):
    """The public organisation configuration after a write."""

    name: str
    short_name: str
    logo_path: str | None
    favicon_path: str | None
    colors: OrganizationColors
    default_locale: str
    enabled_locales: list[str]
    default_theme: Theme
    timezone: str
    grading_scale: list[GradeBandResponse]
    updated_at: str | None


class BrandingPatch(BaseModel):
    """Brand, locale and display settings to change."""

    name: str | None = None
    short_name: str | None = None
    color_primary_light: str | None = None
    color_primary_dark: str | None = None
    color_accent_light: str | None = None
    color_accent_dark: str | None = None
    enabled_locales: list[str] | None = None
    default_locale: str | None = None
    default_theme: Theme | None = None
    timezone: str | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> Self:
        """Reject null for fields whose omission already means unchanged."""
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Organisation fields cannot be null.")
        return self


class GradeBandRequest(BaseModel):
    """One replacement grading band."""

    min_percentage: float
    label: str


SettingsDep = Annotated[Settings, Depends(get_settings)]
AssetKindPath = Annotated[
    AssetKind,
    Path(description="Asset to replace or clear.", examples=["logo"]),
]


@router.patch(
    "/branding",
    response_model=OrganizationResponse,
    summary="Change organisation branding",
    responses={
        403: {"description": "`FORBIDDEN` — superadmins only."},
        422: {"description": "`VALIDATION_ERROR` — invalid branding configuration."},
    },
)
def update_branding(
    body: BrandingPatch,
    principal: SuperAdminUser,
    conn: DbConn,
) -> OrganizationResponse:
    """Merge supplied branding fields into the organisation."""
    changes = body.model_dump(exclude_unset=True)
    return _response(update(conn, principal, changes))


@router.put(
    "/grading-scale",
    response_model=OrganizationResponse,
    summary="Replace the grading scale",
    responses={
        403: {"description": "`FORBIDDEN` — superadmins only."},
        422: {"description": "`VALIDATION_ERROR` — invalid grading scale."},
    },
)
def replace_grading_scale(
    body: list[GradeBandRequest],
    principal: SuperAdminUser,
    conn: DbConn,
) -> OrganizationResponse:
    """Replace all grading bands as one audited decision."""
    bands = [band.model_dump() for band in body]
    return _response(update(conn, principal, {"grading_scale": bands}))


@router.post(
    "/assets/{kind}",
    response_model=OrganizationResponse,
    summary="Upload an organisation asset",
    responses={
        403: {"description": "`FORBIDDEN` — superadmins only."},
        413: {"description": "`PAYLOAD_TOO_LARGE` — above the configured limit."},
        422: {"description": "`VALIDATION_ERROR` — unsupported image type."},
    },
)
async def replace_asset(
    kind: AssetKindPath,
    file: Annotated[UploadFile, File(description="PNG, JPEG, WebP or icon image.")],
    principal: SuperAdminUser,
    conn: DbConn,
    settings: SettingsDep,
) -> OrganizationResponse:
    """Validate and store a logo or favicon under a fixed name."""
    content = await file.read(settings.max_upload_bytes + 1)
    organization = upload_asset(
        conn,
        principal,
        kind,
        content,
        file.content_type or "",
        settings.upload_path,
        settings.max_upload_bytes,
    )
    return _response(organization)


@router.delete(
    "/assets/{kind}",
    response_model=OrganizationResponse,
    summary="Restore the organisation wordmark",
    responses={403: {"description": "`FORBIDDEN` — superadmins only."}},
)
def delete_asset(
    kind: AssetKindPath,
    principal: SuperAdminUser,
    conn: DbConn,
    settings: SettingsDep,
) -> OrganizationResponse:
    """Clear a logo or favicon and return the updated organisation."""
    return _response(remove_asset(conn, principal, kind, settings.upload_path))


def _response(organization: Organization) -> OrganizationResponse:
    """Convert the domain model to the documented wire shape."""
    return OrganizationResponse.model_validate(organization.to_dict())
