/**
 * The permission matrix, asserted role by role.
 *
 * The claim this file defends is the one that is easiest to break silently: **a
 * student sees no write control anywhere.** Before `lib/permissions.ts` existed, the
 * Edit buttons on students, courses and grades rendered for every role, and nothing
 * in the suite noticed — because a missing gate produces no error, just a button.
 *
 * So the important test is not the per-capability list; it is
 * `every capability is false for a student`, driven off `Object.keys(can)` rather
 * than a hand-written list. Add a capability and forget to consider students, and
 * this fails without anyone remembering to update it.
 */

import { describe, expect, it } from "vitest";

import { can, type Principal } from "../permissions";

const STUDENT: Principal = { role: "student", user_id: 5, student_id: "S001" };
const TEACHER: Principal = { role: "teacher", user_id: 3, student_id: null };
const ADMIN: Principal = { role: "admin", user_id: 2, student_id: null };
const SUPERADMIN: Principal = { role: "superadmin", user_id: 1, student_id: null };

const OWN_COURSE = { teacher_id: 3 };
const OTHER_COURSE = { teacher_id: 99 };
const ORPHAN_COURSE = { teacher_id: null };

describe("a student may write nothing", () => {
  // The two capabilities a student legitimately has. Anything else appearing here
  // later should be a deliberate decision, not a default.
  const ALLOWED = new Set(["viewStudentReport", "writeCourseNote"]);

  it.each(Object.keys(can).filter((name) => !ALLOWED.has(name)))(
    "can.%s is false for a student",
    (name) => {
      const rule = can[name as keyof typeof can] as (
        p: Principal,
        second?: unknown,
      ) => boolean;

      // The second argument differs per rule; a course-shaped object satisfies the
      // course rules and is harmlessly ignored by the rest. `deleteNote` gets an
      // author id that is not the student's, which is the case worth checking.
      expect(rule(STUDENT, { teacher_id: 3, author_id: 999 })).toBe(false);
    },
  );

  it("may read their own report and nobody else's", () => {
    expect(can.viewStudentReport(STUDENT, "S001")).toBe(true);
    expect(can.viewStudentReport(STUDENT, "S002")).toBe(false);
  });

  it("may post on a course thread", () => {
    // Deliberate: a course discussion that excluded the class would not be one.
    // Visibility of what they then see is enforced by note_scope server-side.
    expect(can.writeCourseNote()).toBe(true);
    expect(can.writeStudentNote(STUDENT)).toBe(false);
  });
});

describe("course ownership", () => {
  it("a teacher writes their own course and not a colleague's", () => {
    expect(can.writeCourse(TEACHER, OWN_COURSE)).toBe(true);
    expect(can.writeCourse(TEACHER, OTHER_COURSE)).toBe(false);
    expect(can.writeCourse(TEACHER, ORPHAN_COURSE)).toBe(false);
  });

  it("an admin writes any course, including one with no teacher", () => {
    for (const course of [OWN_COURSE, OTHER_COURSE, ORPHAN_COURSE]) {
      expect(can.writeCourse(ADMIN, course)).toBe(true);
    }
  });

  it("enrolment follows course ownership exactly", () => {
    // Same rule by construction. Asserted anyway: if they ever diverge it should be
    // because someone changed this expectation on purpose.
    for (const [p, course] of [
      [TEACHER, OWN_COURSE],
      [TEACHER, OTHER_COURSE],
      [ADMIN, OTHER_COURSE],
      [STUDENT, OWN_COURSE],
    ] as const) {
      expect(can.writeEnrolment(p, course)).toBe(can.writeCourse(p, course));
    }
  });
});

describe("the admin / superadmin line", () => {
  it("only a superadmin configures AI and branding", () => {
    expect(can.manageAi(ADMIN)).toBe(false);
    expect(can.editBranding(ADMIN)).toBe(false);
    expect(can.manageAi(SUPERADMIN)).toBe(true);
    expect(can.editBranding(SUPERADMIN)).toBe(true);
  });

  it("both manage accounts, audit and wording", () => {
    for (const rule of [can.manageUsers, can.viewAudit, can.editOverrides]) {
      expect(rule(ADMIN)).toBe(true);
      expect(rule(SUPERADMIN)).toBe(true);
      expect(rule(TEACHER)).toBe(false);
    }
  });

  it("a teacher imports grades but not people", () => {
    expect(can.importGrades(TEACHER)).toBe(true);
    expect(can.importData(TEACHER)).toBe(false);
    expect(can.importData(ADMIN)).toBe(true);
  });
});

describe("note deletion", () => {
  const OWN = { author_id: 3 };
  const SOMEONE_ELSES = { author_id: 42 };

  it("the author may delete their own", () => {
    expect(can.deleteNote(TEACHER, OWN)).toBe(true);
    expect(can.deleteNote(TEACHER, SOMEONE_ELSES)).toBe(false);
  });

  it("an admin may delete any", () => {
    expect(can.deleteNote(ADMIN, SOMEONE_ELSES)).toBe(true);
  });

  it("an unattributed note is admin-only", () => {
    // author_id is nullable: the account was deleted. Nobody inherits authorship.
    expect(can.deleteNote(TEACHER, { author_id: null })).toBe(false);
    expect(can.deleteNote(ADMIN, { author_id: null })).toBe(true);
  });
});

describe("the hierarchy holds", () => {
  it("a superadmin can do everything a teacher can", () => {
    const teacherCan = Object.keys(can).filter((name) => {
      const rule = can[name as keyof typeof can] as (p: Principal, s?: unknown) => boolean;
      return rule(TEACHER, { teacher_id: 3, author_id: 3 });
    });

    for (const name of teacherCan) {
      const rule = can[name as keyof typeof can] as (p: Principal, s?: unknown) => boolean;
      // author_id 3 is the teacher's, not the superadmin's — an admin's blanket
      // delete right is what must carry this, not authorship.
      expect(rule(SUPERADMIN, { teacher_id: 3, author_id: 3 }), name).toBe(true);
    }
  });
});
