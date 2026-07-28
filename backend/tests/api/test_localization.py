"""Per-organisation string overrides."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestReadingOverrides:
    def test_is_public(self, client: TestClient) -> None:
        """The sign-in page needs its labels before anyone has signed in."""
        response = client.get("/org/i18n/de")
        assert response.status_code == 200
        assert response.json() == {}

    def test_an_unsupported_locale_is_rejected(self, client: TestClient) -> None:
        response = client.get("/org/i18n/ja")
        assert response.status_code == 422
        assert "en" in response.json()["context"]["supported"]

    def test_returns_only_what_is_overridden(self, as_admin: TestClient) -> None:
        """Usually nothing — the client then uses its shipped translations unchanged."""
        as_admin.put("/org/i18n/de/nav.students", json={"value": "Auszubildende"})
        assert as_admin.get("/org/i18n/de").json() == {"nav.students": "Auszubildende"}
        assert as_admin.get("/org/i18n/fr").json() == {}

    def test_the_grid_covers_every_shipped_locale(self, as_admin: TestClient) -> None:
        """Including empty ones, so the editor renders a complete grid rather than
        inferring absence."""
        assert set(as_admin.get("/org/i18n").json()) == {"en", "de", "fr"}

    def test_the_grid_is_admin_only(self, as_teacher: TestClient) -> None:
        assert as_teacher.get("/org/i18n").status_code == 403


class TestWritingOverrides:
    def test_admin_can_rename_a_label(self, as_admin: TestClient) -> None:
        """The real need: institutions rename Student to Trainee or Auszubildende."""
        response = as_admin.put("/org/i18n/de/nav.students", json={"value": "Auszubildende"})
        assert response.status_code == 200
        assert response.json()["value"] == "Auszubildende"

    def test_setting_twice_replaces(self, as_admin: TestClient) -> None:
        as_admin.put("/org/i18n/de/nav.students", json={"value": "First"})
        as_admin.put("/org/i18n/de/nav.students", json={"value": "Second"})
        assert as_admin.get("/org/i18n/de").json()["nav.students"] == "Second"

    def test_a_teacher_cannot_edit_translations(self, as_teacher: TestClient) -> None:
        response = as_teacher.put("/org/i18n/de/nav.students", json={"value": "Nope"})
        assert response.status_code == 403

    def test_an_unauthenticated_caller_cannot_edit(self, client: TestClient) -> None:
        assert client.put("/org/i18n/de/nav.students", json={"value": "Nope"}).status_code == 401

    def test_a_malformed_key_is_rejected(self, as_admin: TestClient) -> None:
        """Otherwise the table accumulates typos that look like real keys and never
        match anything."""
        # An empty key collapses the URL to /org/i18n/de/, which has no PUT — 405 is
        # correct routing rather than a validation gap.
        for key in ["Nav.Students", "nav students", "nav..students", "1nav"]:
            response = as_admin.put(f"/org/i18n/de/{key}", json={"value": "x"})
            assert response.status_code == 422, key
        assert as_admin.put("/org/i18n/de/", json={"value": "x"}).status_code in (404, 405)

    def test_an_empty_value_is_rejected(self, as_admin: TestClient) -> None:
        """A blank override renders as a blank label and reads as a broken page.
        Deleting is the explicit way to restore the shipped text."""
        assert as_admin.put("/org/i18n/de/nav.students", json={"value": "   "}).status_code == 422

    def test_an_overlong_value_is_rejected(self, as_admin: TestClient) -> None:
        assert (
            as_admin.put("/org/i18n/de/nav.students", json={"value": "x" * 600}).status_code == 422
        )


class TestDeletingOverrides:
    def test_delete_restores_the_shipped_text(self, as_admin: TestClient) -> None:
        as_admin.put("/org/i18n/de/nav.students", json={"value": "Auszubildende"})
        assert as_admin.delete("/org/i18n/de/nav.students").status_code == 204
        assert as_admin.get("/org/i18n/de").json() == {}

    def test_deleting_a_missing_override_is_not_found(self, as_admin: TestClient) -> None:
        response = as_admin.delete("/org/i18n/de/nav.nothing")
        assert response.status_code == 404
        assert response.json()["code"] == "OVERRIDE_NOT_FOUND"

    def test_a_teacher_cannot_delete(self, as_admin: TestClient, as_teacher: TestClient) -> None:
        as_admin.put("/org/i18n/de/nav.students", json={"value": "Auszubildende"})
        assert as_teacher.delete("/org/i18n/de/nav.students").status_code == 403


class TestAuditTrail:
    def test_every_change_is_recorded(self, as_admin: TestClient, seeded_db: object) -> None:
        """Someone will eventually ask why a label changed."""
        as_admin.put("/org/i18n/de/nav.students", json={"value": "Auszubildende"})
        as_admin.put("/org/i18n/de/nav.students", json={"value": "Lernende"})
        as_admin.delete("/org/i18n/de/nav.students")

        rows = seeded_db.execute(  # type: ignore[attr-defined]
            "SELECT action FROM audit_log WHERE entity = 'i18n_override' ORDER BY id"
        ).fetchall()
        assert [r["action"] for r in rows] == ["create", "update", "delete"]
