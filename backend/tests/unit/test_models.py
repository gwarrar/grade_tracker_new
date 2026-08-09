"""Model validation, properties and serialisation."""

from __future__ import annotations

from typing import Any

import pytest

from notenverwaltung.exceptions import ValidationError
from notenverwaltung.grading_scale import DEFAULT_SCALE, GradeBand, GradingScale
from notenverwaltung.models import Course, Grade, Student, normalise_date


class TestStudent:
    def test_full_name_and_str(self) -> None:
        s = Student("S001", "Anna", "Schmidt", "anna@example.com")
        assert s.full_name == "Anna Schmidt"
        assert "S001" in str(s)

    def test_fields_are_trimmed_and_email_lowercased(self) -> None:
        s = Student("  S001 ", " Anna ", " Schmidt ", "  Anna@Example.COM ")
        assert (s.student_id, s.first_name, s.last_name) == ("S001", "Anna", "Schmidt")
        assert s.email == "anna@example.com"

    @pytest.mark.parametrize(
        ("sid", "first", "last", "email"),
        [
            ("", "Anna", "Schmidt", "a@b.co"),
            ("   ", "Anna", "Schmidt", "a@b.co"),
            ("S1", "", "Schmidt", "a@b.co"),
            ("S1", "Anna", "", "a@b.co"),
            ("S1", "Anna", "Schmidt", "no-at-sign"),
            ("S1", "Anna", "Schmidt", "no@dot"),
            ("S1", "Anna", "Schmidt", "two@at@signs.com"),
            ("S1", "Anna", "Schmidt", "spaces in@mail.com"),
            ("S1", "Anna", "Schmidt", ""),
        ],
    )
    def test_invalid_input_is_rejected(self, sid: str, first: str, last: str, email: str) -> None:
        with pytest.raises(ValidationError):
            Student(sid, first, last, email)

    def test_dict_round_trip(self) -> None:
        s = Student("S001", "Anna", "Schmidt", "anna@example.com", user_id=7)
        assert Student.from_dict(s.to_dict()) == s

    def test_from_dict_reports_the_missing_field(self) -> None:
        with pytest.raises(ValidationError) as exc:
            Student.from_dict({"student_id": "S1", "first_name": "A", "last_name": "B"})
        assert exc.value.context["field"] == "email"


class TestCourse:
    def test_defaults_match_the_specification(self) -> None:
        c = Course("CS101", "Intro")
        assert (c.max_grade, c.passing_grade, c.max_students) == (100.0, 50.0, 30)

    @pytest.mark.parametrize(
        ("kwargs", "field"),
        [
            ({"max_grade": 0}, "max_grade"),
            ({"max_grade": -5}, "max_grade"),
            ({"passing_grade": 0}, "passing_grade"),
            ({"passing_grade": 101}, "passing_grade"),  # above max_grade
            ({"max_students": 0}, "max_students"),
            ({"credits": 0}, "credits"),
        ],
    )
    def test_invalid_bounds_are_rejected(self, kwargs: dict[str, Any], field: str) -> None:
        with pytest.raises(ValidationError) as exc:
            Course("CS101", "Intro", **kwargs)
        assert exc.value.context["field"] == field

    def test_passing_grade_may_equal_max_grade(self) -> None:
        assert Course("X", "All or nothing", max_grade=10, passing_grade=10).passing_grade == 10

    def test_dict_round_trip(self) -> None:
        c = Course("CS101", "Intro", 50.0, 25.0, 20, teacher_id=3, term="2026-SS", credits=2.5)
        assert Course.from_dict(c.to_dict()) == c

    def test_from_dict_accepts_coursework_era_payloads(self) -> None:
        """Files written by v1 have no teacher_id, term or credits."""
        c = Course.from_dict(
            {
                "course_id": "CS101",
                "name": "Intro",
                "max_grade": 100,
                "passing_grade": 50,
                "max_students": 30,
            }
        )
        assert (c.teacher_id, c.term, c.credits) == (None, None, 1.0)


class TestNormaliseDate:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-01-15", "2026-01-15"),  # ISO, as the specification asks for
            ("15-01-2026", "2026-01-15"),  # the coursework version's format
            ("15.01.2026", "2026-01-15"),  # German keyboard habit
            ("15/01/2026", "2026-01-15"),  # French keyboard habit
            ("  2026-01-15  ", "2026-01-15"),
        ],
    )
    def test_accepted_formats_normalise_to_iso(self, raw: str, expected: str) -> None:
        assert normalise_date(raw) == expected

    @pytest.mark.parametrize("raw", ["", "not-a-date", "2026-13-01", "2026-02-30", "01-2026"])
    def test_invalid_dates_are_rejected(self, raw: str) -> None:
        with pytest.raises(ValidationError):
            normalise_date(raw)


