-- Additive directory metadata and course prerequisites.

ALTER TABLE courses ADD COLUMN description TEXT;
ALTER TABLE courses ADD COLUMN room TEXT;
ALTER TABLE courses ADD COLUMN schedule TEXT;
ALTER TABLE courses ADD COLUMN department TEXT;
ALTER TABLE courses ADD COLUMN start_date TEXT
    CHECK (
        start_date IS NULL
        OR (
            length(start_date) = 10
            AND date(start_date, '+0 days') IS NOT NULL
            AND date(start_date, '+0 days') = start_date
        )
    );
ALTER TABLE courses ADD COLUMN end_date TEXT
    CHECK (
        end_date IS NULL
        OR (
            length(end_date) = 10
            AND date(end_date, '+0 days') IS NOT NULL
            AND date(end_date, '+0 days') = end_date
        )
    );
ALTER TABLE courses ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'archived'));

ALTER TABLE students ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
    CHECK (is_active IN (0, 1));
ALTER TABLE students ADD COLUMN phone TEXT;
ALTER TABLE students ADD COLUMN date_of_birth TEXT
    CHECK (
        date_of_birth IS NULL
        OR (
            length(date_of_birth) = 10
            AND date(date_of_birth, '+0 days') IS NOT NULL
            AND date(date_of_birth, '+0 days') = date_of_birth
        )
    );
ALTER TABLE students ADD COLUMN cohort TEXT;

CREATE TABLE course_prerequisites (
    course_id         TEXT NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    requires_course_id TEXT NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,

    PRIMARY KEY (course_id, requires_course_id),
    CHECK (course_id <> requires_course_id)
);
