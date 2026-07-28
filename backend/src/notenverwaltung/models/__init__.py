"""Domain models: plain dataclasses that validate themselves and perform no I/O."""

from notenverwaltung.models.course import Course
from notenverwaltung.models.grade import Grade, normalise_date
from notenverwaltung.models.student import Student

__all__ = ["Course", "Grade", "Student", "normalise_date"]
