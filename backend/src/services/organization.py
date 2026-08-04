"""Read and update the organisation's configuration."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, cast

from notenverwaltung.exceptions import PayloadTooLargeError, ValidationError
from notenverwaltung.grading_scale import DEFAULT_SCALE, GradingScale
from notenverwaltung.models import BrandColor, Organization, Theme
from notenverwaltung.storage import transaction
from services import audit
from services.scoping import Principal
from services.security import utc_now

logger = logging.getLogger(__name__)

AssetKind = Literal["logo", "favicon"]

_CONTENT_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
}


def _matches_content_type(content: bytes, content_type: str) -> bool:
    """Return whether an upload has the claimed image signature."""
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    if content_type == "image/x-icon":
        return content.startswith(b"\x00\x00\x01\x00")
    return False


def load_organization(conn: sqlite3.Connection) -> Organization:
    """Read the organisation configuration.

    Args:
        conn: The connection to query.

    Returns:
        The organisation, or defaults if the row is somehow missing.
    """
    row = conn.execute("SELECT * FROM organization WHERE id = 1").fetchone()
    return Organization.from_row(row) if row else Organization(name="Grade Tracker")


def load_grading_scale(conn: sqlite3.Connection) -> GradingScale:
    """Read the organisation's grading scale.

    Args:
        conn: The connection to query.

    Returns:
        The configured scale, or the specification default.
    """
    try:
        return load_organization(conn).grading_scale
    except ValidationError as error:
        logger.warning("Invalid stored grading scale; using the default: %s", error)
        return DEFAULT_SCALE


def update(
    conn: sqlite3.Connection,
    principal: Principal,
    changes: Mapping[str, object],
) -> Organization:
    """Merge validated organisation changes, persist them and audit the write.

    Args:
        conn: The request's database connection.
        principal: The superadmin making the change.
        changes: Domain field names and replacement values.

    Returns:
        The stored organisation.

    Raises:
        ValidationError: If a field is unknown or a domain invariant fails.
    """
    with transaction(conn):
        return _update_in_transaction(conn, principal, changes)


def _update_in_transaction(
    conn: sqlite3.Connection,
    principal: Principal,
    changes: Mapping[str, object],
) -> Organization:
    """Apply and audit an organisation update inside the caller's transaction."""
    before = load_organization(conn)
    merged: dict[str, object] = {
        "name": before.name,
        "short_name": before.short_name,
        "logo_path": before.logo_path,
        "favicon_path": before.favicon_path,
        "color_primary_light": before.primary.light,
        "color_primary_dark": before.primary.dark,
        "color_accent_light": before.accent.light,
        "color_accent_dark": before.accent.dark,
        "enabled_locales": before.enabled_locales,
        "default_locale": before.default_locale,
        "default_theme": before.default_theme,
        "timezone": before.timezone,
        "grading_scale": before.grading_scale,
    }
    for field, value in changes.items():
        if field not in merged:
            raise ValidationError("Unknown organisation field.", field=field)
        merged[field] = value

    scale_value = merged["grading_scale"]
    scale = (
        scale_value
        if isinstance(scale_value, GradingScale)
        else GradingScale.from_list(cast(list[dict[str, object]], scale_value))
    )
    theme_value = merged["default_theme"]
    try:
        theme = theme_value if isinstance(theme_value, Theme) else Theme(str(theme_value))
    except ValueError as error:
        raise ValidationError(
            "Unrecognised default theme.", field="default_theme", value=theme_value
        ) from error

    after = Organization(
        name=cast(str, merged["name"]),
        short_name=cast(str, merged["short_name"]),
        logo_path=cast(str | None, merged["logo_path"]),
        favicon_path=cast(str | None, merged["favicon_path"]),
        primary=BrandColor(
            cast(str, merged["color_primary_light"]),
            cast(str, merged["color_primary_dark"]),
        ),
        accent=BrandColor(
            cast(str, merged["color_accent_light"]),
            cast(str, merged["color_accent_dark"]),
        ),
        enabled_locales=tuple(cast(list[str] | tuple[str, ...], merged["enabled_locales"])),
        default_locale=cast(str, merged["default_locale"]),
        default_theme=theme,
        timezone=cast(str, merged["timezone"]),
        grading_scale=scale,
        updated_at=utc_now(),
    )

    conn.execute(
        "UPDATE organization SET name = ?, short_name = ?, logo_path = ?, favicon_path = ?,"
        " color_primary_light = ?, color_primary_dark = ?, color_accent_light = ?,"
        " color_accent_dark = ?, default_locale = ?, enabled_locales_json = ?,"
        " default_theme = ?, timezone = ?, grading_scale_json = ?, updated_at = ?"
        " WHERE id = 1",
        (
            after.name,
            after.short_name,
            after.logo_path,
            after.favicon_path,
            after.primary.light,
            after.primary.dark,
            after.accent.light,
            after.accent.dark,
            after.default_locale,
            json.dumps(after.enabled_locales),
            str(after.default_theme),
            after.timezone,
            json.dumps(after.grading_scale.to_list()),
            after.updated_at,
        ),
    )
    audit.record(
        conn,
        actor_user_id=principal.user_id,
        entity="organization",
        entity_id="1",
        action="update",
        before=before.to_dict(),
        after=after.to_dict(),
    )
    return after


