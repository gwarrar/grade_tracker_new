"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import {
  Field,
  FormError,
  Input,
  PanelHeader,
  Select,
  Textarea,
} from "@/components/app/detail-fields";
import { InsightBlock } from "@/components/app/insight";
import { MasterDetail } from "@/components/app/master-detail";
import { NotesBlock } from "@/components/app/notes";
import { Pager } from "@/components/app/pager";
import { Confirm } from "@/components/ui/confirm";
import { Modal } from "@/components/ui/modal";
import { api, ApiError, type Response } from "@/lib/api";
import type { paths } from "@/lib/api-schema";
import { readCourseAssessments } from "@/lib/course-assessments";
import {
  formatDate,
  formatNumber,
  formatNumberForInput,
  parseLocaleNumber,
} from "@/lib/format";
import { can } from "@/lib/permissions";
import type { Me } from "@/lib/session";
import { useDebounced, useSelection, useUrlParam } from "@/lib/use-selection";

type Course = Response<"/courses/{course_id}", "get">;
type CoursePage = Response<"/courses", "get">;
type Register = Response<"/courses/{course_id}/enrollments", "get">;
type StudentPage = Response<"/students", "get">;
type Accounts = Response<"/admin/users", "get">;
type CourseCreate = paths["/courses"]["post"]["requestBody"]["content"]["application/json"];
type CourseUpdate = paths["/courses/{course_id}"]["patch"]["requestBody"]["content"]["application/json"];

/** What can be done to one row of a course register. */
type EnrollmentAction = "enroll" | "complete" | "withdraw" | "remove";

const PAGE_SIZE = 50;

