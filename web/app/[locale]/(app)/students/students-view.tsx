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
} from "@/components/app/detail-fields";
import { InsightBlock } from "@/components/app/insight";
import { MasterDetail } from "@/components/app/master-detail";
import { NotesBlock } from "@/components/app/notes";
import { Pager } from "@/components/app/pager";
import { StudentRecord } from "@/components/app/student-record";
import { Confirm } from "@/components/ui/confirm";
import { Modal } from "@/components/ui/modal";
import { Link } from "@/i18n/navigation";
import { api, ApiError, type Response } from "@/lib/api";
import type { paths } from "@/lib/api-schema";
import { formatDate, formatNumber } from "@/lib/format";
import { can } from "@/lib/permissions";
import type { Me } from "@/lib/session";
import { useDebounced, useSelection, useUrlParam } from "@/lib/use-selection";

type Student = Response<"/students/{student_id}", "get">;
type StudentPage = Response<"/students", "get">;
type StudentReport = Response<"/reports/student/{student_id}", "get">;
type StudentCourses = Response<"/students/{student_id}/courses", "get">;
type CoursePage = Response<"/courses", "get">;
type Course = Response<"/courses/{course_id}", "get">;
type StudentCreate = paths["/students"]["post"]["requestBody"]["content"]["application/json"];
type StudentUpdate = paths["/students/{student_id}"]["patch"]["requestBody"]["content"]["application/json"];

const PAGE_SIZE = 50;

