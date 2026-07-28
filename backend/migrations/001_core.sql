-- Core schema: organisation, identity, domain, audit.
--
-- Table order is load-bearing: a table must exist before another references it.
-- `users` therefore precedes `students`, `courses` and `grades`, all of which point
-- at it. Adding those foreign keys later would mean a create-copy-drop-rename rebuild,
-- because SQLite has no ALTER TABLE ADD CONSTRAINT.
--
-- Portability rules (see docs/DECISIONS.md — "SQLite now, Postgres later"):
--   * No AUTOINCREMENT. `INTEGER PRIMARY KEY` is SQLite's rowid alias and auto-assigns;
--     AUTOINCREMENT only adds a monotonicity guarantee we do not need and Postgres
--     spells differently.
--   * No SQLite-specific date functions in application queries. Timestamps are
--     ISO-8601 TEXT, which sorts and compares correctly as a string.
--   * No INSERT OR REPLACE.
-- Following these means porting to Postgres is editing these files, not rewriting the app.

-- ── Organisation ────────────────────────────────────────────────────────────
-- Exactly one row, id = 1. A table rather than a config file so an administrator can
-- change branding, locale and the grading scale from the UI without a redeploy.
CREATE TABLE organization (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    name                 TEXT NOT NULL,
    short_name           TEXT NOT NULL DEFAULT '',
    logo_path            TEXT,
    favicon_path         TEXT,

    -- Brand colours, stored per theme. The admin picker validates contrast against
    -- both backgrounds, so a colour legible on white but not on near-black is rejected.
    color_primary_light  TEXT NOT NULL DEFAULT '#2E5BFF',
    color_primary_dark   TEXT NOT NULL DEFAULT '#7C9BFF',
    color_accent_light   TEXT NOT NULL DEFAULT '#00A37A',
    color_accent_dark    TEXT NOT NULL DEFAULT '#3DD9AC',

    default_locale       TEXT NOT NULL DEFAULT 'en',
    enabled_locales_json TEXT NOT NULL DEFAULT '["en","de","fr"]',
    default_theme        TEXT NOT NULL DEFAULT 'system',
    timezone             TEXT NOT NULL DEFAULT 'UTC',

    -- A/B/C/D/F at 90/80/70/60 by default. Institutions differ (German 1-6,
    -- pass/merit/distinction), so the bands are data rather than code.
    grading_scale_json   TEXT NOT NULL DEFAULT
        '[{"min_percentage":90,"label":"A"},{"min_percentage":80,"label":"B"},{"min_percentage":70,"label":"C"},{"min_percentage":60,"label":"D"},{"min_percentage":0,"label":"F"}]',

    updated_at           TEXT,

    CHECK (default_theme IN ('light', 'dark', 'system'))
);

-- Admin-supplied overrides of individual UI strings, merged over the shipped
-- translation files at GET /org/i18n/{locale}. Institutions rename "Student" to
-- "Trainee", "Course" to "Modul", and expect that to apply without a rebuild.
CREATE TABLE i18n_overrides (
    locale     TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_by INTEGER,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    PRIMARY KEY (locale, key)
);

-- ── Identity ────────────────────────────────────────────────────────────────
CREATE TABLE users (
    id                INTEGER PRIMARY KEY,
    email             TEXT NOT NULL,
    password_hash     TEXT NOT NULL,      -- scrypt, hex
    password_salt     TEXT NOT NULL,      -- per-user, hex
    role              TEXT NOT NULL,
    full_name         TEXT NOT NULL,
    avatar_path       TEXT,
    locale            TEXT,               -- NULL: follow the organisation default
    theme_preference  TEXT,               -- NULL: follow the organisation default
    is_active         INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at        TEXT,

    CHECK (role IN ('superadmin', 'admin', 'teacher', 'student')),
    CHECK (theme_preference IS NULL OR theme_preference IN ('light', 'dark', 'system'))
);

-- Case-insensitive: nobody expects Anna@school.de and anna@school.de to be two accounts.
CREATE UNIQUE INDEX idx_users_email ON users (lower(email));

