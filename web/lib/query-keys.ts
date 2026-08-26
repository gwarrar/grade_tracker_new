/**
 * Every TanStack Query key, in one place.
 *
 * Keys were written inline at 52 call sites, and two things went wrong that only
 * this file can prevent.
 *
 * **The same request cached twice.** `GET /reports/student/{id}` was fetched under
 * `["reports","student",id]` on the reports screen and `["report","student",id]` in
 * the student panel and the printable page. Singular and plural are different cache
 * entries, so editing a mark refreshed one and left the other showing the old
 * average with no way to tell.
 *
 * **A prefix that was not meant to be one.** `["courses","management"]` fetched every
 * course; `["courses","management","active"]` fetched only the active ones. The
 * second reads as a child of the first, so invalidating the parent also invalidated a
 * query fetched with different parameters — and TanStack was right to, because that
 * is what the key said.
 *
 * The shape below makes both impossible: a list always carries its parameters, and
 * variants of a list are **siblings** under `picker`, never nested inside each other.
 * `root` is the invalidation handle — the only thing a mutation should reach for.
 */

/** Parameters that identify one page of a list. */
type ListParams = Record<string, unknown>;

/**
 * An entity id that may not be chosen yet.
 *
 * Detail queries are gated on `enabled: id !== null`, so the key is still built on
 * the render where nothing is selected. Accepting the absence keeps that honest
 * rather than pushing a non-null assertion into every caller.
 */
type MaybeId = string | null | undefined;

export const queryKeys = {
  students: {
    root: ["students"] as const,
    list: (params: ListParams) => ["students", "list", params] as const,
    /** A dropdown's copy of the student list, keyed by which dropdown. */
    picker: (name: string, params: ListParams = {}) =>
      ["students", "picker", name, params] as const,
    detail: (id: MaybeId) => ["students", "detail", id] as const,
    courses: (id: MaybeId) => ["students", "detail", id, "courses"] as const,
  },

  courses: {
    root: ["courses"] as const,
    list: (params: ListParams) => ["courses", "list", params] as const,
    /**
     * A dropdown's copy of the course list.
     *
     * Every picker fetches a different slice — all courses, active only, sorted for
     * the grade form — so each is its own sibling. Nesting them was the bug.
     */
    picker: (name: string) => ["courses", "picker", name] as const,
    detail: (id: MaybeId) => ["courses", "detail", id] as const,
    enrollments: (id: MaybeId) => ["courses", "detail", id, "enrollments"] as const,
  },

  grades: {
    root: ["grades"] as const,
    list: (params: ListParams) => ["grades", "list", params] as const,
    detail: (id: MaybeId) => ["grades", "detail", id] as const,
    history: (id: MaybeId) => ["grades", "detail", id, "history"] as const,
  },

  reports: {
    root: ["reports"] as const,
    summary: () => ["reports", "summary"] as const,
    student: (id: MaybeId) => ["reports", "student", id] as const,
    course: (id: string) => ["reports", "course", id] as const,
    teacher: (id: string) => ["reports", "teacher", id] as const,
    term: (term: string) => ["reports", "term", term] as const,
    assessments: (courseId: string) => ["reports", "assessments", courseId] as const,
    enrollment: () => ["reports", "enrollment"] as const,
    distribution: (bucket: string) => ["reports", "distribution", bucket] as const,
  },

  analytics: {
    root: ["analytics"] as const,
    dashboard: () => ["analytics", "dashboard"] as const,
    atRisk: () => ["analytics", "at-risk"] as const,
    topStudents: () => ["analytics", "top-students"] as const,
  },

  audit: {
    root: ["audit"] as const,
    list: (params: ListParams) => ["audit", "list", params] as const,
  },

  notes: {
    root: ["notes"] as const,
    forEntity: (entityType: string, entityId: string) =>
      ["notes", entityType, entityId] as const,
  },

  profile: {
    root: ["profile"] as const,
    sessions: () => ["profile", "sessions"] as const,
  },

  admin: {
    users: {
      root: ["admin", "users"] as const,
      list: (params: ListParams) => ["admin", "users", "list", params] as const,
      picker: (name: string, params: ListParams = {}) =>
        ["admin", "users", "picker", name, params] as const,
    },
    ai: {
      root: ["admin", "ai"] as const,
      providers: () => ["admin", "ai", "providers"] as const,
      routing: () => ["admin", "ai", "routing"] as const,
      usage: () => ["admin", "ai", "usage"] as const,
      models: (providerId: number | string | null) =>
        ["admin", "ai", "models", providerId] as const,
    },
  },

  /** The ⌘K palette's own searches, deliberately separate from the list screens. */
  palette: {
    students: (query: string) => ["palette", "students", query] as const,
    courses: (query: string) => ["palette", "courses", query] as const,
  },

  /** The importer's AI column-mapping suggestion, keyed by the file's own headers. */
  importMap: (kind: string, headers: readonly string[]) =>
    ["import", "map", kind, headers] as const,
} as const;

/**
 * Every cache root a write to a student, course, grade or enrolment can affect.
 *
 * Three views used to keep private lists of what to invalidate, and they drifted:
 * only one of them refreshed grade history, so editing a student left it stale on
 * the other two. The fix at the time was `invalidateQueries()` with no key at all,
 * which cannot drift but refetches every mounted query in the application —
 * including the AI usage table and the audit feed, which no grade edit can change.
 *
 * One list, in one place, is what stops both failure modes. Add a root here when a
 * new screen shows academic data; nothing else needs touching.
 */
export const academicRoots = [
  queryKeys.students.root,
  queryKeys.courses.root,
  queryKeys.grades.root,
  queryKeys.reports.root,
  queryKeys.analytics.root,
  queryKeys.notes.root,
  queryKeys.audit.root,
] as const;
