"""What the store guarantees: identity, cascades, soft deletion and ordering.

These ran twice for a while, over an in-memory backend as well as SQLite, to prove
an ABC's two implementations agreed. The in-memory one shipped to nobody and the
ABC went with it — but the assertions never were about interchangeability. They
pin the behaviour every layer above depends on: that a duplicate id is refused,
that deleting a student takes their grades, that a retired grade stops appearing
while its row stays put.
"""

from __future__ import annotations

import pytest

from notenverwaltung.exceptions import (
    CourseNotFoundError,
    DuplicateEntryError,
    GradeNotFoundError,
    StudentNotFoundError,
    ValidationError,
)
from notenverwaltung.models import Course, Grade, Student
from notenverwaltung.storage import GradeStore


@pytest.fixture
def populated(store: GradeStore) -> GradeStore:
    """A store with one student, one course and one grade."""
    store.add_student(Student("S001", "Anna", "Schmidt", "anna@example.com"))
    store.add_course(Course("CS101", "Intro"))
    return store


class TestStudents:
    def test_add_then_get(self, store: GradeStore) -> None:
        student = Student("S001", "Anna", "Schmidt", "anna@example.com")
        store.add_student(student)
        assert store.get_student("S001") == student

    def test_duplicate_id_is_rejected(self, store: GradeStore) -> None:
        store.add_student(Student("S001", "Anna", "Schmidt", "anna@example.com"))
        with pytest.raises(DuplicateEntryError):
            store.add_student(Student("S001", "Other", "Person", "other@example.com"))

    def test_duplicate_email_is_rejected(self, store: GradeStore) -> None:
        store.add_student(Student("S001", "Anna", "Schmidt", "anna@example.com"))
        with pytest.raises(DuplicateEntryError):
            store.add_student(Student("S002", "Anna", "Clone", "anna@example.com"))

    def test_missing_raises_domain_error_not_key_error(self, store: GradeStore) -> None:
        """Callers must not need to know which backend they are talking to."""
        with pytest.raises(StudentNotFoundError):
            store.get_student("nope")

    def test_update_persists(self, populated: GradeStore) -> None:
        student = populated.get_student("S001")
        student.last_name = "Fischer"
        populated.update_student(student)
        assert populated.get_student("S001").last_name == "Fischer"

    def test_update_missing_raises(self, store: GradeStore) -> None:
        with pytest.raises(StudentNotFoundError):
            store.update_student(Student("ghost", "No", "One", "no@example.com"))

    def test_delete_removes(self, populated: GradeStore) -> None:
        populated.delete_student("S001")
        with pytest.raises(StudentNotFoundError):
            populated.get_student("S001")

    def test_delete_cascades_to_grades(self, populated: GradeStore) -> None:
        populated.record_grade(
            Grade(populated.get_student("S001"), populated.get_course("CS101"), 85, "2026-01-15")
        )
        populated.delete_student("S001")
        assert populated.get_all_grades() == []

    def test_list_is_ordered_by_id(self, store: GradeStore) -> None:
        for sid in ("S003", "S001", "S002"):
            store.add_student(Student(sid, "A", "B", f"{sid}@example.com"))
        assert [s.student_id for s in store.get_all_students()] == ["S001", "S002", "S003"]

    def test_mutating_a_returned_object_does_not_change_the_store(
        self, populated: GradeStore
    ) -> None:
        """Defensive copying: the store owns its state."""
        populated.get_student("S001").first_name = "Mutated"
        assert populated.get_student("S001").first_name == "Anna"


class TestCourses:
    def test_add_then_get(self, store: GradeStore) -> None:
        course = Course("CS101", "Intro")
        store.add_course(course)
        assert store.get_course("CS101") == course

    def test_duplicate_id_is_rejected(self, store: GradeStore) -> None:
        store.add_course(Course("CS101", "Intro"))
        with pytest.raises(DuplicateEntryError):
            store.add_course(Course("CS101", "Different"))

    def test_missing_raises(self, store: GradeStore) -> None:
        with pytest.raises(CourseNotFoundError):
            store.get_course("nope")

    def test_update_persists(self, populated: GradeStore) -> None:
        course = populated.get_course("CS101")
        course.name = "Renamed"
        course.credits = 3.0
        populated.update_course(course)
        refreshed = populated.get_course("CS101")
        assert (refreshed.name, refreshed.credits) == ("Renamed", 3.0)

    def test_delete_cascades_to_grades(self, populated: GradeStore) -> None:
        populated.record_grade(
            Grade(populated.get_student("S001"), populated.get_course("CS101"), 85, "2026-01-15")
        )
        populated.delete_course("CS101")
        assert populated.get_all_grades() == []


