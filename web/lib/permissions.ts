/**
 * What the signed-in user may do — one module, mirroring the backend rules.
 *
 * **This is not a security boundary.** Every rule here exists identically in the API,
 * which is where it is enforced; a caller who bypasses the interface gets a 403 or a
 * 404 regardless. What this module buys is honesty: before it, the Edit buttons on
 * students, courses and grades rendered for *every* role including students, who then
 * filled in a form and were refused on submit. An interface that offers an action it
 * knows will fail is lying to the person using it.
 *
 * Three properties are deliberate:
 *
 * - **Pure functions, no React, no `"use client"`.** So the same predicate runs in a
 *   server `page.tsx` guard and in a client component's JSX. One rule, one place, and
 *   no chance of the page allowing what the component forbids.
 * - **Each entry names its backend counterpart in a comment.** When the API rule
 *   changes, the comment is where you look to find what must change here.
 * - **Hide, never disable.** A greyed-out button still advertises a capability. The
 *   only exception in the codebase is the account admin table, where a disabled
 *   control communicates *"not on yourself"* rather than *"not for your role"* — a
 *   distinction worth showing.
 *
 * The counterpart test (`__tests__/permissions.test.ts`) asserts every capability is
 * false for a student except reading their own report, which is what makes the
 * hide-everything claim checkable rather than aspirational.
 */

import { atLeast, type Me } from "./session";

/** Just the fields a rule needs — so tests can build one without a full session. */
export type Principal = Pick<Me, "role" | "user_id" | "student_id">;

/** Just the ownership field a course rule needs. */
export interface CourseLike {
  teacher_id?: number | null;
}

export const can = {
  // ── Students ──────────────────────────────────────────────────────────────
  // directory.py: create_student / update_student / delete_student take AdminUser.
  writeStudent: (p: Principal): boolean => atLeast(p.role, "admin"),

  // ── Courses ───────────────────────────────────────────────────────────────
  // directory.py: create_course takes TeacherUser — a teacher owns what they create.
  createCourse: (p: Principal): boolean => atLeast(p.role, "teacher"),

  // scoping.py can_write_course(): any admin, or the teacher who owns this course.
  writeCourse: (p: Principal, course: CourseLike): boolean =>
    atLeast(p.role, "admin") || (p.role === "teacher" && course.teacher_id === p.user_id),

  // Same rule: the enrolment endpoints are owner-or-admin, via _assert_can_write.
  writeEnrolment: (p: Principal, course: CourseLike): boolean => can.writeCourse(p, course),

  // ── Grades ────────────────────────────────────────────────────────────────
  // grades.py: record / amend / retire take TeacherUser, and the row permission is
  // the scope. grade_scope(teacher) is student_scope AND course_scope, and
  // course_scope(teacher) is "courses I own" — so a grade a teacher can *see* is a
  // grade they may write, and a course-level check here would be redundant.
  // If grade scope ever widens, this needs a course_id → teacher_id lookup.
  writeGrade: (p: Principal): boolean => atLeast(p.role, "teacher"),

  // ── Reports ───────────────────────────────────────────────────────────────
  // reporting.py _assert_may_read_summary(): teacher and above.
  viewReports: (p: Principal): boolean => atLeast(p.role, "teacher"),

  // reporting.py student_report(): a student's own report is theirs in full, a
  // teacher's copy is trimmed to their own courses. This is the rule that lets one
  // component serve both readers instead of a separate student-facing page.
  viewStudentReport: (p: Principal, studentId: string): boolean =>
    p.student_id === studentId || atLeast(p.role, "teacher"),

  // ── Administration ────────────────────────────────────────────────────────
  // audit.py feed(): the whole table is admin-only, so there is no row dimension.
  viewAudit: (p: Principal): boolean => atLeast(p.role, "admin"),

  // importing.py: students and courses take AdminUser; grades take TeacherUser.
  importData: (p: Principal): boolean => atLeast(p.role, "admin"),
  importGrades: (p: Principal): boolean => atLeast(p.role, "teacher"),

  // users.py: every route takes AdminUser (with further self/rank guards inside).
  manageUsers: (p: Principal): boolean => atLeast(p.role, "admin"),

  // admin_ai.py: every route takes SuperAdminUser. Provider keys and model routing
  // are the first half of what separates a superadmin from an admin.
  manageAi: (p: Principal): boolean => p.role === "superadmin",

  // organization.py: branding, assets and the grading scale are SuperAdminUser.
  // The second half of that separation.
  editBranding: (p: Principal): boolean => p.role === "superadmin",

  // localization.py: the override write path is admin and above.
  editOverrides: (p: Principal): boolean => atLeast(p.role, "admin"),

  // ── Notes ─────────────────────────────────────────────────────────────────
  // notes.py: a note on a *student* record is staff-written.
  writeStudentNote: (p: Principal): boolean => atLeast(p.role, "teacher"),

  // A note on a *course* may be written by anyone who can see the course, students
  // included — a course thread that excluded the class would not be a thread. Takes a
  // principal it does not read, so that every entry in this object has one shape and a
  // caller never has to remember which ones need arguments.
  writeCourseNote: (): boolean => true,

  // notes.py delete(): the author, or any admin. Nobody edits anyone's note,
  // including their own, so there is no `editNote`.
  deleteNote: (p: Principal, note: { author_id?: number | null }): boolean =>
    atLeast(p.role, "admin") || note.author_id === p.user_id,
} as const;
