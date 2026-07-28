"""Domain models: plain dataclasses that validate themselves and perform no I/O."""

from notenverwaltung.models.course import Course
from notenverwaltung.models.enrollment import Enrollment, EnrollmentStatus
from notenverwaltung.models.grade import Grade, normalise_date
from notenverwaltung.models.organization import (
    SUPPORTED_LOCALES,
    BrandColor,
    Organization,
)
from notenverwaltung.models.student import Student
from notenverwaltung.models.user import Role, Theme, User

__all__ = [
    "SUPPORTED_LOCALES",
    "BrandColor",
    "Course",
    "Enrollment",
    "EnrollmentStatus",
    "Grade",
    "Organization",
    "Role",
    "Student",
    "Theme",
    "User",
    "normalise_date",
]
