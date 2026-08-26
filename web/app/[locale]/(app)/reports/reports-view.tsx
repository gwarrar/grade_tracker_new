"use client";

/**
 * The reports surface: an institution summary plus six focused reports.
 *
 * The API returns numbers and identifiers with no sentences in them, and the
 * wording is assembled here. That is what lets a report read in German without
 * the server holding a German phrasebook — and it is why the CSV export is the
 * one place a locale has to travel to the backend, since a downloaded file has
 * no frontend to render it.
 *
 * The chosen report lives in the URL rather than in component state, so a
 * colleague can be sent a link to the one that matters instead of instructions
 * for finding it.
 */

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Distribution } from "@/components/app/distribution";
import { StatTile } from "@/components/app/stat-tile";
import { StudentRecord } from "@/components/app/student-record";
import { Link } from "@/i18n/navigation";
import { API_BASE, api, type Response } from "@/lib/api";
import { errorCode } from "@/lib/use-api-error";
import { queryKeys } from "@/lib/query-keys";
import { formatNumber, formatPercent } from "@/lib/format";
import { useDebounced, useUrlParam } from "@/lib/use-selection";

type Summary = Response<"/reports/summary", "get">;
type CourseReport = Response<"/reports/course/{course_id}", "get">;
type Courses = Response<"/courses", "get">;
type TeacherReport = Response<"/reports/teacher/{user_id}", "get">;
type TermReport = Response<"/reports/term/{term}", "get">;
type Assessments = Response<"/reports/course/{course_id}/assessments", "get">;
type Enrollment = Response<"/reports/enrollment", "get">;
type DistributionReport = Response<"/reports/distribution", "get">;
type StudentReport = Response<"/reports/student/{student_id}", "get">;
type StudentCourses = Response<"/students/{student_id}/courses", "get">;
type StudentPage = Response<"/students", "get">;

const KINDS = [
  "summary",
  "student",
  "course",
  "teacher",
  "term",
  "assessments",
  "enrollment",
  "distribution",
] as const;

type Kind = (typeof KINDS)[number];

/** The message key naming each report in the picker. */
const KIND_LABEL: Record<Kind, string> = {
  summary: "report.summary",
  student: "student.one",
  course: "course.one",
  teacher: "report.teacherReport",
  term: "report.termReport",
  assessments: "report.assessments",
  enrollment: "report.enrollmentReport",
  distribution: "report.distributionReport",
};

const SELECT_CLASS =
  "rounded-lg border border-line bg-bg px-3 py-1.5 text-sm text-text outline-none focus-visible:border-brand";

/** A download link. The browser's own file handling beats a fetch and a blob URL. */
function ExportLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      download
      className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
    >
      {label}
    </a>
  );
}

