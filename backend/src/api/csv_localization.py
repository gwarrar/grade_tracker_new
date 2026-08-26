"""Column headers and cell words for downloaded CSV files.

The one place the backend translates anything. A downloaded file has no frontend to
render it in the reader's language, which is the single exception recorded in
`docs/DECISIONS.md` §5 -- every other string the API emits is a code.

Deliberately not a general message catalogue: it covers the column headers and the
handful of cell values that are words rather than data. Growing it into one would
recreate the server-side translation layer that decision exists to avoid.
"""

from __future__ import annotations

CSV_LABELS: dict[str, dict[str, str]] = {
    "en": {},  # the generator's defaults are already English
    "de": {"pass": "BESTANDEN", "fail": "NICHT BESTANDEN"},
    "fr": {"pass": "ADMIS", "fail": "NON ADMIS"},
}
"""Cell values that are words, not data. Headers alone were not enough: a German
file with an English "FAIL" in every failing row is neither language."""

CSV_HEADERS: dict[str, dict[str, str]] = {
    "en": {},  # the generator's defaults are already English
    "de": {
        "student_id": "Matrikelnummer",
        "student_name": "Studierende:r",
        "course_id": "Kurs-ID",
        "course_name": "Kurs",
        "title": "Leistung",
        "score": "Punkte",
        "max_grade": "Maximum",
        "percentage": "Prozent",
        "letter": "Note",
        "weight": "Gewichtung",
        "status": "Status",
        "date": "Datum",
        "notes": "Anmerkungen",
        "metric": "Kennzahl",
        "value": "Wert",
        "rank": "Rang",
        "average": "Durchschnitt",
        "term": "Semester",
        "teacher_name": "Lehrkraft",
        "student_count": "Studierende",
        "grade_count": "Noten",
        "pass_rate": "Bestehensquote",
        "count": "Anzahl",
        "average_score": "Ø Punkte",
        "average_percentage": "Ø Prozent",
        "min_score": "Minimum",
        "max_score": "Maximum",
        "capacity": "Kapazität",
        "active": "Aktiv",
        "withdrawn": "Abgemeldet",
        "completed": "Abgeschlossen",
        "utilisation": "Auslastung",
        "bucket": "Zeitraum",
    },
    "fr": {
        "student_id": "N° étudiant",
        "student_name": "Étudiant",
        "course_id": "Code cours",
        "course_name": "Cours",
        "title": "Évaluation",
        "score": "Note",
        "max_grade": "Maximum",
        "percentage": "Pourcentage",
        "letter": "Mention",
        "weight": "Coefficient",
        "status": "Statut",
        "date": "Date",
        "notes": "Remarques",
        "metric": "Indicateur",
        "value": "Valeur",
        "rank": "Rang",
        "average": "Moyenne",
        "term": "Semestre",
        "teacher_name": "Enseignant",
        "student_count": "Étudiants",
        "grade_count": "Notes",
        "pass_rate": "Taux de réussite",
        "count": "Nombre",
        "average_score": "Note moyenne",
        "average_percentage": "Moyenne %",
        "min_score": "Min",
        "max_score": "Max",
        "capacity": "Capacité",
        "active": "Actifs",
        "withdrawn": "Retirés",
        "completed": "Terminés",
        "utilisation": "Utilisation",
        "bucket": "Période",
    },
}

# German and French Windows Excel splits on ';'. A comma-separated file opens as a
# single column there, which reads to the user as corruption rather than a setting.
CSV_DELIMITERS = {"en": ",", "de": ";", "fr": ";"}
