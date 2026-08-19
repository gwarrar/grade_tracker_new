"""Populate a database with realistic demo data.

Usage:
    uv run python -m api.seed [--reset]

Deterministic: the same run produces the same data, so a screenshot or a test
assertion does not drift between runs. Uses a seeded :class:`random.Random` rather
than the global one, which would otherwise be perturbed by anything else importing
this module.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import date, timedelta

from api.config import get_settings
from notenverwaltung.models import Course, Grade, Role, Student, User
from notenverwaltung.storage import GradeStore, apply_migrations, connect, transaction
from services.security import hash_password

_SEED = 20260728
_DEMO_PASSWORD = "demo-password-2026"  # noqa: S105 - a demo credential, not a secret

_FIRST_NAMES = [
    "Anna",
    "Ben",
    "Clara",
    "David",
    "Elena",
    "Felix",
    "Greta",
    "Hugo",
    "Ida",
    "Jonas",
    "Karla",
    "Lukas",
    "Mira",
    "Noah",
    "Olivia",
    "Paul",
    "Quinn",
    "Rosa",
    "Sami",
    "Tara",
    "Ulrich",
    "Vera",
    "Willem",
    "Xenia",
    "Yara",
    "Zoe",
    "Amelie",
    "Bruno",
    "Chloe",
    "Dario",
    "Emil",
    "Fiona",
    "Gustav",
    "Hanna",
    "Ivan",
    "Julia",
    "Kilian",
    "Lena",
    "Mateo",
    "Nina",
]
_LAST_NAMES = [
    "Schmidt",
    "Mueller",
    "Dubois",
    "Weber",
    "Fischer",
    "Meyer",
    "Wagner",
    "Becker",
    "Hoffmann",
    "Schulz",
    "Martin",
    "Bernard",
    "Petit",
    "Durand",
    "Leroy",
    "Moreau",
    "Simon",
    "Laurent",
    "Lefebvre",
    "Roux",
]

# Pass marks sit at 60% of the maximum, aligning with the D band of the default
# grading scale. A course can legitimately be configured otherwise -- passing at 50%
# while the scale calls anything under 60% an F is a real institutional policy -- but
# in demo data it renders as "F ... PASS" on the same row and reads as a defect.
_COURSES = [
    ("CS101", "Intro to Programming", 100.0, 60.0, 30, "2026-SS", 5.0),
    ("CS102", "Data Structures", 100.0, 60.0, 25, "2026-SS", 5.0),
    ("CS201", "Databases", 100.0, 60.0, 25, "2026-SS", 4.0),
    ("MA110", "Discrete Mathematics", 20.0, 12.0, 40, "2026-SS", 3.0),
    ("SE210", "Software Engineering", 100.0, 60.0, 20, "2026-WS", 6.0),
    ("SE220", "Testing and Quality", 50.0, 30.0, 20, "2026-WS", 3.0),
]

_ASSESSMENTS = [("Midterm", 1.0), ("Coursework", 1.5), ("Final", 2.5)]


def _insert_user(conn: sqlite3.Connection, user: User) -> int:
    """Insert one account with the shared demo password.

    Args:
        conn: An open connection.
        user: The account to write. Validated by the model before it reaches SQL.

    Returns:
        The new user id.
    """
    digest, salt = hash_password(_DEMO_PASSWORD)
    cursor = conn.execute(
        "INSERT INTO users (email, password_hash, password_salt, role, full_name)"
        " VALUES (?, ?, ?, ?, ?)",
        (user.email, digest, salt, str(user.role), user.full_name),
    )
    row_id = cursor.lastrowid
    if row_id is None:  # pragma: no cover - an INSERT always assigns a rowid
        raise RuntimeError(f"insert of {user.email} returned no row id")
    return row_id


def _make_users(conn: sqlite3.Connection, rng: random.Random) -> dict[str, int]:
    """Insert the staff accounts.

    The student account is not here: it has to be linked to a student record, which
    does not exist yet at this point. See :func:`_link_student_login`.

    Args:
        conn: An open connection.
        rng: The seeded generator (unused today; kept so account details can be
            randomised later without changing the signature).

    Returns:
        Email to user id, for wiring teachers to their courses.
    """
    accounts = [
        ("admin@gradetracker.test", "Sam Okonkwo", Role.SUPERADMIN),
        ("registrar@gradetracker.test", "Priya Raman", Role.ADMIN),
        ("t.weber@gradetracker.test", "Thomas Weber", Role.TEACHER),
        ("m.laurent@gradetracker.test", "Marie Laurent", Role.TEACHER),
        ("k.novak@gradetracker.test", "Karel Novak", Role.TEACHER),
    ]

    return {
        email: _insert_user(conn, User(email=email, full_name=name, role=role))
        for email, name, role in accounts
    }


def _link_student_login(conn: sqlite3.Connection, student: Student) -> int:
    """Give one student a sign-in account and link it to their record.

    ``Role.STUDENT`` is scoped throughout ``services/scoping.py``, but a student
    principal falls through to ``DENY_ALL`` unless a ``students`` row points at their
    account. Without this the role is unreachable in a running app, and the
    "only your own rows" path can only ever be exercised by a test fixture.

    The account uses the student's own address rather than a second invented one, so
    there is exactly one email per person.

    Args:
        conn: An open connection.
        student: The already-inserted student record to attach the account to.

    Returns:
        The new user id.
    """
    user_id = _insert_user(
        conn, User(email=student.email, full_name=student.full_name, role=Role.STUDENT)
    )
    conn.execute(
        "UPDATE students SET user_id = ? WHERE student_id = ?", (user_id, student.student_id)
    )
    return user_id


def seed(conn: sqlite3.Connection, *, student_count: int = 40) -> dict[str, int]:
    """Populate a migrated database.

    Args:
        conn: An open, migrated connection.
        student_count: How many students to create.

    Returns:
        Counts per entity, for reporting.
    """
    rng = random.Random(_SEED)  # noqa: S311 - demo data, not cryptography
    store = GradeStore(conn)

    user_ids = _make_users(conn, rng)
    teachers = [
        user_ids["t.weber@gradetracker.test"],
        user_ids["m.laurent@gradetracker.test"],
        user_ids["k.novak@gradetracker.test"],
    ]

    for index, (cid, name, mx, passing, cap, term, credits) in enumerate(_COURSES):
        store.add_course(
            Course(
                course_id=cid,
                name=name,
                max_grade=mx,
                passing_grade=passing,
                max_students=cap,
                teacher_id=teachers[index % len(teachers)],
                term=term,
                credits=credits,
            )
        )

    students: list[Student] = []
    for i in range(1, student_count + 1):
        first = _FIRST_NAMES[(i - 1) % len(_FIRST_NAMES)]
        last = _LAST_NAMES[(i * 7) % len(_LAST_NAMES)]
        student = Student(
            student_id=f"S{i:03d}",
            first_name=first,
            last_name=last,
            email=f"{first.lower()}.{last.lower()}{i}@students.test",
        )
        store.add_student(student)
        students.append(student)

    user_ids[students[0].email] = _link_student_login(conn, students[0])

    # Each student enrols on 2-4 courses and is graded on most of them. Some
    # enrolments are deliberately left ungraded: a student enrolled but not yet
    # assessed is exactly the state the coursework schema could not represent, and
    # the UI needs real examples of it.
    enrollments = 0
    grades = 0
    start = date(2026, 1, 12)

    for student in students:
        chosen = rng.sample(_COURSES, k=rng.randint(2, 4))
        # A quarter of students sit at the weak end, so at-risk lists and the F band
        # are populated rather than theoretical.
        struggling = rng.random() < 0.25

        for cid, _, mx, _, _, _, _ in chosen:
            conn.execute(
                "INSERT INTO enrollments (student_id, course_id) VALUES (?, ?)",
                (student.student_id, cid),
            )
            enrollments += 1

            if rng.random() < 0.15:
                continue  # enrolled, not yet graded

            course = store.get_course(cid)
            for offset, (title, weight) in enumerate(_ASSESSMENTS):
                if rng.random() < 0.2:
                    continue  # assessment not sat yet
                ratio = rng.uniform(0.28, 0.58) if struggling else rng.uniform(0.55, 0.99)
                store.record_grade(
                    Grade(
                        student=student,
                        course=course,
                        score=round(mx * ratio, 1),
                        date=(start + timedelta(days=30 * offset + rng.randint(0, 9))).isoformat(),
                        title=title,
                        weight=weight,
                        graded_by=course.teacher_id,
                    )
                )
                grades += 1

    return {
        "users": len(user_ids),
        "courses": len(_COURSES),
        "students": len(students),
        "enrollments": enrollments,
        "grades": grades,
    }


def main(argv: list[str] | None = None) -> int:
    """Seed the configured database.

    Args:
        argv: Command-line arguments. Defaults to :data:`sys.argv`.

    Returns:
        A process exit code.
    """
    parser = argparse.ArgumentParser(description="Populate the database with demo data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing database file first. Destroys all data.",
    )
    parser.add_argument("--students", type=int, default=40, help="How many students to create.")
    args = parser.parse_args(argv)

    settings = get_settings()
    db_file = settings.database_file

    if args.reset and db_file.exists():
        db_file.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = db_file.with_name(db_file.name + suffix)
            sidecar.unlink(missing_ok=True)
        print(f"removed {db_file}")

    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_file)
    try:
        apply_migrations(conn)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            print("database already has users; re-run with --reset to start over")
            return 1

        with transaction(conn):
            counts = seed(conn, student_count=args.students)
        # Read back rather than re-derive: the student login is whichever record
        # _link_student_login attached the account to, and the database knows.
        student_login = conn.execute(
            "SELECT email FROM users WHERE role = 'student' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    except Exception as exc:  # a CLI reports failures, it does not re-raise them at the user
        print(f"seed failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    for entity, count in counts.items():
        print(f"{count:>5}  {entity}")
    print(f"\nevery demo account shares the password {_DEMO_PASSWORD}")
    print("  admin@gradetracker.test       superadmin")
    print("  registrar@gradetracker.test   admin")
    print("  t.weber@gradetracker.test     teacher")
    print(f"  {student_login:<28}  student")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