export function ReportsView({ locale, bands }: { locale: string; bands: string[] }) {
  const t = useTranslations();
  const [kindParam, setKind] = useUrlParam("kind", "summary");
  const kind = (KINDS as readonly string[]).includes(kindParam) ? (kindParam as Kind) : "summary";

  const [courseId, setCourseId] = useState("");
  const [teacherId, setTeacherId] = useState("");
  const [term, setTerm] = useState("");
  const [bucket, setBucket] = useState("month");
  const [studentId, setStudentId] = useState("");
  const [studentSearch, setStudentSearch] = useState("");
  const studentQuery = useDebounced(studentSearch.trim());

  const courses = useQuery({
    queryKey: queryKeys.courses.picker("reports"),
    queryFn: () => api<Courses>("/courses", { query: { size: 100 } }),
    enabled: kind === "course" || kind === "assessments",
  });

  const summary = useQuery({
    queryKey: queryKeys.reports.summary(),
    queryFn: () => api<Summary>("/reports/summary"),
    enabled: kind === "summary",
  });

  // Searched rather than listed: an institution has far more students than courses,
  // and a picker capped at some round number silently omits the rest.
  const students = useQuery({
    queryKey: queryKeys.students.picker("reports", { q: studentQuery }),
    queryFn: () => api<StudentPage>("/students", { query: { q: studentQuery, size: 20 } }),
    enabled: kind === "student",
    placeholderData: (previous) => previous,
  });

  const studentReport = useQuery({
    queryKey: queryKeys.reports.student(studentId),
    queryFn: () => api<StudentReport>(`/reports/student/${encodeURIComponent(studentId)}`),
    enabled: kind === "student" && studentId !== "",
  });

  const studentCourses = useQuery({
    queryKey: queryKeys.students.courses(studentId),
    queryFn: () => api<StudentCourses>(`/students/${encodeURIComponent(studentId)}/courses`),
    enabled: kind === "student" && studentId !== "",
  });

  const course = useQuery({
    queryKey: queryKeys.reports.course(courseId),
    queryFn: () => api<CourseReport>(`/reports/course/${encodeURIComponent(courseId)}`),
    enabled: kind === "course" && courseId !== "",
  });

  const teacher = useQuery({
    queryKey: queryKeys.reports.teacher(teacherId),
    queryFn: () => api<TeacherReport>(`/reports/teacher/${encodeURIComponent(teacherId)}`),
    enabled: kind === "teacher" && teacherId !== "",
  });

  const termReport = useQuery({
    queryKey: queryKeys.reports.term(term),
    queryFn: () => api<TermReport>(`/reports/term/${encodeURIComponent(term)}`),
    enabled: kind === "term" && term !== "",
  });

  const assessments = useQuery({
    queryKey: queryKeys.reports.assessments(courseId),
    queryFn: () =>
      api<Assessments>(`/reports/course/${encodeURIComponent(courseId)}/assessments`),
    enabled: kind === "assessments" && courseId !== "",
  });

  const enrollment = useQuery({
    queryKey: queryKeys.reports.enrollment(),
    queryFn: () => api<Enrollment>("/reports/enrollment"),
    enabled: kind === "enrollment",
  });

  const distribution = useQuery({
    queryKey: queryKeys.reports.distribution(bucket),
    queryFn: () => api<DistributionReport>("/reports/distribution", { query: { bucket } }),
    enabled: kind === "distribution",
  });

  // isFetching, not isPending: a disabled query never fetches, so it stays pending
  // forever. Six of these seven are disabled at any moment -- only the chosen report
  // is enabled -- so reading isPending left "Loading…" on screen permanently.
  const active = [
    summary,
    studentReport,
    studentCourses,
    course,
    teacher,
    termReport,
    assessments,
    enrollment,
    distribution,
  ];

  const pending = active.some((query) => query.isFetching);

  // Every section here renders on `.data &&`, so a failure rendered nothing at all
  // and "this teacher does not exist" looked exactly like "this teacher has no
  // courses". On the one screen that is read-only, an empty card is not a neutral
  // outcome: it is a wrong answer that nobody can tell is wrong.
  const failure = active.find((query) => query.isError)?.error;

  const courseOptions = (
    <>
      <option value="">{t("report.pick")}</option>
      {(courses.data?.items ?? []).map((row) => (
        <option key={row.course_id} value={row.course_id}>
          {row.course_id} — {row.name}
        </option>
      ))}
    </>
  );

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text">{t("report.title")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">{t("report.hint")}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="report-kind" className="sr-only">
            {t("report.title")}
          </label>
          <select
            id="report-kind"
            value={kind}
            onChange={(event) => setKind(event.target.value)}
            className={SELECT_CLASS}
          >
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {t(KIND_LABEL[value])}
              </option>
            ))}
          </select>

          {kind === "summary" && (
            <ExportLink
              href={`${API_BASE}/reports/summary/summary/export.csv?locale=${locale}`}
              label={t("report.summaryDownload")}
            />
          )}
          {kind === "course" && courseId && (
            <ExportLink
              href={`${API_BASE}/reports/course/${encodeURIComponent(courseId)}/export.csv?locale=${locale}`}
              label={t("action.export")}
            />
          )}
          {kind === "student" && studentId && (
            <>
              <ExportLink
                href={`${API_BASE}/reports/student/${encodeURIComponent(studentId)}/export.csv?locale=${locale}`}
                label={t("action.export")}
              />
              {/* The dedicated page carries the print stylesheet, which is how a
                  transcript becomes a PDF without a server-side renderer. */}
              <Link href={`/reports/student/${encodeURIComponent(studentId)}`} className="btn btn-ghost">
                {t("report.print")}
              </Link>
            </>
          )}
        </div>
      </div>

      {kind === "summary" && summary.data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              label={t("student.other")}
              value={formatNumber(summary.data.student_count, locale)}
            />
            <StatTile
              label={t("course.other")}
              value={formatNumber(summary.data.course_count, locale)}
            />
            <StatTile
              label={t("grade.other")}
              value={formatNumber(summary.data.grade_count, locale)}
            />
            <StatTile
              label={t("stats.average")}
              value={
                summary.data.overall_average_percentage != null
                  ? formatPercent(summary.data.overall_average_percentage, locale)
                  : "—"
              }
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Distribution distribution={summary.data.distribution} order={bands} locale={locale} />

            <section className="rounded-xl border border-line bg-surface p-6">
              <h2 className="text-sm font-medium text-text">{t("stats.topStudents")}</h2>

              {summary.data.top_students.length === 0 ? (
                <p className="mt-4 text-center text-sm text-subtle">{t("stats.noData")}</p>
              ) : (
                <table className="mt-3 w-full text-sm">
                  <caption className="sr-only">{t("stats.topStudents")}</caption>
                  <thead className="sr-only">
                    <tr>
                      <th scope="col">{t("report.rank")}</th>
                      <th scope="col">{t("profile.name")}</th>
                      <th scope="col">{t("stats.average")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {summary.data.top_students.map((student, index) => (
                      <tr key={student.student_id}>
                        <td className="numeric w-8 py-2 text-subtle">
                          {formatNumber(index + 1, locale)}
                        </td>
                        <th
                          scope="row"
                          className="min-w-0 truncate py-2 text-start font-normal text-muted"
                        >
                          {student.name}
                        </th>
                        <td className="numeric py-2 text-end text-text">
                          {formatPercent(student.average_percentage, locale)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section className="rounded-xl border border-line bg-surface p-6">
              <h2 className="text-sm font-medium text-text">{t("stats.atRisk")}</h2>
              <p className="numeric mt-1 text-xs text-subtle">
                {t("report.threshold")}: {formatPercent(summary.data.at_risk_threshold, locale)}
              </p>

              {summary.data.at_risk_students.length === 0 ? (
                <p className="mt-4 text-center text-sm text-subtle">{t("stats.noData")}</p>
              ) : (
                <ul className="mt-3 divide-y divide-line text-sm">
                  {summary.data.at_risk_students.map((student) => (
                    <li
                      key={student.student_id}
                      className="flex items-center justify-between gap-4 py-2"
                    >
                      <span className="min-w-0 truncate text-muted">{student.name}</span>
                      <span className="numeric shrink-0 text-fail">
                        {formatPercent(student.average_percentage, locale)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}

      {kind === "student" && (
        <section className="rounded-xl border border-line bg-surface p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="text-sm font-medium text-text">{t("student.one")}</h2>
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="student-search" className="sr-only">
                {t("enrollment.searchStudents")}
              </label>
              <input
                id="student-search"
                value={studentSearch}
                onChange={(event) => setStudentSearch(event.target.value)}
                placeholder={t("enrollment.searchStudents")}
                className={SELECT_CLASS}
              />
              <label htmlFor="student-pick" className="sr-only">
                {t("report.pick")}
              </label>
              <select
                id="student-pick"
                value={studentId}
                onChange={(event) => setStudentId(event.target.value)}
                className={SELECT_CLASS}
              >
                <option value="">{t("report.pick")}</option>
                {(students.data?.items ?? []).map((row) => (
                  <option key={row.student_id} value={row.student_id}>
                    {row.student_id} — {row.first_name} {row.last_name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {studentReport.data && (
            <div className="mt-6">
              <StudentRecord
                report={studentReport.data}
                courses={studentCourses.data ?? []}
                locale={locale}
              />
            </div>
          )}
        </section>
      )}

      {kind === "course" && (
        <section className="rounded-xl border border-line bg-surface p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="text-sm font-medium text-text">{t("course.one")}</h2>
            <label htmlFor="course" className="sr-only">
              {t("report.pick")}
            </label>
            <select
              id="course"
              value={courseId}
              onChange={(event) => setCourseId(event.target.value)}
              className={SELECT_CLASS}
            >
              {courseOptions}
            </select>
          </div>

          {course.data && (
            <div className="mt-6 space-y-6">
              <div className="grid gap-4 sm:grid-cols-3">
                <StatTile
                  label={t("stats.average")}
                  value={
                    course.data.average_score != null
                      ? formatNumber(course.data.average_score, locale)
                      : "—"
                  }
                  hint={`${t("grade.max")}: ${formatNumber(course.data.max_grade, locale)}`}
                />
                <StatTile
                  label={t("stats.passRate")}
                  value={
                    course.data.pass_rate != null
                      ? formatPercent(course.data.pass_rate, locale)
                      : "—"
                  }
                />
                <StatTile
                  label={t("report.graded")}
                  value={formatNumber(course.data.graded_student_count, locale)}
                />
              </div>

              <Distribution distribution={course.data.distribution} order={bands} locale={locale} />
            </div>
          )}
        </section>
      )}

      {kind === "teacher" && (
        <section className="rounded-xl border border-line bg-surface p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="text-sm font-medium text-text">{t("report.teacherReport")}</h2>
            <label htmlFor="teacher" className="sr-only">
              {t("report.pickTeacher")}
            </label>
            <input
              id="teacher"
              type="number"
              min={1}
              inputMode="numeric"
              value={teacherId}
              onChange={(event) => setTeacherId(event.target.value)}
              placeholder={t("report.pickTeacher")}
              className={SELECT_CLASS}
            />
          </div>

          {teacher.data && (
            <div className="mt-6 space-y-6">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <StatTile label={t("profile.name")} value={teacher.data.teacher_name ?? "—"} />
                <StatTile
                  label={t("course.other")}
                  value={formatNumber(teacher.data.course_count, locale)}
                />
                <StatTile
                  label={t("student.other")}
                  value={formatNumber(teacher.data.student_count, locale)}
                />
                <StatTile
                  label={t("stats.average")}
                  value={
                    teacher.data.average_percentage != null
                      ? formatPercent(teacher.data.average_percentage, locale)
                      : "—"
                  }
                />
              </div>

              {teacher.data.courses.length === 0 ? (
                <p className="text-center text-sm text-subtle">{t("stats.noData")}</p>
              ) : (
                <table className="w-full text-sm">
                  <caption className="sr-only">{t("report.teacherReport")}</caption>
                  <thead className="text-start text-xs text-subtle">
                    <tr className="border-b border-line">
                      <th scope="col" className="py-2 text-start font-medium">
                        {t("course.one")}
                      </th>
                      <th scope="col" className="py-2 text-end font-medium">
                        {t("student.other")}
                      </th>
                      <th scope="col" className="py-2 text-end font-medium">
                        {t("stats.average")}
                      </th>
                      <th scope="col" className="py-2 text-end font-medium">
                        {t("stats.passRate")}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {teacher.data.courses.map((row) => (
                      <tr key={row.course_id}>
                        <th scope="row" className="py-2 text-start font-normal text-muted">
                          {row.course_id} — {row.course_name}
                        </th>
                        <td className="numeric py-2 text-end text-muted">
                          {formatNumber(row.student_count, locale)}
                        </td>
                        <td className="numeric py-2 text-end text-text">
                          {row.average_percentage != null
                            ? formatPercent(row.average_percentage, locale)
                            : "—"}
                        </td>
                        <td className="numeric py-2 text-end text-muted">
                          {row.pass_rate != null ? formatPercent(row.pass_rate, locale) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </section>
      )}

      {kind === "term" && (
        <section className="rounded-xl border border-line bg-surface p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="text-sm font-medium text-text">{t("report.termReport")}</h2>
            <label htmlFor="term" className="sr-only">
              {t("report.pickTerm")}
            </label>
            <input
              id="term"
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder={t("report.pickTerm")}
              className={SELECT_CLASS}
            />
          </div>

          {termReport.data && (
            <div className="mt-6 space-y-6">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <StatTile
                  label={t("course.other")}
                  value={formatNumber(termReport.data.course_count, locale)}
                />
                <StatTile
                  label={t("student.other")}
                  value={formatNumber(termReport.data.student_count, locale)}
                />
                <StatTile
                  label={t("stats.average")}
                  value={
                    termReport.data.average_percentage != null
                      ? formatPercent(termReport.data.average_percentage, locale)
                      : "—"
                  }
                />
                <StatTile
                  label={t("stats.passRate")}
                  value={
                    termReport.data.pass_rate != null
                      ? formatPercent(termReport.data.pass_rate, locale)
                      : "—"
                  }
                />
              </div>

              {termReport.data.courses.length === 0 ? (
                <p className="text-center text-sm text-subtle">{t("stats.noData")}</p>
              ) : (
                <table className="w-full text-sm">
                  <caption className="sr-only">{t("report.termReport")}</caption>
                  <thead className="text-xs text-subtle">
                    <tr className="border-b border-line">
                      <th scope="col" className="py-2 text-start font-medium">
                        {t("course.one")}
                      </th>
                      <th scope="col" className="py-2 text-start font-medium">
                        {t("profile.name")}
                      </th>
                      <th scope="col" className="py-2 text-end font-medium">
                        {t("stats.average")}
                      </th>
                      <th scope="col" className="py-2 text-end font-medium">
                        {t("stats.passRate")}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {termReport.data.courses.map((row) => (
                      <tr key={row.course_id}>
                        <th scope="row" className="py-2 text-start font-normal text-muted">
                          {row.course_id} — {row.course_name}
                        </th>
                        <td className="py-2 text-muted">{row.teacher_name ?? "—"}</td>
                        <td className="numeric py-2 text-end text-text">
                          {row.average_percentage != null
                            ? formatPercent(row.average_percentage, locale)
                            : "—"}
                        </td>
                        <td className="numeric py-2 text-end text-muted">
                          {row.pass_rate != null ? formatPercent(row.pass_rate, locale) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </section>
      )}

      {kind === "assessments" && (
        <section className="rounded-xl border border-line bg-surface p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="text-sm font-medium text-text">{t("report.assessments")}</h2>
            <label htmlFor="assessment-course" className="sr-only">
              {t("report.pickAssessment")}
            </label>
            <select
              id="assessment-course"
              value={courseId}
              onChange={(event) => setCourseId(event.target.value)}
              className={SELECT_CLASS}
            >
              {courseOptions}
            </select>
          </div>

          {assessments.data && (
            <div className="mt-6 space-y-6">
              {assessments.data.assessments.length === 0 ? (
                <p className="text-center text-sm text-subtle">{t("stats.noData")}</p>
              ) : (
                assessments.data.assessments.map((row) => (
                  <div key={row.title} className="space-y-3 border-t border-line pt-4 first:border-0 first:pt-0">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <h3 className="text-sm font-medium text-text">{row.title}</h3>
                      <p className="numeric text-xs text-subtle">
                        {t("report.range")}: {formatNumber(row.min_score, locale)} –{" "}
                        {formatNumber(row.max_score, locale)}
                      </p>
                    </div>

                    <div className="grid gap-4 sm:grid-cols-3">
                      <StatTile
                        label={t("stats.average")}
                        value={formatPercent(row.average_percentage, locale)}
                        hint={formatNumber(row.average_score, locale)}
                      />
                      <StatTile
                        label={t("stats.passRate")}
                        value={formatPercent(row.pass_rate, locale)}
                      />
                      <StatTile
                        label={t("report.total")}
                        value={formatNumber(row.count, locale)}
                      />
                    </div>

                    <Distribution
                      distribution={row.distribution as Record<string, number>}
                      order={bands}
                      locale={locale}
                    />
                  </div>
                ))
              )}
            </div>
          )}
        </section>
      )}

      {kind === "enrollment" && enrollment.data && (
        <section className="rounded-xl border border-line bg-surface p-6">
          <h2 className="text-sm font-medium text-text">{t("report.enrollmentReport")}</h2>

          {enrollment.data.rows.length === 0 ? (
            <p className="mt-4 text-center text-sm text-subtle">{t("stats.noData")}</p>
          ) : (
            <table className="mt-4 w-full text-sm">
              <caption className="sr-only">{t("report.enrollmentReport")}</caption>
              <thead className="text-xs text-subtle">
                <tr className="border-b border-line">
                  <th scope="col" className="py-2 text-start font-medium">
                    {t("course.one")}
                  </th>
                  <th scope="col" className="py-2 text-end font-medium">
                    {t("report.capacity")}
                  </th>
                  <th scope="col" className="py-2 text-end font-medium">
                    {t("enrollment.active")}
                  </th>
                  <th scope="col" className="py-2 text-end font-medium">
                    {t("enrollment.withdrawn")}
                  </th>
                  <th scope="col" className="py-2 text-end font-medium">
                    {t("report.utilisation")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {enrollment.data.rows.map((row) => (
                  <tr key={row.course_id}>
                    <th scope="row" className="py-2 text-start font-normal text-muted">
                      {row.course_id} — {row.course_name}
                    </th>
                    <td className="numeric py-2 text-end text-muted">
                      {formatNumber(row.capacity, locale)}
                    </td>
                    <td className="numeric py-2 text-end text-text">
                      {formatNumber(row.active, locale)}
                    </td>
                    <td className="numeric py-2 text-end text-subtle">
                      {formatNumber(row.withdrawn, locale)}
                    </td>
                    <td className="numeric py-2 text-end text-text">
                      {formatPercent(row.utilisation, locale)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {kind === "distribution" && (
        <section className="rounded-xl border border-line bg-surface p-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h2 className="text-sm font-medium text-text">{t("report.distributionReport")}</h2>
            <label htmlFor="bucket" className="sr-only">
              {t("report.period")}
            </label>
            <select
              id="bucket"
              value={bucket}
              onChange={(event) => setBucket(event.target.value)}
              className={SELECT_CLASS}
            >
              <option value="month">{t("report.byMonth")}</option>
              <option value="term">{t("report.byTerm")}</option>
            </select>
          </div>

          {distribution.data && (
            <div className="mt-6 space-y-6">
              {distribution.data.buckets.length === 0 ? (
                <p className="text-center text-sm text-subtle">{t("stats.noData")}</p>
              ) : (
                distribution.data.buckets.map((row) => (
                  <div key={row.bucket} className="space-y-2">
                    <h3 className="numeric text-xs font-medium text-subtle">{row.bucket}</h3>
                    <Distribution
                      distribution={row.distribution as Record<string, number>}
                      order={bands}
                      locale={locale}
                    />
                  </div>
                ))
              )}
            </div>
          )}
        </section>
      )}

      {pending && <p className="text-center text-sm text-subtle">{t("stats.loading")}</p>}

      {!pending && failure && (
        <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-center text-sm text-fail">
          {t(
            errorCode(failure),
          )}
        </p>
      )}
    </div>
  );
}
