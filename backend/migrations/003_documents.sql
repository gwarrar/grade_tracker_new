-- Unstructured course text: syllabi, policies, handbook sections.
--
-- Created empty and deliberately. The AI features answer questions about grades with
-- SQL, because grades are structured and SQL returns exact numbers where a vector
-- search returns approximate matches. But "what is the late-submission policy for
-- CS101" is not a SQL question, and that is when retrieval starts to earn its keep.
--
-- The escalation path, each rung needing no new infrastructure:
--   1. now      — SQL tool-calling over grades          (implemented)
--   2. keyword  — SQLite FTS5 over this table           (stdlib, zero dependencies)
--   3. semantic — the sqlite-vec extension              (one file, still one database)
--   4. scale    — a dedicated vector database           (not this project)
--
-- Defining the table now means rung 2 is a migration rather than a refactor.

CREATE TABLE documents (
    id         INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'note',
    course_id  TEXT REFERENCES courses (course_id) ON DELETE CASCADE,
    created_by INTEGER REFERENCES users (id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT,

    CHECK (kind IN ('note', 'syllabus', 'policy', 'handbook'))
);

CREATE INDEX idx_documents_course ON documents (course_id);
