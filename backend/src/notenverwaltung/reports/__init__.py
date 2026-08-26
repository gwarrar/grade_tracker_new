"""Report generation: structured builders plus the text and CSV renderers."""

from notenverwaltung.reports.base import (
    CourseReport,
    GradeLine,
    ReportBuilder,
    ReportGenerator,
    StudentReport,
    SummaryReport,
)
from notenverwaltung.reports.csv_report import CsvReportGenerator
from notenverwaltung.reports.text_report import TextReportGenerator

__all__ = [
    "CourseReport",
    "CsvReportGenerator",
    "GradeLine",
    "ReportBuilder",
    "ReportGenerator",
    "StudentReport",
    "SummaryReport",
    "TextReportGenerator",
]