-- A session is a database row, not a signed token: revocation is a DELETE and takes
-- effect immediately, which is what "log out my other devices" has to mean.
CREATE TABLE sessions (
    token_sha256 TEXT PRIMARY KEY,        -- the raw token is never stored
    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    expires_at   TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_seen_at TEXT,
    user_agent   TEXT NOT NULL DEFAULT '',
    ip_address   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_sessions_user    ON sessions (user_id);
CREATE INDEX idx_sessions_expires ON sessions (expires_at);

-- ── Domain ──────────────────────────────────────────────────────────────────
CREATE TABLE students (
    student_id TEXT PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name  TEXT NOT NULL,
    email      TEXT NOT NULL,
    -- Nullable: a student record can exist without a login. Deleting the account
    -- must not delete the academic record, hence SET NULL rather than CASCADE.
    user_id    INTEGER REFERENCES users (id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT
);

CREATE UNIQUE INDEX idx_students_email ON students (email);
CREATE INDEX idx_students_user         ON students (user_id);

CREATE TABLE courses (
    course_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    max_grade     REAL    NOT NULL DEFAULT 100.0,
    passing_grade REAL    NOT NULL DEFAULT 50.0,
    max_students  INTEGER NOT NULL DEFAULT 30,
    -- Drives row-level access: a teacher sees only the courses they own.
    teacher_id    INTEGER REFERENCES users (id) ON DELETE SET NULL,
    term          TEXT,
    credits       REAL    NOT NULL DEFAULT 1.0,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at    TEXT,

    CHECK (max_grade > 0),
    CHECK (passing_grade > 0 AND passing_grade <= max_grade),
    CHECK (max_students > 0),
    CHECK (credits > 0)
);

CREATE INDEX idx_courses_teacher ON courses (teacher_id);
CREATE INDEX idx_courses_term    ON courses (term);

-- The link the coursework version lacked. Without it a student who is enrolled but
-- not yet graded is invisible to the course, and "how many students are in CS101"
-- can only be answered by counting grade rows — which double-counts anyone with more
-- than one assessment.
CREATE TABLE enrollments (
    student_id  TEXT NOT NULL REFERENCES students (student_id) ON DELETE CASCADE,
    course_id   TEXT NOT NULL REFERENCES courses (course_id)   ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'active',
    enrolled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    enrolled_by INTEGER REFERENCES users (id) ON DELETE SET NULL,

    PRIMARY KEY (student_id, course_id),
    CHECK (status IN ('active', 'withdrawn', 'completed'))
);

CREATE INDEX idx_enrollments_course ON enrollments (course_id, status);

CREATE TABLE grades (
    grade_id   INTEGER PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students (student_id) ON DELETE CASCADE,
    course_id  TEXT NOT NULL REFERENCES courses (course_id)   ON DELETE CASCADE,
    score      REAL NOT NULL,
    date       TEXT NOT NULL,             -- ISO YYYY-MM-DD
    notes      TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',  -- e.g. 'Midterm'; empty for a single overall grade
    weight     REAL NOT NULL DEFAULT 1.0,
    graded_by  INTEGER REFERENCES users (id) ON DELETE SET NULL,
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

-- ── Audit ───────────────────────────────────────────────────────────────────
-- Append-only. A grade system must be able to answer "who changed this mark, when,
-- and from what" — a question that arrives months later, during a dispute, when the
-- current row alone cannot answer it.
CREATE TABLE audit_log (
    id             INTEGER PRIMARY KEY,
    actor_user_id  INTEGER REFERENCES users (id) ON DELETE SET NULL,
    entity         TEXT NOT NULL,         -- 'grade', 'student', 'course', 'user', ...
    entity_id      TEXT NOT NULL,
    action         TEXT NOT NULL,         -- 'create', 'update', 'delete'
    before_json    TEXT,
    after_json     TEXT,
    at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    CHECK (action IN ('create', 'update', 'delete'))
);

CREATE INDEX idx_audit_entity ON audit_log (entity, entity_id, at);
CREATE INDEX idx_audit_actor  ON audit_log (actor_user_id, at);

-- ── Seed the singleton organisation ─────────────────────────────────────────
INSERT INTO organization (id, name, short_name) VALUES (1, 'Grade Tracker', 'GT');
