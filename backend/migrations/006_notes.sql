-- Notes on students and courses.
--
-- A new table rather than the dormant `documents` table: reusing that one would need
-- `student_id`, `visibility`, `author_name` and a widened `kind` CHECK, and SQLite
-- cannot alter a CHECK without a create-copy-drop-rename rebuild. `documents` keeps
-- its retrieval-corpus purpose.
CREATE TABLE notes (
    id          INTEGER PRIMARY KEY,
    entity      TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    body        TEXT NOT NULL,
    visibility  TEXT NOT NULL DEFAULT 'staff',
    author_id   INTEGER REFERENCES users (id) ON DELETE SET NULL,
    -- Denormalised on purpose: "the author's name is always shown" must survive the
    -- account being deleted — the same trade `audit.history` already makes.
    author_name TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    CHECK (entity IN ('student', 'course')),
    CHECK (visibility IN ('private', 'staff', 'shared', 'course'))
);

-- The list queries filter on (entity, entity_id) and order by created_at.
CREATE INDEX idx_notes_entity ON notes (entity, entity_id, created_at);