def upload_asset(
    conn: sqlite3.Connection,
    principal: Principal,
    kind: AssetKind,
    content: bytes,
    content_type: str,
    upload_path: Path,
    max_upload_bytes: int,
) -> Organization:
    """Validate, store and activate one organisation image.

    Args:
        conn: The request's database connection.
        principal: The superadmin making the change.
        kind: Logo or favicon.
        content: Uploaded bytes.
        content_type: Validated media type candidate.
        upload_path: Directory supplied by the API configuration.
        max_upload_bytes: Configured size ceiling.

    Returns:
        The updated organisation.

    Raises:
        PayloadTooLargeError: If the upload exceeds the configured ceiling.
        ValidationError: If the media type is not supported.
    """
    if len(content) > max_upload_bytes:
        raise PayloadTooLargeError(
            "Uploaded asset exceeds the configured size limit.", limit=max_upload_bytes
        )

    # SVG is intentionally absent: serving active SVG from our own origin turns a
    # logo upload into stored XSS, and branding does not need executable vectors.
    extension = _CONTENT_EXTENSIONS.get(content_type)
    if extension is None:
        raise ValidationError(
            "Unsupported organisation asset type.",
            field="content_type",
            value=content_type,
            supported=sorted(_CONTENT_EXTENSIONS),
        )
    if not _matches_content_type(content, content_type):
        raise ValidationError(
            "Uploaded bytes do not match the declared image type.",
            field="file",
            value=content_type,
        )

    upload_path.mkdir(parents=True, exist_ok=True)
    destination = upload_path / f"{kind}{extension}"
    with TemporaryDirectory(prefix=f".{kind}-", dir=upload_path) as staging_dir:
        staged = Path(staging_dir) / destination.name
        staged.write_bytes(content)
        backups: list[tuple[Path, Path]] = []
        activated = False
        try:
            with transaction(conn):
                organization = _update_in_transaction(
                    conn,
                    principal,
                    {f"{kind}_path": f"/uploads/{destination.name}"},
                )
                backups = _back_up_asset_files(upload_path, kind, Path(staging_dir))
                staged.replace(destination)
                activated = True
        except Exception:
            if activated:
                destination.unlink(missing_ok=True)
            _restore_asset_files(backups)
            raise

    return organization


def remove_asset(
    conn: sqlite3.Connection,
    principal: Principal,
    kind: AssetKind,
    upload_path: Path,
) -> Organization:
    """Clear one organisation image and remove its fixed files.

    Args:
        conn: The request's database connection.
        principal: The superadmin making the change.
        kind: Logo or favicon.
        upload_path: Directory supplied by the API configuration.

    Returns:
        The updated organisation, configured to use its wordmark.
    """
    upload_path.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f".{kind}-", dir=upload_path) as staging_dir:
        backups: list[tuple[Path, Path]] = []
        try:
            with transaction(conn):
                organization = _update_in_transaction(conn, principal, {f"{kind}_path": None})
                backups = _back_up_asset_files(upload_path, kind, Path(staging_dir))
        except Exception:
            _restore_asset_files(backups)
            raise
    return organization


def _back_up_asset_files(
    upload_path: Path,
    kind: AssetKind,
    staging_path: Path,
) -> list[tuple[Path, Path]]:
    """Move every fixed variant aside so the caller can commit or restore it.

    Args:
        upload_path: Directory containing organisation assets.
        kind: Logo or favicon.
        staging_path: Same-filesystem temporary directory.

    Returns:
        Original and backup path pairs.
    """
    backups: list[tuple[Path, Path]] = []
    try:
        for extension in _CONTENT_EXTENSIONS.values():
            original = upload_path / f"{kind}{extension}"
            if original.exists():
                backup = staging_path / f"{original.name}.backup"
                original.replace(backup)
                backups.append((original, backup))
    except Exception:
        _restore_asset_files(backups)
        raise
    return backups


def _restore_asset_files(backups: list[tuple[Path, Path]]) -> None:
    """Restore asset files moved aside by a failed transaction."""
    for original, backup in backups:
        backup.replace(original)
