/**
 * The two cache-key invariants, as assertions.
 *
 * Both of these shipped as real defects before `lib/query-keys.ts` existed, and both
 * are invisible in a browser until something is stale — which is exactly the kind of
 * bug worth spending a test on.
 */

import { describe, expect, it } from "vitest";

import { academicRoots, queryKeys } from "../query-keys";

/** Is `a` a prefix of `b` — i.e. would invalidating `a` also invalidate `b`? */
function isPrefixOf(a: readonly unknown[], b: readonly unknown[]): boolean {
  if (a.length >= b.length) return false;
  return a.every((segment, index) => JSON.stringify(segment) === JSON.stringify(b[index]));
}

describe("one request, one key", () => {
  it("caches a student report under the same key wherever it is asked for", () => {
    // The reports screen, the student detail panel and the printable page each
    // fetched GET /reports/student/{id}. Two of them said "report" and one said
    // "reports", so editing a mark refreshed one and left the others showing the
    // old average.
    expect(queryKeys.reports.student("S001")).toEqual(queryKeys.reports.student("S001"));
    expect(queryKeys.reports.student("S001")).not.toEqual(queryKeys.reports.student("S002"));
  });
});

describe("no picker is a prefix of another", () => {
  // `["courses","management"]` fetched every course and
  // `["courses","management","active"]` only the active ones, which made the second
  // read as a child of the first: invalidating the parent silently invalidated a
  // query fetched with entirely different parameters.
  const pickers = [
    queryKeys.courses.picker("management"),
    queryKeys.courses.picker("enrolment-active"),
    queryKeys.courses.picker("grade-entry"),
    queryKeys.courses.picker("reports"),
    queryKeys.students.picker("reports", { q: "" }),
    queryKeys.students.picker("enrolment", { q: "", courseId: "CS101" }),
    queryKeys.admin.users.picker("teachers", { role: "teacher" }),
    queryKeys.admin.users.picker("account-link"),
  ];

  it.each(pickers.map((key, index) => [index, key] as const))(
    "picker %i is a sibling, not an ancestor",
    (index, key) => {
      const others = pickers.filter((_, other) => other !== index);
      expect(others.filter((other) => isPrefixOf(key, other))).toEqual([]);
    },
  );
});

describe("every list carries its parameters", () => {
  it("distinguishes two pages of the same list", () => {
    expect(queryKeys.students.list({ q: "", page: 1 })).not.toEqual(
      queryKeys.students.list({ q: "", page: 2 }),
    );
  });

  it("keeps a detail key clear of the list it came from", () => {
    expect(isPrefixOf(queryKeys.students.list({ page: 1 }), queryKeys.students.detail("S001"))).toBe(
      false,
    );
  });
});

describe("academicRoots", () => {
  it("invalidates every screen a grade edit can change", () => {
    // A mark changes the student's average, the course's figures, every report and
    // the dashboard, and it writes an audit row.
    for (const root of [
      queryKeys.students.root,
      queryKeys.courses.root,
      queryKeys.grades.root,
      queryKeys.reports.root,
      queryKeys.analytics.root,
      queryKeys.audit.root,
    ]) {
      expect(academicRoots).toContainEqual(root);
    }
  });

  it("leaves the admin screens alone", () => {
    // No grade edit changes AI usage or provider routing. Refetching them was the
    // cost of the keyless `invalidateQueries()` this list replaced.
    expect(academicRoots).not.toContainEqual(queryKeys.admin.ai.root);
    expect(academicRoots).not.toContainEqual(queryKeys.profile.root);
  });

  it("reaches every academic root as a genuine prefix", () => {
    // A root must actually be an ancestor of the keys under it, or invalidating it
    // does nothing.
    expect(isPrefixOf(queryKeys.students.root, queryKeys.students.detail("S001"))).toBe(true);
    expect(isPrefixOf(queryKeys.courses.root, queryKeys.courses.picker("management"))).toBe(true);
    expect(isPrefixOf(queryKeys.grades.root, queryKeys.grades.history("1"))).toBe(true);
    expect(isPrefixOf(queryKeys.reports.root, queryKeys.reports.student("S001"))).toBe(true);
  });
});