class TestGrade:
    @pytest.fixture
    def course(self) -> Course:
        return Course("CS101", "Intro", max_grade=100.0, passing_grade=50.0)

    @pytest.fixture
    def student(self) -> Student:
        return Student("S001", "Anna", "Schmidt", "anna@example.com")

    @pytest.mark.parametrize(
        ("score", "letter"),
        [
            (100, "A"),
            (90, "A"),
            (89.9, "B"),
            (80, "B"),
            (79.9, "C"),
            (70, "C"),
            (69.9, "D"),
            (60, "D"),
            (59.9, "F"),
            (0, "F"),
        ],
    )
    def test_letter_grade_boundaries(
        self, student: Student, course: Course, score: float, letter: str
    ) -> None:
        assert Grade(student, course, score, "2026-01-15").letter_grade == letter

    def test_percentage_is_relative_to_the_course_maximum(self, student: Student) -> None:
        small = Course("CS102", "Small", max_grade=20.0, passing_grade=10.0)
        assert Grade(student, small, 18, "2026-01-15").percentage == pytest.approx(90.0)

    def test_is_passing_uses_the_course_threshold(self, student: Student, course: Course) -> None:
        assert Grade(student, course, 50, "2026-01-15").is_passing is True
        assert Grade(student, course, 49.9, "2026-01-15").is_passing is False

    @pytest.mark.parametrize("score", [-0.1, 100.1, 1000])
    def test_out_of_range_scores_are_rejected(
        self, student: Student, course: Course, score: float
    ) -> None:
        with pytest.raises(ValidationError) as exc:
            Grade(student, course, score, "2026-01-15")
        assert exc.value.context["field"] == "score"

    def test_non_positive_weight_is_rejected(self, student: Student, course: Course) -> None:
        with pytest.raises(ValidationError):
            Grade(student, course, 50, "2026-01-15", weight=0)

    def test_date_is_normalised_on_construction(self, student: Student, course: Course) -> None:
        assert Grade(student, course, 50, "15-01-2026").date == "2026-01-15"

    def test_date_obj_supports_sorting(self, student: Student, course: Course) -> None:
        assert Grade(student, course, 50, "2026-01-15").date_obj.month == 1

    def test_to_dict_references_by_id_not_by_nesting(
        self, student: Student, course: Course
    ) -> None:
        d = Grade(student, course, 85, "2026-01-15").to_dict()
        assert d["student_id"] == "S001"
        assert "student" not in d


class TestGradingScale:
    def test_default_scale_matches_the_specification(self) -> None:
        assert [b.label for b in DEFAULT_SCALE.bands] == ["A", "B", "C", "D", "F"]
        assert DEFAULT_SCALE.label_for(95) == "A"
        assert DEFAULT_SCALE.label_for(0) == "F"

    def test_ascending_bands_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GradingScale(bands=(GradeBand(0, "F"), GradeBand(90, "A")))

    def test_empty_scale_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GradingScale(bands=())

    def test_scale_not_reaching_zero_is_rejected(self) -> None:
        """Otherwise a score below the lowest band would have no label at all."""
        with pytest.raises(ValidationError):
            GradingScale(bands=(GradeBand(90, "A"), GradeBand(50, "B")))

    def test_round_trip_through_storage_form(self) -> None:
        assert GradingScale.from_list(DEFAULT_SCALE.to_list()) == DEFAULT_SCALE

    def test_a_custom_institution_scale_works(self) -> None:
        """German 1-6, where 1 is best — the reason bands are configurable."""
        german = GradingScale(
            bands=(
                GradeBand(92, "1"),
                GradeBand(81, "2"),
                GradeBand(67, "3"),
                GradeBand(50, "4"),
                GradeBand(30, "5"),
                GradeBand(0, "6"),
            )
        )
        assert german.label_for(95) == "1"
        assert german.label_for(55) == "4"
        assert german.label_for(10) == "6"

    def test_the_default_scale_is_priced(self) -> None:
        """A-F carries its own conventional points; that is a fact about the scale,
        not an assumption imposed on institutions using their own labels."""
        assert DEFAULT_SCALE.points_for(95) == 4.0
        assert DEFAULT_SCALE.points_for(0) == 0.0

    def test_an_unpriced_band_yields_no_points(self) -> None:
        """None rather than zero. Zero is a grade; None is an unanswered question,
        and only one of them belongs in an average."""
        scale = GradingScale(bands=(GradeBand(50, "pass"), GradeBand(0, "retry")))
        assert scale.points_for(80) is None
        assert scale.label_for(80) == "pass"

    def test_points_may_run_opposite_to_the_thresholds(self) -> None:
        """A German 1-6 scale awards its lowest number to its highest threshold.
        Nothing may enforce a relationship between points and percentage."""
        german = GradingScale(
            bands=(GradeBand(92, "1", 1.0), GradeBand(50, "4", 4.0), GradeBand(0, "6", 6.0))
        )
        assert german.points_for(95) == 1.0
        assert german.points_for(10) == 6.0

    def test_negative_points_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GradeBand(90, "A", -1.0)

    def test_a_scale_stored_before_points_existed_still_loads(self) -> None:
        """Backward compatibility is the whole reason `points` is optional."""
        scale = GradingScale.from_list(
            [{"min_percentage": 50, "label": "pass"}, {"min_percentage": 0, "label": "retry"}]
        )
        assert scale.bands[0].points is None

    def test_unpriced_bands_round_trip_without_gaining_a_key(self) -> None:
        """`to_list` omits points rather than writing null, so an organisation that
        never configures a GPA sees its stored document unchanged."""
        scale = GradingScale(bands=(GradeBand(0, "F"),))
        assert scale.to_list() == [{"min_percentage": 0.0, "label": "F"}]
