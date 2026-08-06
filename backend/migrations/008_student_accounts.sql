-- Student sign-in accounts: forced first change, and the link that was never made.
--
-- Two problems, one migration.
--
-- 1. A generated password is known to whoever generated it. Until the person it
--    belongs to replaces it, the account is shared, so the application must insist
--    on the change rather than suggest it. Cleared by `AuthService.change_password`
--    and set again by every administrative reset.
ALTER TABLE users
    ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0
    CHECK (must_change_password IN (0, 1));

-- 2. Creating an account for a student and attaching it to their record were two
--    separate acts, and nothing performed the second. The result was an account
--    that signs in successfully and then sees nothing at all: `student_scope` has
--    no `student_id` to scope by, so every query matches zero rows.
--
--    The address is the join — a student account is created with the address on the
--    student record. Only unlinked records and only student-role accounts, so this
--    can never steal a link or hand a teacher's account a student's visibility.
UPDATE students
   SET user_id = (
       SELECT u.id FROM users u
        WHERE u.email = students.email AND u.role = 'student'
   )
 WHERE user_id IS NULL
   AND EXISTS (
       SELECT 1 FROM users u
        WHERE u.email = students.email AND u.role = 'student'
   );