class TestGrades:
    def test_record_returns_an_assigned_id(self, populated: GradeStore) -> None:
        """The caller needs the id to edit the grade later, without a follow-up query."""
        grade = populated.record_grade(
            Grade(populated.get_student("S001"), populated.get_course("CS101"), 85, "2026-01-15")
        )
        assert grade.grade_id is not None

    def test_unknown_student_is_rejected(self, populated: GradeStore) -> None:
        """Foreign keys are genuinely enforced — they were not in the coursework version."""
        ghost = Student("ghost", "No", "One", "ghost@example.com")
        with pytest.raises(StudentNotFoundError):
            populated.record_grade(Grade(ghost, populated.get_course("CS101"), 85, "2026-01-15"))

    def test_unknown_course_is_rejected(self, populated: GradeStore) -> None:
        ghost = Course("GHOST", "Nowhere")
        with pytest.raises(CourseNotFoundError):
            populated.record_grade(Grade(populated.get_student("S001"), ghost, 85, "2026-01-15"))

    def test_get_returns_the_full_object_graph(self, populated: GradeStore) -> None:
        """One JOIN, not a follow-up query per row."""
        recorded = populated.record_grade(
            Grade(populated.get_student("S001"), populated.get_course("CS101"), 85, "2026-01-15")
        )
        assert recorded.grade_id is not None
        fetched = populated.get_grade(recorded.grade_id)
        assert fetched.student.full_name == "Anna Schmidt"
        assert fetched.course.name == "Intro"

    def test_update_persists(self, populated: GradeStore) -> None:
        grade = populated.record_grade(
            Grade(populated.get_student("S001"), populated.get_course("CS101"), 85, "2026-01-15")
        )
        grade.score = 92
        grade.title = "Resit"
        populated.update_grade(grade)
        assert grade.grade_id is not None
        refreshed = populated.get_grade(grade.grade_id)
        assert (refreshed.score, refreshed.title) == (92, "Resit")

    def test_update_unsaved_grade_is_rejected(self, populated: GradeStore) -> None:
        with pytest.raises(ValidationError):
            populated.update_grade(
                Grade(
                    populated.get_student("S001"), populated.get_course("CS101"), 85, "2026-01-15"
                )
            )

    def test_delete_is_soft_and_hides_the_row(self, populated: GradeStore) -> None:
        """An altered mark may be disputed later, so the row is retained."""
        grade = populated.record_grade(
            Grade(populated.get_student("S001"), populated.get_course("CS101"), 85, "2026-01-15")
        )
        assert grade.grade_id is not None
        populated.delete_grade(grade.grade_id)

        with pytest.raises(GradeNotFoundError):
            populated.get_grade(grade.grade_id)
        assert populated.get_all_grades() == []
        assert populated.get_student_grades("S001") == []

    def test_deleting_twice_raises(self, populated: GradeStore) -> None:
        grade = populated.record_grade(
            Grade(populated.get_student("S001"), populated.get_course("CS101"), 85, "2026-01-15")
        )
        assert grade.grade_id is not None
        populated.delete_grade(grade.grade_id)
        with pytest.raises(GradeNotFoundError):
            populated.delete_grade(grade.grade_id)

    def test_listing_is_most_recent_first(self, populated: GradeStore) -> None:
        student, course = populated.get_student("S001"), populated.get_course("CS101")
        for day in ("2026-01-10", "2026-03-01", "2026-02-01"):
            populated.record_grade(Grade(student, course, 70, day))
        assert [g.date for g in populated.get_all_grades()] == [
            "2026-03-01",
            "2026-02-01",
            "2026-01-10",
        ]

    def test_filters_by_student_and_course(self, store: GradeStore) -> None:
        store.add_student(Student("S001", "Anna", "S", "a@example.com"))
        store.add_student(Student("S002", "Ben", "M", "b@example.com"))
        store.add_course(Course("CS101", "Intro"))
        store.add_course(Course("CS102", "Data"))
        store.record_grade(
            Grade(store.get_student("S001"), store.get_course("CS101"), 85, "2026-01-15")
        )
        store.record_grade(
            Grade(store.get_student("S002"), store.get_course("CS102"), 60, "2026-01-16")
        )

        assert len(store.get_student_grades("S001")) == 1
        assert len(store.get_course_grades("CS102")) == 1
        assert len(store.get_all_grades()) == 2

    def test_a_student_may_hold_several_grades_in_one_course(self, populated: GradeStore) -> None:
        student, course = populated.get_student("S001"), populated.get_course("CS101")
        populated.record_grade(Grade(student, course, 70, "2026-01-15", title="Midterm"))
        populated.record_grade(Grade(student, course, 90, "2026-03-15", title="Final"))
        assert len(populated.get_student_grades("S001")) == 2