export function CoursesView({ me, locale }: { me: Me; locale: string }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [selectedId, select] = useSelection();
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const query = useDebounced(search.trim());
  const [pageParam, setPage] = useUrlParam("page", "1");
  const page = Math.max(1, Number(pageParam) || 1);

  const list = useQuery({
    queryKey: ["courses", { q: query, page }],
    queryFn: () =>
      api<CoursePage>("/courses", { query: { q: query, page, size: PAGE_SIZE } }),
    placeholderData: (previous) => previous,
  });

  const allCourses = useQuery({
    // Not filtered by status: this one feeds the *prerequisite* selector, and a
    // prerequisite is a course somebody completed in the past. Archiving it is
    // exactly what happens when a course stops running, so excluding archived
    // courses here would quietly drop the prerequisites most likely to be real.
    queryKey: ["courses", "management"],
    queryFn: () => api<CoursePage>("/courses", { query: { size: 200 } }),
    enabled: can.createCourse(me),
  });

  const detail = useQuery({
    queryKey: ["course", selectedId],
    queryFn: () => api<Course>(`/courses/${selectedId}`),
    enabled: selectedId !== null,
  });

  // One call, not a hand-kept list: these three views each maintained their own
  // and they had already drifted apart — only this one invalidated grade history,
  // so editing a student left it stale on the other two.
  const refresh = () => queryClient.invalidateQueries();

  const create = useMutation({
    mutationFn: (body: CourseCreate) => api<Course>("/courses", { method: "POST", body }),
    onSuccess: (course) => {
      setCreating(false);
      setCode(null);
      setNotice(t("course.created"));
      select(course.course_id);
      void refresh();
    },
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  function createCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const credits = parseLocaleNumber(String(data.get("credits") ?? ""), locale);
    const maxGrade = parseLocaleNumber(String(data.get("max_grade") ?? ""), locale);
    const passingGrade = parseLocaleNumber(String(data.get("passing_grade") ?? ""), locale);
    const maxStudents = Number(data.get("max_students"));
    const teacherText = String(data.get("teacher_id") ?? "").trim();
    const teacherId = teacherText ? Number(teacherText) : null;
    const assessments = readCourseAssessments(data, locale);
    if (
      credits === null ||
      maxGrade === null ||
      passingGrade === null ||
      assessments === null ||
      !Number.isInteger(maxStudents) ||
      maxStudents < 1 ||
      (teacherId !== null && (!Number.isInteger(teacherId) || teacherId < 1))
    ) {
      setCode("VALIDATION_ERROR");
      return;
    }

    setCode(null);
    setNotice(null);
    create.mutate({
      course_id: String(data.get("course_id") ?? "").trim(),
      name: String(data.get("name") ?? "").trim(),
      term: String(data.get("term") ?? "").trim() || null,
      credits,
      max_students: maxStudents,
      max_grade: maxGrade,
      passing_grade: passingGrade,
      teacher_id: teacherId,
      status: data.get("status") === "archived" ? "archived" : "active",
      start_date: String(data.get("start_date") ?? "") || null,
      end_date: String(data.get("end_date") ?? "") || null,
      department: String(data.get("department") ?? "").trim() || null,
      room: String(data.get("room") ?? "").trim() || null,
      schedule: String(data.get("schedule") ?? "").trim() || null,
      description: String(data.get("description") ?? "").trim() || null,
      prerequisite_ids: data.getAll("prerequisite_ids").map(String),
      assessments,
    });
  }

  const rows = list.data?.items ?? [];

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          {t("course.other")}
          {list.data && (
            <span className="numeric ms-3 text-base font-normal text-subtle">
              {formatNumber(list.data.total, locale)}
            </span>
          )}
        </h1>

        <div className="flex flex-wrap items-center gap-2">
          {can.createCourse(me) && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setCode(null);
                setCreating(true);
              }}
            >
              {t("course.add")}
            </button>
          )}
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("action.search")}
            aria-label={t("action.search")}
            className="w-56 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          />
        </div>
      </div>

      {notice && (
        <p role="status" className="mb-4 rounded-lg bg-pass-bg px-3 py-2 text-sm text-pass">
          {notice}
        </p>
      )}

      {creating && (
        <Modal
          open
          title={t("course.createTitle")}
          onClose={() => {
            if (!create.isPending) {
              setCreating(false);
              setCode(null);
            }
          }}
        >
          {allCourses.isPending && <p className="text-sm text-subtle">{t("stats.loading")}</p>}
          {allCourses.error && (
            <FormError>
              {t(`error.${allCourses.error instanceof ApiError ? allCourses.error.code : "NETWORK_ERROR"}` as "error.unknown")}
            </FormError>
          )}
          {/* Same reason as the roster in `bulk-grades.tsx`: the dialog caps and
              scrolls itself, so capping again here just nests two scrollbars. */}
          {allCourses.isSuccess ? (
            <form onSubmit={createCourse} className="space-y-4">
              <CourseFields courses={allCourses.data.items} me={me} locale={locale} includeId />
              {code && <FormError>{t(`error.${code}` as "error.unknown")}</FormError>}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={create.isPending}
                  onClick={() => {
                    setCreating(false);
                    setCode(null);
                  }}
                >
                  {t("action.cancel")}
                </button>
                <button type="submit" className="btn btn-primary" disabled={create.isPending}>
                  {t("action.save")}
                </button>
              </div>
            </form>
          ) : (
            <div className="flex justify-end pt-4">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setCreating(false);
                  setCode(null);
                }}
              >
                {t("action.cancel")}
              </button>
            </div>
          )}
        </Modal>
      )}

      <MasterDetail
        detailKey={creating ? null : selectedId}
        detail={
          !creating && selectedId && (
            <CourseDetail
              key={selectedId}
              courseId={selectedId}
              course={detail.data}
              courses={allCourses.data?.items ?? []}
              coursesReady={allCourses.isSuccess}
              coursesLoading={allCourses.isPending}
              coursesError={allCourses.error}
              loading={detail.isPending}
              error={detail.error}
              me={me}
              locale={locale}
              onClose={() => select(null)}
              onSaved={refresh}
              onDeleted={() => {
                setNotice(t("course.deleted"));
                select(null);
                void refresh();
              }}
            />
          )
        }
      >
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("course.other")}</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-subtle">
                <th scope="col" className="px-4 py-2.5 font-medium">{t("course.id")}</th>
                <th scope="col" className="px-4 py-2.5 font-medium">{t("course.one")}</th>
                <th scope="col" className="px-4 py-2.5 font-medium">{t("course.status")}</th>
                <th scope="col" className="px-4 py-2.5 text-end font-medium">{t("enrollment.enrolled")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((course) => {
                const active = course.course_id === selectedId;
                return (
                  <tr key={course.course_id} className={`border-b border-line last:border-0 transition-colors ${active ? "bg-bg-subtle" : "hover:bg-bg-subtle"}`}>
                    <td className="px-4 py-0">
                      <button
                        type="button"
                        onClick={() => select(course.course_id)}
                        aria-current={active ? "true" : undefined}
                        className="numeric -mx-4 w-[calc(100%+2rem)] px-4 py-2.5 text-start text-muted outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
                      >
                        {course.course_id}
                      </button>
                    </td>
                    <td className="px-4 py-2.5 text-text">{course.name}</td>
                    <td className="px-4 py-2.5">
                      <span className={`badge ${course.status === "active" ? "badge-pass" : "badge-warn"}`}>
                        {t(`course.statusValue.${course.status}`)}
                      </span>
                    </td>
                    <td className="numeric px-4 py-2.5 text-end text-muted">
                      {formatNumber(course.enrolled_count, locale)}
                      <span className="text-subtle"> / {formatNumber(course.max_students, locale)}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {list.isPending && (
            <p className="px-4 py-8 text-center text-sm text-subtle">{t("stats.loading")}</p>
          )}
          {!list.isPending && rows.length === 0 && (
            <p className="px-4 py-8 text-center text-sm text-subtle">{t("stats.noData")}</p>
          )}
          <Pager
            page={page}
            size={PAGE_SIZE}
            total={list.data?.total ?? 0}
            locale={locale}
            labels={{
              previous: t("pager.previous"),
              next: t("pager.next"),
              status: (current, pages) => t("pager.page", { page: current, pages }),
            }}
            onPage={(next) => setPage(String(next))}
          />
        </div>
      </MasterDetail>
    </>
  );
}

/**
 * Who owns the course.
 *
 * This was a bare number input asking for a user id, so assigning a course meant
 * knowing an integer by heart, and a wrong one was accepted silently — the course
 * then never appeared for the person it named, because `course_scope` matches on a
 * teacher id that would never be theirs. The API validates the id now; this makes a
 * wrong one hard to pick in the first place.
 *
 * Rendered only for administrators, which is also who may call this endpoint. A
 * teacher creating a course is given it by default and needs no control at all.
 */
function TeacherPicker({ course }: { course?: Course }) {
  const t = useTranslations();

  const teachers = useQuery({
    queryKey: ["admin", "users", { role: "teacher" }],
    queryFn: () =>
      api<Accounts>("/admin/users", { query: { role: "teacher", include_inactive: false } }),
    staleTime: 60_000,
  });

  const options = teachers.data ?? [];
  // A course whose teacher has since been deactivated still has to render its own
  // value, or opening the form would quietly reassign it on save.
  const orphaned =
    course?.teacher_id && !options.some((row) => row.id === course.teacher_id)
      ? course.teacher_id
      : null;

  return (
    <Select
      name="teacher_id"
      label={t("course.teacher")}
      value={course?.teacher_id ? String(course.teacher_id) : ""}
      required={false}
    >
      <option value="">{t("course.noTeacher")}</option>
      {orphaned !== null && <option value={String(orphaned)}>{course?.teacher_name ?? orphaned}</option>}
      {options.map((teacher) => (
        <option key={teacher.id} value={String(teacher.id)}>
          {teacher.full_name}
        </option>
      ))}
    </Select>
  );
}

function CourseFields({
  course,
  courses,
  me,
  locale,
  includeId = false,
}: {
  course?: Course;
  courses: Course[];
  me: Me;
  locale: string;
  includeId?: boolean;
}) {
  const t = useTranslations();
  const missingPrerequisites = (course?.prerequisite_ids ?? []).filter(
    (id) => !courses.some((candidate) => candidate.course_id === id),
  );
  const [assessments, setAssessments] = useState(
    (course?.assessments ?? []).map((assessment) => ({
      name: assessment.name,
      // Full precision: these seed an editable field, and the two-digit display
      // cap rewrote the stored weight on any save that did not touch it.
      weight: formatNumberForInput(assessment.weight, locale),
    })),
  );
  return (
    <>
      {includeId && <Input name="course_id" label={t("course.id")} value="" />}
      <Input name="name" label={t("course.name")} value={course?.name ?? ""} />
      <Input name="term" label={t("course.term")} value={course?.term ?? ""} required={false} />
      <Input
        name="credits"
        label={t("course.credits")}
        value={course ? formatNumberForInput(course.credits, locale) : "1"}
        inputMode="decimal"
        help={t("course.creditsHelp")}
      />
      <Input name="max_students" label={t("course.maxStudents")} value={String(course?.max_students ?? 30)} type="number" inputMode="numeric" />
      <Input name="max_grade" label={t("course.maxGrade")} value={course ? formatNumberForInput(course.max_grade, locale) : "100"} inputMode="decimal" />
      <Input name="passing_grade" label={t("course.passingGrade")} value={course ? formatNumberForInput(course.passing_grade, locale) : "60"} inputMode="decimal" />
      {can.writeStudent(me) && <TeacherPicker course={course} />}
      <Select name="status" label={t("course.status")} value={course?.status ?? "active"}>
        <option value="active">{t("course.statusValue.active")}</option>
        <option value="archived">{t("course.statusValue.archived")}</option>
      </Select>
      <Input name="start_date" label={t("course.startDate")} value={course?.start_date ?? ""} type="date" required={false} />
      <Input name="end_date" label={t("course.endDate")} value={course?.end_date ?? ""} type="date" required={false} />
      <Input name="department" label={t("course.department")} value={course?.department ?? ""} required={false} />
      <Input name="room" label={t("course.room")} value={course?.room ?? ""} required={false} />
      <Input name="schedule" label={t("course.schedule")} value={course?.schedule ?? ""} required={false} />
      <Textarea name="description" label={t("course.description")} value={course?.description ?? ""} required={false} />
      <fieldset>
        <legend className="text-sm font-medium text-text">{t("course.assessments")}</legend>
        <p className="mt-1 text-xs text-subtle">{t("course.assessmentsHint")}</p>
        <div className="mt-3 space-y-3">
          {assessments.map((assessment, index) => (
            <div
              key={index}
              className="grid gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
            >
              <label className="text-sm text-muted">
                {t("grade.title")}
                <input
                  name="assessment_names"
                  value={assessment.name}
                  className="field-input"
                  onChange={(event) =>
                    setAssessments((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index ? { ...item, name: event.target.value } : item,
                      ),
                    )
                  }
                />
              </label>
              <label className="text-sm text-muted">
                {t("grade.weight")}
                <input
                  name="assessment_weights"
                  value={assessment.weight}
                  inputMode="decimal"
                  className="field-input numeric"
                  onChange={(event) =>
                    setAssessments((current) =>
                      current.map((item, itemIndex) =>
                        itemIndex === index ? { ...item, weight: event.target.value } : item,
                      ),
                    )
                  }
                />
              </label>
              <button
                type="button"
                className="btn btn-ghost px-2 text-fail"
                aria-label={t("action.remove")}
                onClick={() =>
                  setAssessments((current) =>
                    current.filter((_, itemIndex) => itemIndex !== index),
                  )
                }
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          className="btn mt-3"
          onClick={() =>
            setAssessments((current) => [
              ...current,
              { name: "", weight: formatNumber(1, locale) },
            ])
          }
        >
          {t("course.addAssessment")}
        </button>
      </fieldset>
      <div>
        <label htmlFor="prerequisite_ids" className="block text-sm text-muted">{t("course.prerequisites")}</label>
        <select
          id="prerequisite_ids"
          name="prerequisite_ids"
          multiple
          defaultValue={course?.prerequisite_ids ?? []}
          aria-describedby="prerequisite_ids-hint"
          className="field-input min-h-28"
        >
          {missingPrerequisites.map((id) => <option key={id} value={id}>{id}</option>)}
          {courses.filter((candidate) => candidate.course_id !== course?.course_id).map((candidate) => (
            <option key={candidate.course_id} value={candidate.course_id}>{candidate.course_id} — {candidate.name}</option>
          ))}
        </select>
        <p id="prerequisite_ids-hint" className="mt-1 text-xs text-subtle">{t("course.prerequisitesHint")}</p>
      </div>
    </>
  );
}

function CourseDetail({
  courseId,
  course,
  courses,
  coursesReady,
  coursesLoading,
  coursesError,
  loading,
  error,
  me,
  locale,
  onClose,
  onSaved,
  onDeleted,
}: {
  courseId: string;
  course: Course | undefined;
  courses: Course[];
  coursesReady: boolean;
  coursesLoading: boolean;
  coursesError: unknown;
  loading: boolean;
  error: unknown;
  me: Me;
  locale: string;
  onClose: () => void;
  onSaved: () => void | Promise<unknown>;
  onDeleted: () => void;
}) {
  const t = useTranslations();
  const editable = course !== undefined && can.writeCourse(me, course);
  const manageable = course !== undefined && can.writeEnrolment(me, course);
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [studentSearch, setStudentSearch] = useState("");
  const studentQuery = useDebounced(studentSearch.trim());
  const studentSearchUnsettled = studentQuery !== studentSearch.trim();
  const [enrollmentAction, setEnrollmentAction] = useState<{
    kind: Exclude<EnrollmentAction, "enroll">;
    studentId: string;
    studentName: string;
  } | null>(null);

  const register = useQuery({
    queryKey: ["course", courseId, "enrollments"],
    queryFn: () => api<Register>(`/courses/${courseId}/enrollments`),
    enabled: !editing,
  });

  const students = useQuery({
    queryKey: ["students", { q: studentQuery, enrollmentCourse: courseId }],
    queryFn: () => api<StudentPage>("/students", { query: { q: studentQuery, size: 20 } }),
    enabled: manageable && register.isSuccess && !editing && studentQuery.length >= 2,
  });

  const save = useMutation({
    mutationFn: (body: CourseUpdate) => api(`/courses/${courseId}`, { method: "PATCH", body }),
    onSuccess: () => {
      setEditing(false);
      setCode(null);
      setNotice(t("course.saved"));
      void onSaved();
    },
    onError: (err) => setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR"),
  });

  const removeCourse = useMutation({
    mutationFn: () => api(`/courses/${courseId}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleting(false);
      onDeleted();
    },
    onError: (err) => {
      setDeleting(false);
      setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR");
    },
  });

  const enrollment = useMutation({
    mutationFn: ({ kind, studentId }: { kind: EnrollmentAction; studentId: string }) => {
      const path = `/courses/${courseId}/enrollments/${studentId}`;
      if (kind === "enroll") {
        return api(`/courses/${courseId}/enrollments`, { method: "POST", body: { student_id: studentId } });
      }
      if (kind === "withdraw") return api(path, { method: "PATCH", body: { status: "withdrawn" } });
      // Completion is what a prerequisite is checked against, so this button is the
      // only thing that can ever satisfy one. Withdrawn is leaving; completed is
      // finishing, and the register had a word for only the first.
      if (kind === "complete") return api(path, { method: "PATCH", body: { status: "completed" } });
      return api(path, { method: "DELETE" });
    },
    onSuccess: (_, action) => {
      setEnrollmentAction(null);
      setCode(null);
      setNotice(t(`enrollment.${action.kind}Success` as "enrollment.enrollSuccess"));
      if (action.kind === "enroll") setStudentSearch("");
      void onSaved();
    },
    onError: (err) => {
      setEnrollmentAction(null);
      setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR");
    },
  });

  function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!coursesReady) return;
    const data = new FormData(event.currentTarget);
    const credits = parseLocaleNumber(String(data.get("credits") ?? ""), locale);
    const maxGrade = parseLocaleNumber(String(data.get("max_grade") ?? ""), locale);
    const passingGrade = parseLocaleNumber(String(data.get("passing_grade") ?? ""), locale);
    const maxStudents = Number(data.get("max_students"));
    const teacherText = String(data.get("teacher_id") ?? "").trim();
    // `has` rather than a truthiness check on the value: the picker is rendered for
    // administrators only, so for a teacher editing their own course the field is
    // absent and must mean "unchanged". Reading an absent field as empty would
    // orphan the course the moment its owner edited anything on it. An empty value
    // from a present picker is the Unassigned option, and does mean null.
    const teacherId = data.has("teacher_id")
      ? teacherText
        ? Number(teacherText)
        : null
      : (course?.teacher_id ?? null);
    const assessments = readCourseAssessments(data, locale);
    if (
      credits === null ||
      maxGrade === null ||
      passingGrade === null ||
      assessments === null ||
      !Number.isInteger(maxStudents) ||
      maxStudents < 1 ||
      (teacherId !== null && (!Number.isInteger(teacherId) || teacherId < 1))
    ) {
      setCode("VALIDATION_ERROR");
      return;
    }

    setCode(null);
    setNotice(null);
    save.mutate({
      name: String(data.get("name") ?? "").trim(),
      term: String(data.get("term") ?? "").trim() || null,
      credits,
      max_students: maxStudents,
      max_grade: maxGrade,
      passing_grade: passingGrade,
      teacher_id: teacherId,
      status: data.get("status") === "archived" ? "archived" : "active",
      start_date: String(data.get("start_date") ?? "") || null,
      end_date: String(data.get("end_date") ?? "") || null,
      department: String(data.get("department") ?? "").trim() || null,
      room: String(data.get("room") ?? "").trim() || null,
      schedule: String(data.get("schedule") ?? "").trim() || null,
      description: String(data.get("description") ?? "").trim() || null,
      prerequisite_ids: data.getAll("prerequisite_ids").map(String),
      assessments,
    });
  }

  function submitEnrollment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const studentId = String(new FormData(event.currentTarget).get("student_id") ?? "");
    if (!studentSearchUnsettled && studentId) enrollment.mutate({ kind: "enroll", studentId });
  }

  const registeredIds = new Set((register.data ?? []).map((entry) => entry.student_id));
  const candidates = studentSearchUnsettled
    ? []
    : (students.data?.items ?? []).filter(
        (student) => student.is_active && !registeredIds.has(student.student_id),
      );

  return (
    <div className="rounded-xl border border-line bg-surface p-6">
      <PanelHeader title={course?.name ?? t("stats.loading")} subtitle={course?.course_id} closeLabel={t("action.close")} onClose={onClose} />
      {loading && <p className="mt-4 text-sm text-subtle">{t("stats.loading")}</p>}
      {error instanceof ApiError && <FormError>{t(`error.${error.code}` as "error.unknown")}</FormError>}
      {notice && <p role="status" className="mt-4 text-sm text-pass">{notice}</p>}
      {code && !editing && <FormError>{t(`error.${code}` as "error.unknown")}</FormError>}

      {course && !editing && (
        <>
          <dl className="mt-6 space-y-3 text-sm">
            <Field label={t("course.term")} value={course.term ?? "—"} />
            <Field label={t("course.credits")} value={formatNumber(course.credits, locale)} numeric />
            <Field label={t("course.maxStudents")} value={formatNumber(course.max_students, locale)} numeric />
            <Field label={t("course.maxGrade")} value={formatNumber(course.max_grade, locale)} numeric />
            <Field label={t("course.passingGrade")} value={formatNumber(course.passing_grade, locale)} numeric />
            <Field label={t("course.teacher")} value={course.teacher_name ?? "—"} />
            <Field label={t("course.status")} value={t(`course.statusValue.${course.status}`)} />
            <Field label={t("course.startDate")} value={formatDate(course.start_date, locale)} />
            <Field label={t("course.endDate")} value={formatDate(course.end_date, locale)} />
            <Field label={t("course.department")} value={course.department ?? "—"} />
            <Field label={t("course.room")} value={course.room ?? "—"} />
            <Field label={t("course.schedule")} value={course.schedule ?? "—"} />
            <Field label={t("course.description")} value={course.description ?? "—"} />
            <Field label={t("course.prerequisites")} value={course.prerequisite_ids?.join(", ") || "—"} />
          </dl>

          {editable && (
            <>
              <div className="mt-6 flex flex-wrap gap-2">
                {coursesReady && (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setCode(null);
                      setEditing(true);
                    }}
                  >
                    {t("action.edit")}
                  </button>
                )}
                <button type="button" className="btn btn-danger" onClick={() => setDeleting(true)}>{t("action.delete")}</button>
              </div>
              {coursesLoading && <p className="mt-3 text-sm text-subtle">{t("stats.loading")}</p>}
              {Boolean(coursesError) && (
                <FormError>
                  {t(`error.${coursesError instanceof ApiError ? coursesError.code : "NETWORK_ERROR"}` as "error.unknown")}
                </FormError>
              )}
            </>
          )}

          <h3 className="mt-8 text-sm font-medium text-text">{t("enrollment.other")}</h3>
          {register.isPending && <p className="mt-3 text-sm text-subtle">{t("stats.loading")}</p>}
          {register.error && (
            <FormError>
              {t(`error.${register.error instanceof ApiError ? register.error.code : "NETWORK_ERROR"}` as "error.unknown")}
            </FormError>
          )}
          {register.isSuccess && (
            <>
              {manageable && (
                <div className="mt-3 rounded-lg border border-line p-3">
                  <label htmlFor={`student-search-${courseId}`} className="block text-sm text-muted">
                    {t("enrollment.searchStudents")}
                  </label>
                  <input
                    id={`student-search-${courseId}`}
                    type="search"
                    value={studentSearch}
                    onChange={(event) => setStudentSearch(event.target.value)}
                    className="field-input"
                    aria-describedby={`student-search-${courseId}-hint`}
                  />
                  <p id={`student-search-${courseId}-hint`} className="mt-1 text-xs text-subtle">
                    {t("enrollment.searchHint")}
                  </p>
                  {studentQuery.length >= 2 && students.isPending && (
                    <p className="mt-3 text-sm text-subtle">{t("stats.loading")}</p>
                  )}
                  {students.error && (
                    <FormError>
                      {t(`error.${students.error instanceof ApiError ? students.error.code : "NETWORK_ERROR"}` as "error.unknown")}
                    </FormError>
                  )}
                  {!studentSearchUnsettled && studentQuery.length >= 2 && students.isSuccess && candidates.length > 0 && (
                    <form onSubmit={submitEnrollment} className="mt-3 flex items-end gap-2">
                      <div className="min-w-0 flex-1">
                        <Select name="student_id" label={t("enrollment.student")} value={candidates[0].student_id}>
                          {candidates.map((student) => (
                            <option key={student.student_id} value={student.student_id}>
                              {student.student_id} — {student.first_name} {student.last_name}
                            </option>
                          ))}
                        </Select>
                      </div>
                      <button type="submit" className="btn btn-primary" disabled={enrollment.isPending || studentSearchUnsettled}>{t("action.enroll")}</button>
                    </form>
                  )}
                  {!studentSearchUnsettled && studentQuery.length >= 2 && students.isSuccess && candidates.length === 0 && (
                    <p className="mt-3 text-sm text-subtle">{t("enrollment.noStudents")}</p>
                  )}
                </div>
              )}

              <ul className="mt-3 divide-y divide-line rounded-lg border border-line">
                {register.data.map((entry) => {
                  const studentName = `${entry.first_name ?? ""} ${entry.last_name ?? ""}`.trim() || entry.student_id;
                  return (
                    <li key={entry.student_id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm">
                      <span className="min-w-0 truncate text-text">{studentName}</span>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`badge ${entry.status === "active" ? "badge-pass" : entry.status === "withdrawn" ? "badge-warn" : ""}`}>
                          {t(`enrollment.status.${entry.status}` as "enrollment.status.active")}
                        </span>
                        <span className="numeric text-xs text-subtle">
                          {entry.grade_count > 0 ? `${formatNumber(entry.grade_count, locale)} ${t("grade.other")}` : t("enrollment.notAssessed")}
                        </span>
                        {manageable && entry.status === "active" && (
                          <>
                            <button type="button" className="btn btn-ghost" onClick={() => setEnrollmentAction({ kind: "complete", studentId: entry.student_id, studentName })}>{t("action.complete")}</button>
                            <button type="button" className="btn btn-ghost" onClick={() => setEnrollmentAction({ kind: "withdraw", studentId: entry.student_id, studentName })}>{t("action.withdraw")}</button>
                          </>
                        )}
                        {manageable && (
                          <button type="button" className="btn btn-danger" onClick={() => setEnrollmentAction({ kind: "remove", studentId: entry.student_id, studentName })}>{t("action.remove")}</button>
                        )}
                      </div>
                    </li>
                  );
                })}
                {register.data.length === 0 && <li className="px-3 py-4 text-center text-sm text-subtle">{t("stats.noData")}</li>}
              </ul>
            </>
          )}

          <InsightBlock entityType="course" entityId={courseId} />
          <NotesBlock entityType="course" entityId={courseId} me={me} locale={locale} />
        </>
      )}

      {course && editing && (
        <form onSubmit={submitEdit} className="mt-6 space-y-4">
          <CourseFields course={course} courses={courses} me={me} locale={locale} />
          {coursesLoading && <p className="text-sm text-subtle">{t("stats.loading")}</p>}
          {Boolean(coursesError) && (
            <FormError>
              {t(`error.${coursesError instanceof ApiError ? coursesError.code : "NETWORK_ERROR"}` as "error.unknown")}
            </FormError>
          )}
          {code && <FormError>{t(`error.${code}` as "error.unknown")}</FormError>}
          <div className="flex gap-2">
            <button type="submit" disabled={save.isPending || !coursesReady} className="btn btn-primary">{t("action.save")}</button>
            <button type="button" className="btn btn-ghost" onClick={() => { setEditing(false); setCode(null); }}>{t("action.cancel")}</button>
          </div>
        </form>
      )}

      <Confirm
        open={deleting}
        title={t("course.deleteTitle")}
        description={t("course.deleteDescription")}
        confirmLabel={t("action.delete")}
        cancelLabel={t("action.cancel")}
        onConfirm={() => removeCourse.mutateAsync().then(() => undefined).catch(() => undefined)}
        onCancel={() => setDeleting(false)}
      />
      <Confirm
        open={enrollmentAction !== null}
        title={t(`enrollment.${enrollmentAction?.kind ?? "withdraw"}Title` as "enrollment.withdrawTitle")}
        description={t(
          `enrollment.${enrollmentAction?.kind ?? "withdraw"}StudentDescription` as "enrollment.withdrawStudentDescription",
          { student: enrollmentAction?.studentName ?? "" },
        )}
        confirmLabel={t(`action.${enrollmentAction?.kind ?? "withdraw"}` as "action.withdraw")}
        cancelLabel={t("action.cancel")}
        onConfirm={() => enrollmentAction ? enrollment.mutateAsync(enrollmentAction).then(() => undefined).catch(() => undefined) : undefined}
        onCancel={() => setEnrollmentAction(null)}
      />
    </div>
  );
}
