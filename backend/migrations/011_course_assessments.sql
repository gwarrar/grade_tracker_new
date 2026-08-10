-- What a course marks, and what each piece is worth.
--
-- `grades.title` and `grades.weight` were free text and a float typed per mark, which
-- made a course-level fact behave like a per-row one. Three things had already grown
-- around the gap: `api/seed.py` carries a hard-coded list of (title, weight) pairs,
-- every seeded course uses the same three, and `course_assessments_report` groups by
-- **exact string equality** -- so "Midterm" and "midterm " are two assessments in the
-- report and nobody is told.
--
-- This table is what a course *offers*. It is not a foreign key on `grades`, and the
-- grades table is not touched, for two reasons:
--
--   * History must not move. Reweighting a Final from 2.5 to 3 would otherwise
--     re-average every mark already awarded under the old scheme. A transcript that
--     changes because somebody edited a course is worse than a duplicate string.
--   * Nothing else has to cope. The CSV importer keeps accepting free text, the
--     report keeps grouping by title, and `grades.title` keeps its sort and search.
--     The change is confined to what the picker offers.
CREATE TABLE course_assessments (
    course_id TEXT    NOT NULL REFERENCES courses (course_id) ON DELETE CASCADE,
    name      TEXT    NOT NULL,
    weight    REAL    NOT NULL DEFAULT 1.0,
    position  INTEGER NOT NULL DEFAULT 0,

    PRIMARY KEY (course_id, name),
    CHECK (weight > 0),
    CHECK (length(trim(name)) > 0)
);

-- Seed each course from the marks it has already recorded, so nothing arrives empty
-- and no course loses the scheme it has been using in practice.
--
-- MAX(weight) because nothing has ever stopped one title carrying different weights
-- on different rows. It is deterministic, and the alternative is inventing a rule for
-- data that should not have diverged. An administrator who disagrees edits the course.
INSERT INTO course_assessments (course_id, name, weight)
SELECT course_id, title, MAX(weight)
  FROM grades
 WHERE title <> '' AND deleted_at IS NULL
 GROUP BY course_id, title;