export function StudentsView({ me, locale }: { me: Me; locale: string }) {
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
  const editable = can.writeStudent(me);

  const list = useQuery({
    queryKey: ["students", { q: query, page }],
    queryFn: () =>
      api<StudentPage>("/students", { query: { q: query, page, size: PAGE_SIZE } }),
    placeholderData: (previous) => previous,
  });

  const detail = useQuery({
    queryKey: ["student", selectedId],
    queryFn: () => api<Student>(`/students/${selectedId}`),
    enabled: selectedId !== null,
  });

  const courses = useQuery({
    queryKey: ["courses", "management"],
    queryFn: () => api<CoursePage>("/courses", { query: { size: 200 } }),
    enabled: can.createCourse(me),
  });

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["students"] }),
      queryClient.invalidateQueries({ queryKey: ["student"] }),
      queryClient.invalidateQueries({ queryKey: ["report"] }),
      queryClient.invalidateQueries({ queryKey: ["reports"] }),
      queryClient.invalidateQueries({ queryKey: ["courses"] }),
      queryClient.invalidateQueries({ queryKey: ["course"] }),
      queryClient.invalidateQueries({ queryKey: ["grades"] }),
      queryClient.invalidateQueries({ queryKey: ["grade"] }),
      queryClient.invalidateQueries({ queryKey: ["analytics"] }),
      queryClient.invalidateQueries({ queryKey: ["palette"] }),
    ]);

  const create = useMutation({
    mutationFn: (body: StudentCreate) => api<Student>("/students", { method: "POST", body }),
    onSuccess: (student) => {
      setCreating(false);
      setCode(null);
      setNotice(t("student.created"));
      select(student.student_id);
      void refresh();
    },
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  function createStudent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setCode(null);
    setNotice(null);
    create.mutate({
      student_id: String(data.get("student_id") ?? "").trim(),
      first_name: String(data.get("first_name") ?? "").trim(),
      last_name: String(data.get("last_name") ?? "").trim(),
      email: String(data.get("email") ?? "").trim(),
      date_of_birth: String(data.get("date_of_birth") ?? "") || null,
      phone: String(data.get("phone") ?? "").trim() || null,
      cohort: String(data.get("cohort") ?? "").trim() || null,
      is_active: data.get("is_active") === "true",
    });
  }

  const rows = list.data?.items ?? [];

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          {t("student.other")}
          {list.data && (
            <span className="numeric ms-3 text-base font-normal text-subtle">
              {formatNumber(list.data.total, locale)}
            </span>
          )}
        </h1>

        <div className="flex flex-wrap items-center gap-2">
          {editable && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setCode(null);
                setCreating(true);
              }}
            >
              {t("student.add")}
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
          title={t("student.createTitle")}
          onClose={() => {
            if (!create.isPending) {
              setCreating(false);
              setCode(null);
            }
          }}
        >
          <form onSubmit={createStudent} className="space-y-4">
            <StudentFields includeId includeActive />
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
        </Modal>
      )}

      <MasterDetail
        detailKey={creating ? null : selectedId}
        detail={
          !creating && selectedId && (
            <StudentDetail
              key={selectedId}
              student={detail.data}
              loading={detail.isPending}
              error={detail.error}
              editable={editable}
              me={me}
              courses={courses.data?.items ?? []}
              coursesReady={courses.isSuccess}
              coursesLoading={courses.isPending}
              coursesError={courses.error}
              locale={locale}
              onClose={() => select(null)}
              onSaved={refresh}
              onDeleted={() => {
                setNotice(t("student.deleted"));
                select(null);
                void refresh();
              }}
            />
          )
        }
      >
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("student.other")}</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-subtle">
                <th scope="col" className="px-4 py-2.5 font-medium">{t("student.id")}</th>
                <th scope="col" className="px-4 py-2.5 font-medium">{t("student.one")}</th>
                <th scope="col" className="px-4 py-2.5 font-medium">{t("student.status")}</th>
                <th scope="col" className="px-4 py-2.5 text-end font-medium">{t("grade.other")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((student) => {
                const active = student.student_id === selectedId;
                return (
                  <tr
                    key={student.student_id}
                    className={`border-b border-line last:border-0 transition-colors ${active ? "bg-bg-subtle" : "hover:bg-bg-subtle"}`}
                  >
                    <td className="px-4 py-0">
                      <button
                        type="button"
                        onClick={() => select(student.student_id)}
                        aria-current={active ? "true" : undefined}
                        className="numeric -mx-4 w-[calc(100%+2rem)] px-4 py-2.5 text-start text-muted outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
                      >
                        {student.student_id}
                      </button>
                    </td>
                    <td className="px-4 py-2.5 text-text">{student.first_name} {student.last_name}</td>
                    <td className="px-4 py-2.5">
                      <span className={`badge ${student.is_active ? "badge-pass" : "badge-warn"}`}>
                        {t(student.is_active ? "student.active" : "student.inactive")}
                      </span>
                    </td>
                    <td className="numeric px-4 py-2.5 text-end text-muted">
                      {formatNumber(student.grade_count, locale)}
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

function StudentFields({
  student,
  includeId = false,
  includeActive = false,
}: {
  student?: Student;
  includeId?: boolean;
  includeActive?: boolean;
}) {
  const t = useTranslations();
  return (
    <>
      {includeId && <Input name="student_id" label={t("student.id")} value="" />}
      <Input name="first_name" label={t("student.firstName")} value={student?.first_name ?? ""} />
      <Input name="last_name" label={t("student.lastName")} value={student?.last_name ?? ""} />
      <Input name="email" label={t("auth.email")} value={student?.email ?? ""} type="email" />
      <Input
        name="date_of_birth"
        label={t("student.dateOfBirth")}
        value={student?.date_of_birth ?? ""}
        type="date"
        required={false}
      />
      <Input name="phone" label={t("student.phone")} value={student?.phone ?? ""} required={false} />
      <Input name="cohort" label={t("student.cohort")} value={student?.cohort ?? ""} required={false} />
      {includeActive && (
        <Select name="is_active" label={t("student.status")} value="true">
          <option value="true">{t("student.active")}</option>
          <option value="false">{t("student.inactive")}</option>
        </Select>
      )}
    </>
  );
}

function StudentDetail({
  student,
  loading,
  error,
  editable,
  me,
  courses,
  coursesReady,
  coursesLoading,
  coursesError,
  locale,
  onClose,
  onSaved,
  onDeleted,
}: {
  student: Student | undefined;
  loading: boolean;
  error: unknown;
  editable: boolean;
  me: Me;
  courses: Course[];
  coursesReady: boolean;
  coursesLoading: boolean;
  coursesError: unknown;
  locale: string;
  onClose: () => void;
  onSaved: () => void | Promise<unknown>;
  onDeleted: () => void;
}) {
  const t = useTranslations();
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deactivating, setDeactivating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [enrollmentAction, setEnrollmentAction] = useState<{
    kind: "withdraw" | "remove";
    courseId: string;
    courseName: string;
  } | null>(null);
  const studentId = student?.student_id;

  const record = useQuery({
    queryKey: ["report", "student", studentId],
    queryFn: () => api<StudentReport>(`/reports/student/${studentId}`),
    enabled: Boolean(studentId) && !editing,
  });

  const enrolled = useQuery({
    queryKey: ["student", studentId, "courses"],
    queryFn: () => api<StudentCourses>(`/students/${studentId}/courses`),
    enabled: Boolean(studentId) && !editing,
  });

  const save = useMutation({
    mutationFn: (body: Omit<StudentUpdate, "is_active">) =>
      api(`/students/${studentId}`, { method: "PATCH", body }),
    onSuccess: () => {
      setEditing(false);
      setCode(null);
      setNotice(t("student.saved"));
      void onSaved();
    },
    onError: (err) => setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR"),
  });

  const lifecycle = useMutation({
    mutationFn: (active: boolean) =>
      api(`/students/${studentId}`, { method: "PATCH", body: { is_active: active } }),
    onSuccess: (_, active) => {
      setDeactivating(false);
      setCode(null);
      setNotice(t(active ? "student.activated" : "student.deactivated"));
      void onSaved();
    },
    onError: (err) => {
      setDeactivating(false);
      setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR");
    },
  });

  const removeStudent = useMutation({
    mutationFn: () => api(`/students/${studentId}`, { method: "DELETE" }),
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
    mutationFn: ({ kind, courseId }: { kind: "enroll" | "withdraw" | "remove"; courseId: string }) => {
      const path = `/courses/${courseId}/enrollments/${studentId}`;
      if (kind === "enroll") {
        return api(`/courses/${courseId}/enrollments`, {
          method: "POST",
          body: { student_id: studentId },
        });
      }
      if (kind === "withdraw") return api(path, { method: "PATCH", body: { status: "withdrawn" } });
      return api(path, { method: "DELETE" });
    },
    onSuccess: (_, action) => {
      setEnrollmentAction(null);
      setCode(null);
      setNotice(t(`enrollment.${action.kind}Success` as "enrollment.enrollSuccess"));
      void onSaved();
    },
    onError: (err) => {
      setEnrollmentAction(null);
      setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR");
    },
  });

  function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!student) return;
    const data = new FormData(event.currentTarget);
    setCode(null);
    setNotice(null);
    save.mutate({
      first_name: String(data.get("first_name") ?? "").trim(),
      last_name: String(data.get("last_name") ?? "").trim(),
      email: String(data.get("email") ?? "").trim(),
      date_of_birth: String(data.get("date_of_birth") ?? "") || null,
      phone: String(data.get("phone") ?? "").trim() || null,
      cohort: String(data.get("cohort") ?? "").trim() || null,
    });
  }

  function submitEnrollment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const courseId = String(new FormData(event.currentTarget).get("course_id") ?? "");
    if (courseId) enrollment.mutate({ kind: "enroll", courseId });
  }

  const manageableCourses = courses.filter((course) => can.writeEnrolment(me, course));
  const enrolledIds = new Set((enrolled.data ?? []).map((course) => course.course_id));
  const availableCourses = manageableCourses.filter((course) => !enrolledIds.has(course.course_id));

  return (
    <div className="rounded-xl border border-line bg-surface p-6">
      <PanelHeader
        title={student ? `${student.first_name} ${student.last_name}` : t("stats.loading")}
        subtitle={student?.student_id}
        closeLabel={t("action.close")}
        onClose={onClose}
      />

      {loading && <p className="mt-4 text-sm text-subtle">{t("stats.loading")}</p>}
      {error instanceof ApiError && <FormError>{t(`error.${error.code}` as "error.unknown")}</FormError>}
      {notice && <p role="status" className="mt-4 text-sm text-pass">{notice}</p>}
      {code && !editing && <FormError>{t(`error.${code}` as "error.unknown")}</FormError>}

      {student && !editing && (
        <>
          <dl className="mt-6 space-y-3 text-sm">
            <Field label={t("auth.email")} value={student.email} />
            <Field label={t("student.dateOfBirth")} value={formatDate(student.date_of_birth, locale)} />
            <Field label={t("student.phone")} value={student.phone ?? "—"} />
            <Field label={t("student.cohort")} value={student.cohort ?? "—"} />
            <Field
              label={t("student.status")}
              value={<span className={`badge ${student.is_active ? "badge-pass" : "badge-warn"}`}>{t(student.is_active ? "student.active" : "student.inactive")}</span>}
            />
          </dl>

          <div className="mt-6">
            {(record.isPending || enrolled.isPending) && (
              <p className="text-sm text-subtle">{t("stats.loading")}</p>
            )}
            {enrolled.error && (
              <FormError>
                {t(`error.${enrolled.error instanceof ApiError ? enrolled.error.code : "NETWORK_ERROR"}` as "error.unknown")}
              </FormError>
            )}
            {record.data && enrolled.isSuccess && (
              <StudentRecord report={record.data} courses={enrolled.data} locale={locale} />
            )}
          </div>

          <div className="mt-6 flex flex-wrap gap-2">
            <Link href={`/reports/student/${student.student_id}`} className="btn btn-ghost">
              {t("student.report")}
            </Link>
            {editable && (
              <>
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
                {student.is_active ? (
                  <button type="button" className="btn btn-ghost" onClick={() => setDeactivating(true)}>
                    {t("action.deactivate")}
                  </button>
                ) : (
                  <button type="button" className="btn btn-ghost" disabled={lifecycle.isPending} onClick={() => lifecycle.mutate(true)}>
                    {t("action.activate")}
                  </button>
                )}
                <button type="button" className="btn btn-danger" onClick={() => setDeleting(true)}>
                  {t("action.delete")}
                </button>
              </>
            )}
          </div>

          {can.createCourse(me) && (
            <section className="mt-8" aria-labelledby="student-enrollments-heading">
              <h3 id="student-enrollments-heading" className="text-sm font-medium text-text">
                {t("enrollment.manage")}
              </h3>
              {(coursesLoading || enrolled.isPending) && (
                <p className="mt-3 text-sm text-subtle">{t("stats.loading")}</p>
              )}
              {Boolean(coursesError) && (
                <FormError>
                  {t(`error.${coursesError instanceof ApiError ? coursesError.code : "NETWORK_ERROR"}` as "error.unknown")}
                </FormError>
              )}
              {enrolled.error && (
                <FormError>
                  {t(`error.${enrolled.error instanceof ApiError ? enrolled.error.code : "NETWORK_ERROR"}` as "error.unknown")}
                </FormError>
              )}
              {coursesReady && enrolled.isSuccess && (
                <>
                  {student.is_active && availableCourses.length > 0 ? (
                    <form onSubmit={submitEnrollment} className="mt-3 flex items-end gap-2">
                      <div className="min-w-0 flex-1">
                        <Select name="course_id" label={t("enrollment.course")} value={availableCourses[0].course_id}>
                          {availableCourses.map((course) => <option key={course.course_id} value={course.course_id}>{course.course_id} — {course.name}</option>)}
                        </Select>
                      </div>
                      <button type="submit" className="btn btn-primary" disabled={enrollment.isPending}>
                        {t("action.enroll")}
                      </button>
                    </form>
                  ) : (
                    <p className="mt-3 text-sm text-subtle">
                      {t(student.is_active ? "enrollment.noAvailableCourses" : "enrollment.inactiveStudent")}
                    </p>
                  )}

                  <ul className="mt-4 divide-y divide-line rounded-lg border border-line">
                    {enrolled.data.map((entry) => {
                      const ownedCourse = manageableCourses.find((course) => course.course_id === entry.course_id);
                      return (
                        <li key={entry.course_id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm">
                          <span className="text-text">{entry.name}</span>
                          <div className="flex items-center gap-2">
                            <span className={`badge ${entry.status === "active" ? "badge-pass" : entry.status === "withdrawn" ? "badge-warn" : ""}`}>
                              {t(`enrollment.status.${entry.status}` as "enrollment.status.active")}
                            </span>
                            {ownedCourse && entry.status === "active" && (
                              <button type="button" className="btn btn-ghost" onClick={() => setEnrollmentAction({ kind: "withdraw", courseId: entry.course_id, courseName: entry.name })}>
                                {t("action.withdraw")}
                              </button>
                            )}
                            {ownedCourse && (
                              <button type="button" className="btn btn-danger" onClick={() => setEnrollmentAction({ kind: "remove", courseId: entry.course_id, courseName: entry.name })}>
                                {t("action.remove")}
                              </button>
                            )}
                          </div>
                        </li>
                      );
                    })}
                    {enrolled.data.length === 0 && (
                      <li className="px-3 py-4 text-center text-sm text-subtle">{t("stats.noData")}</li>
                    )}
                  </ul>
                </>
              )}
            </section>
          )}

          <div className="mt-6">
            <InsightBlock entityType="student" entityId={student.student_id} />
            <NotesBlock entityType="student" entityId={student.student_id} me={me} locale={locale} />
          </div>
        </>
      )}

      {student && editing && (
        <form onSubmit={submitEdit} className="mt-6 space-y-4">
          <StudentFields student={student} />
          {code && <FormError>{t(`error.${code}` as "error.unknown")}</FormError>}
          <div className="flex gap-2">
            <button type="submit" disabled={save.isPending} className="btn btn-primary">{t("action.save")}</button>
            <button type="button" className="btn btn-ghost" onClick={() => { setEditing(false); setCode(null); }}>{t("action.cancel")}</button>
          </div>
        </form>
      )}

      <Confirm
        open={deactivating}
        title={t("student.deactivateTitle")}
        description={t("student.deactivateDescription")}
        confirmLabel={t("action.deactivate")}
        cancelLabel={t("action.cancel")}
        onConfirm={() => lifecycle.mutateAsync(false).then(() => undefined).catch(() => undefined)}
        onCancel={() => setDeactivating(false)}
      />
      <Confirm
        open={deleting}
        title={t("student.deleteTitle")}
        description={t("student.deleteDescription")}
        confirmLabel={t("action.delete")}
        cancelLabel={t("action.cancel")}
        onConfirm={() => removeStudent.mutateAsync().then(() => undefined).catch(() => undefined)}
        onCancel={() => setDeleting(false)}
      />
      <Confirm
        open={enrollmentAction !== null}
        title={t(enrollmentAction?.kind === "remove" ? "enrollment.removeTitle" : "enrollment.withdrawTitle")}
        description={t(
          enrollmentAction?.kind === "remove" ? "enrollment.removeDescription" : "enrollment.withdrawDescription",
          { course: enrollmentAction?.courseName ?? "" },
        )}
        confirmLabel={t(enrollmentAction?.kind === "remove" ? "action.remove" : "action.withdraw")}
        cancelLabel={t("action.cancel")}
        onConfirm={() => enrollmentAction ? enrollment.mutateAsync(enrollmentAction).then(() => undefined).catch(() => undefined) : undefined}
        onCancel={() => setEnrollmentAction(null)}
      />
    </div>
  );
}
