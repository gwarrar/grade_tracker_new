-- Core domain: students, courses, grades.
--
-- Portability rules (see docs/DECISIONS.md — "SQLite now, Postgres later"):
--   * No AUTOINCREMENT. `INTEGER PRIMARY KEY` is SQLite's rowid alias and auto-assigns;
--     AUTOINCREMENT only adds a monotonicity guarantee we do not need and Postgres
--     spells differently.
--   * No SQLite-specific date functions in application queries. Timestamps are
--     ISO-8601 TEXT, which sorts and compares correctly as a string.
--   * No INSERT OR REPLACE.
-- Following these means porting to Postgres is editing these files, not rewriting the app.

CREATE TABLE students (
    student_id  TEXT PRIMARY KEY,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    email       TEXT NOT NULL,
    user_id     INTEGER,                  -- FK added in 002 once `users` exists
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT
);

CREATE UNIQUE INDEX idx_students_email ON students (email);

CREATE TABLE courses (
    course_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    max_grade     REAL    NOT NULL DEFAULT 100.0,
    passing_grade REAL    NOT NULL DEFAULT 50.0,
    max_students  INTEGER NOT NULL DEFAULT 30,
    teacher_id    INTEGER,                -- FK added in 002 once `users` exists
    term          TEXT,
    credits       REAL    NOT NULL DEFAULT 1.0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT,

    CHECK (max_grade > 0),
    CHECK (passing_grade > 0 AND passing_grade <= max_grade),
    CHECK (max_students > 0),
    CHECK (credits > 0)
);

CREATE TABLE grades (
    grade_id   INTEGER PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students (student_id) ON DELETE CASCADE,
    course_id  TEXT NOT NULL REFERENCES courses (course_id)  ON DELETE CASCADE,
    score      REAL NOT NULL,
    date       TEXT NOT NULL,             -- ISO YYYY-MM-DD
    notes      TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',  -- e.g. 'Midterm'; empty for a single overall grade
    weight     REAL NOT NULL DEFAULT 1.0,
    graded_by  INTEGER,                   -- FK added in 002 once `users` exists
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT,
    deleted_at TEXT,                      -- soft delete: an altered mark may be disputed later

    CHECK (score >= 0),
    CHECK (weight > 0)
);

-- Every read filters on deleted_at IS NULL, so it belongs in the index rather than
-- forcing a scan of retired rows.
CREATE INDEX idx_grades_student ON grades (student_id, deleted_at);
CREATE INDEX idx_grades_course  ON grades (course_id, deleted_at);
CREATE INDEX idx_grades_date    ON grades (date);
