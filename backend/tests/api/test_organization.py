"""Superadmin organisation branding and grading configuration."""

from __future__ import annotations

import base64
import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notenverwaltung.grading_scale import DEFAULT_SCALE
from services import audit
from services.organization import load_grading_scale

BRANDING = {
    "name": "Ada Academy",
    "short_name": "ADA",
    "color_primary_light": "#123456",
    "color_primary_dark": "#abcdef",
    "color_accent_light": "#654321",
    "color_accent_dark": "#fedcba",
    "color_background_light": "#f0eee6",
    "color_background_dark": "#101014",
    "enabled_locales": ["en", "de"],
    "default_locale": "de",
    "default_theme": "dark",
    "timezone": "Europe/Berlin",
}

SCALE = [
    {"min_percentage": 90, "label": "A"},
    {"min_percentage": 80, "label": "B"},
    {"min_percentage": 70, "label": "C"},
    {"min_percentage": 60, "label": "D"},
    {"min_percentage": 0, "label": "F"},
]

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_an_admin_cannot_change_organization(as_admin: TestClient) -> None:
    """Every organisation write is reserved for a superadmin."""
    assert as_admin.patch("/org/branding", json=BRANDING).status_code == 403
    assert as_admin.put("/org/grading-scale", json=SCALE).status_code == 403
    assert (
        as_admin.post(
            "/org/assets/logo",
            files={"file": ("logo.png", b"png", "image/png")},
        ).status_code
        == 403
    )
    assert as_admin.delete("/org/assets/logo").status_code == 403


def test_a_superadmin_can_change_branding(as_superadmin: TestClient) -> None:
    """A branding patch is merged with untouched organisation fields."""
    response = as_superadmin.patch("/org/branding", json=BRANDING)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Ada Academy"
    assert body["colors"]["primary"] == {"light": "#123456", "dark": "#abcdef"}
    # The page backdrop, which the frontend injects as `--bg`. An institution whose
    # identity is a warm off-white could restyle every button and still sit on the
    # product's own background before this existed.
    assert body["colors"]["background"] == {"light": "#f0eee6", "dark": "#101014"}
    assert body["enabled_locales"] == ["en", "de"]
    # The shipped A-F scale is priced 4-3-2-1-0 by migration 010, and a branding
    # patch leaves the scale alone.
    assert [(b["label"], b["points"]) for b in body["grading_scale"]] == [
        ("A", 4.0),
        ("B", 3.0),
        ("C", 2.0),
        ("D", 1.0),
        ("F", 0.0),
    ]


def test_a_superadmin_can_replace_the_grading_scale(as_superadmin: TestClient) -> None:
    """The grading-scale endpoint replaces the complete band list."""
    scale = [
        {"min_percentage": 85, "label": "excellent"},
        {"min_percentage": 50, "label": "pass"},
        {"min_percentage": 0, "label": "retry"},
    ]

    response = as_superadmin.put("/org/grading-scale", json=scale)

    assert response.status_code == 200, response.text
    # Points come back null: a scale sent without them has not been priced, and
    # inventing a number would be inventing a GPA. Every scale stored before grade
    # points existed reads back exactly this way.
    assert response.json()["grading_scale"] == [{**band, "points": None} for band in scale]


def test_a_superadmin_can_price_the_grading_scale(as_superadmin: TestClient) -> None:
    """Points are what turn a scale into something a GPA can average."""
    scale = [
        {"min_percentage": 92, "label": "1", "points": 1.0},
        {"min_percentage": 50, "label": "4", "points": 4.0},
        {"min_percentage": 0, "label": "6", "points": 6.0},
    ]

    response = as_superadmin.put("/org/grading-scale", json=scale)

    assert response.status_code == 200, response.text
    # A German scale awards its lowest number to its highest threshold. Nothing may
    # reject or reorder that -- points carry no relationship to the percentage.
    assert response.json()["grading_scale"] == scale


