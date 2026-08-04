"""User, Enrollment and Organization models."""

from __future__ import annotations

import sqlite3

import pytest

from notenverwaltung.exceptions import ValidationError
from notenverwaltung.grading_scale import DEFAULT_SCALE
from notenverwaltung.models import (
    BrandColor,
    Enrollment,
    EnrollmentStatus,
    Organization,
    Role,
    Theme,
    User,
)


class TestRole:
    def test_hierarchy_is_ordered(self) -> None:
        assert Role.SUPERADMIN.outranks(Role.ADMIN)
        assert Role.ADMIN.outranks(Role.TEACHER)
        assert Role.TEACHER.outranks(Role.STUDENT)
        assert not Role.STUDENT.outranks(Role.TEACHER)

    def test_can_act_as_is_inclusive(self) -> None:
        """A role satisfies its own requirement; outranks() alone would say otherwise."""
        assert Role.TEACHER.can_act_as(Role.TEACHER)
        assert Role.ADMIN.can_act_as(Role.TEACHER)
        assert not Role.STUDENT.can_act_as(Role.TEACHER)

    def test_serialises_as_a_readable_string(self) -> None:
        """Stored as 'teacher', not 1 -- a row read by hand stays interpretable."""
        assert str(Role.TEACHER) == "teacher"


class TestUser:
    def test_email_is_normalised(self) -> None:
        assert User(" Anna@School.DE ", "Anna", Role.TEACHER).email == "anna@school.de"

    @pytest.mark.parametrize("email", ["no-at", "no@dot", "a b@c.de", ""])
    def test_invalid_email_is_rejected(self, email: str) -> None:
        with pytest.raises(ValidationError):
            User(email, "Anna", Role.TEACHER)

    def test_blank_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            User("a@b.co", "   ", Role.TEACHER)

    def test_to_dict_never_emits_credentials(self) -> None:
        """A serialiser that cannot emit a hash cannot leak one through a new
        endpoint, a log line, or a debug dump."""
        user = User("a@b.co", "Anna", Role.ADMIN, password_hash="deadbeef", password_salt="cafe")
        payload = user.to_dict()
        assert "password_hash" not in payload
        assert "password_salt" not in payload
        assert "deadbeef" not in str(payload)

    def test_is_staff_covers_teacher_and_above(self) -> None:
        assert User("a@b.co", "T", Role.TEACHER).is_staff
        assert User("a@b.co", "A", Role.ADMIN).is_staff
        assert not User("a@b.co", "S", Role.STUDENT).is_staff

    def test_from_row_coerces_database_strings(self) -> None:
        row = {
            "id": 1,
            "email": "a@b.co",
            "full_name": "Anna",
            "role": "teacher",
            "password_hash": "x",
            "password_salt": "y",
            "avatar_path": None,
            "locale": "de",
            "theme_preference": "dark",
            "is_active": 1,
            "created_at": None,
        }
        user = User.from_row(row)
        assert user.role is Role.TEACHER
        assert user.theme_preference is Theme.DARK
        assert user.is_active is True

    def test_from_row_rejects_an_unknown_role(self) -> None:
        row = {
            "id": 1,
            "email": "a@b.co",
            "full_name": "A",
            "role": "wizard",
            "password_hash": "",
            "password_salt": "",
            "avatar_path": None,
            "locale": None,
            "theme_preference": None,
            "is_active": 1,
            "created_at": None,
        }
        with pytest.raises(ValidationError):
            User.from_row(row)


class TestEnrollment:
    def test_defaults_to_active(self) -> None:
        assert Enrollment("S001", "CS101").is_active

    def test_withdrawn_is_not_active(self) -> None:
        """Withdrawal is recorded, not deleted -- grades earned before it must stay attached."""
        assert not Enrollment("S001", "CS101", EnrollmentStatus.WITHDRAWN).is_active

    @pytest.mark.parametrize(("sid", "cid"), [("", "CS101"), ("S001", ""), ("  ", "CS101")])
    def test_blank_identifiers_are_rejected(self, sid: str, cid: str) -> None:
        with pytest.raises(ValidationError):
            Enrollment(sid, cid)

    def test_from_row_rejects_an_unknown_status(self) -> None:
        row = {
            "student_id": "S001",
            "course_id": "CS101",
            "status": "abducted",
            "enrolled_at": None,
            "enrolled_by": None,
        }
        with pytest.raises(ValidationError):
            Enrollment.from_row(row)


class TestBrandColor:
    @pytest.mark.parametrize("value", ["#fff", "#FFFFFF", "#2e5bff"])
    def test_accepts_hex(self, value: str) -> None:
        assert BrandColor(value, value)

    @pytest.mark.parametrize("value", ["fff", "#ff", "#gggggg", "rgb(0,0,0)", "blue", ""])
    def test_rejects_everything_else(self, value: str) -> None:
        with pytest.raises(ValidationError):
            BrandColor(value, "#fff")

    def test_carries_a_variant_per_theme(self) -> None:
        """One hex cannot serve both modes: legible on white is often illegible on black."""
        colour = BrandColor("#2E5BFF", "#7C9BFF")
        assert colour.light != colour.dark


class TestOrganization:
    def test_defaults_are_usable(self) -> None:
        org = Organization("Test School")
        assert org.default_locale == "en"
        assert org.default_theme is Theme.SYSTEM
        assert org.grading_scale == DEFAULT_SCALE

    def test_blank_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Organization("  ")

    def test_default_locale_must_be_enabled(self) -> None:
        """Otherwise a user with no preference lands in a language the switcher does
        not offer, and cannot get back."""
        with pytest.raises(ValidationError) as exc:
            Organization("Test", default_locale="de", enabled_locales=("en", "fr"))
        assert exc.value.context["field"] == "default_locale"

    def test_unshipped_locale_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            Organization("Test", enabled_locales=("en", "ja"))
        assert exc.value.context["value"] == "ja"

    def test_empty_locale_list_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Organization("Test", enabled_locales=())

    def test_to_dict_shape_matches_the_branding_endpoint(self) -> None:
        payload = Organization("Test School").to_dict()
        assert payload["colors"]["primary"]["light"].startswith("#")
        assert payload["colors"]["primary"]["dark"].startswith("#")
        assert payload["enabled_locales"] == ["en", "de", "fr"]
        assert isinstance(payload["grading_scale"], list)

    def test_from_row_round_trips_the_seeded_defaults(
        self, sqlite_conn: sqlite3.Connection
    ) -> None:
        row = sqlite_conn.execute("SELECT * FROM organization WHERE id = 1").fetchone()
        org = Organization.from_row(row)
        assert org.name == "Grade Tracker"
        assert org.grading_scale == DEFAULT_SCALE
        assert org.enabled_locales == ("en", "de", "fr")

    def test_from_row_wraps_an_invalid_theme_as_validation_error(
        self, sqlite_conn: sqlite3.Connection
    ) -> None:
        row = dict(sqlite_conn.execute("SELECT * FROM organization WHERE id = 1").fetchone())
        row["default_theme"] = "broken"

        with pytest.raises(ValidationError):
            Organization.from_row(row)
