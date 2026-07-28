"""Report generation: structured builders plus per-format renderers."""

from notenverwaltung.reports.base import (
    CourseReport,
    GradeLine,
    JsonReportGenerator,
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
    "JsonReportGenerator",
    "ReportBuilder",
    "ReportGenerator",
    "StudentReport",
    "SummaryReport",
    "TextReportGenerator",
]