def test_grade_points_cannot_be_negative(as_superadmin: TestClient) -> None:
    scale = [{"min_percentage": 0, "label": "F", "points": -1}]

    assert as_superadmin.put("/org/grading-scale", json=scale).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"name": None},
        {"color_primary_light": "blue"},
        {"color_background_light": "eggshell"},
        {"enabled_locales": ["en", "es"]},
        {"enabled_locales": ["de"], "default_locale": "en"},
    ],
)
def test_invalid_branding_returns_a_validation_code(
    as_superadmin: TestClient, changes: dict[str, object]
) -> None:
    """Domain validation failures keep the stable RFC-9457 code."""
    response = as_superadmin.patch("/org/branding", json=changes)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "scale",
    [
        [{"min_percentage": 50, "label": "pass"}],
        [
            {"min_percentage": 90, "label": "A"},
            {"min_percentage": -1, "label": "F"},
        ],
        [
            {"min_percentage": 90, "label": "A"},
            {"min_percentage": 90, "label": "A-"},
            {"min_percentage": 0, "label": "F"},
        ],
        [
            {"min_percentage": 101, "label": "A"},
            {"min_percentage": 0, "label": "F"},
        ],
        [
            {"min_percentage": 90, "label": "   "},
            {"min_percentage": 0, "label": "F"},
        ],
    ],
)
def test_invalid_grading_scales_return_a_validation_code(
    as_superadmin: TestClient, scale: list[dict[str, object]]
) -> None:
    """Uncovered and duplicate thresholds are rejected before storage."""
    response = as_superadmin.put("/org/grading-scale", json=scale)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_a_non_finite_grading_threshold_is_rejected(as_superadmin: TestClient) -> None:
    """A non-finite threshold cannot be committed and then fail response encoding."""
    response = as_superadmin.put(
        "/org/grading-scale",
        content='[{"min_percentage":1e400,"label":"A"},{"min_percentage":0,"label":"F"}]',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_an_oversized_asset_is_rejected(as_superadmin: TestClient) -> None:
    """The configured two-mebibyte ceiling is enforced."""
    response = as_superadmin.post(
        "/org/assets/logo",
        files={"file": ("logo.png", b"x" * (2 * 1024 * 1024 + 1), "image/png")},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_a_non_image_asset_is_rejected(as_superadmin: TestClient) -> None:
    """An allowed filename cannot disguise executable markup."""
    response = as_superadmin.post(
        "/org/assets/logo",
        files={"file": ("logo.png", b"<script>alert(1)</script>", "text/html")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_an_image_content_type_cannot_disguise_markup(as_superadmin: TestClient) -> None:
    """The body must match the claimed image media type."""
    response = as_superadmin.post(
        "/org/assets/logo",
        files={"file": ("logo.png", b"<svg onload=alert(1)>", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_asset_paths_come_from_content_type_and_delete_restores_the_wordmark(
    as_superadmin: TestClient,
) -> None:
    """Client filenames are ignored and deleting the logo clears its path."""
    uploaded = as_superadmin.post(
        "/org/assets/logo",
        files={"file": ("../../evil.svg", PNG, "image/png")},
    )

    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["logo_path"] == "/uploads/logo.png"

    removed = as_superadmin.delete("/org/assets/logo")

    assert removed.status_code == 200, removed.text
    assert removed.json()["logo_path"] is None


def test_every_successful_change_is_audited(
    as_superadmin: TestClient, seeded_db: sqlite3.Connection
) -> None:
    """Branding, scale, upload and removal each leave one attributable row."""
    assert as_superadmin.patch("/org/branding", json={"short_name": "AC"}).status_code == 200
    assert as_superadmin.put("/org/grading-scale", json=SCALE).status_code == 200
    assert (
        as_superadmin.post(
            "/org/assets/favicon",
            files={"file": ("anything.png", PNG, "image/png")},
        ).status_code
        == 200
    )
    assert as_superadmin.delete("/org/assets/favicon").status_code == 200

    rows = seeded_db.execute(
        "SELECT action FROM audit_log WHERE entity = 'organization' ORDER BY id"
    ).fetchall()
    assert [row["action"] for row in rows] == ["update", "update", "update", "update"]


def test_a_failed_replacement_preserves_the_active_asset(
    as_superadmin: TestClient,
    db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database failure cannot destroy a same-extension active file."""
    assert (
        as_superadmin.post(
            "/org/assets/logo",
            files={"file": ("logo.png", PNG, "image/png")},
        ).status_code
        == 200
    )

    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(audit, "record", fail_audit)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        as_superadmin.post(
            "/org/assets/logo",
            files={"file": ("logo.png", PNG + b"replacement", "image/png")},
        )

    assert (db_path.parent / "uploads" / "logo.png").read_bytes() == PNG


@pytest.mark.parametrize(
    "stored_scale",
    [
        '[{"min_percentage": 50, "label": "pass"}]',
        '[{"min_percentage": 0, "label": null}]',
    ],
)
def test_a_malformed_stored_scale_logs_and_uses_the_default(
    seeded_db: sqlite3.Connection,
    caplog: pytest.LogCaptureFixture,
    stored_scale: str,
) -> None:
    """Malformed stored grading bands use the documented scale fallback."""
    seeded_db.execute(
        "UPDATE organization SET grading_scale_json = ? WHERE id = 1",
        (stored_scale,),
    )

    with caplog.at_level(logging.WARNING):
        scale = load_grading_scale(seeded_db)

    assert scale == DEFAULT_SCALE
    assert "Invalid stored grading scale" in caplog.text
