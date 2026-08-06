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
import { API_BASE, api, type Response } from "@/lib/api";
import { formatNumber, formatPercent } from "@/lib/format";
import { useUrlParam } from "@/lib/use-selection";

type Summary = Response<"/reports/summary", "get">;
type CourseReport = Response<"/reports/course/{course_id}", "get">;
type Courses = Response<"/courses", "get">;
type TeacherReport = Response<"/reports/teacher/{user_id}", "get">;
type TermReport = Response<"/reports/term/{term}", "get">;
type Assessments = Response<"/reports/course/{course_id}/assessments", "get">;
type Enrollment = Response<"/reports/enrollment", "get">;
type DistributionReport = Response<"/reports/distribution", "get">;

const KINDS = [
  "summary",
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

  const courses = useQuery({
    queryKey: ["courses", "all"],
    queryFn: () => api<Courses>("/courses", { query: { size: 100 } }),
    enabled: kind === "course" || kind === "assessments",
  });

  const summary = useQuery({
    queryKey: ["reports", "summary"],
    queryFn: () => api<Summary>("/reports/summary"),
    enabled: kind === "summary",
  });

  const course = useQuery({
    queryKey: ["reports", "course", courseId],
    queryFn: () => api<CourseReport>(`/reports/course/${encodeURIComponent(courseId)}`),
    enabled: kind === "course" && courseId !== "",
  });

  const teacher = useQuery({
    queryKey: ["reports", "teacher", teacherId],
    queryFn: () => api<TeacherReport>(`/reports/teacher/${encodeURIComponent(teacherId)}`),
    enabled: kind === "teacher" && teacherId !== "",
  });

  const termReport = useQuery({
    queryKey: ["reports", "term", term],
    queryFn: () => api<TermReport>(`/reports/term/${encodeURIComponent(term)}`),
    enabled: kind === "term" && term !== "",
  });

  const assessments = useQuery({
    queryKey: ["reports", "assessments", courseId],
    queryFn: () =>
      api<Assessments>(`/reports/course/${encodeURIComponent(courseId)}/assessments`),
    enabled: kind === "assessments" && courseId !== "",
  });

  const enrollment = useQuery({
    queryKey: ["reports", "enrollment"],
    queryFn: () => api<Enrollment>("/reports/enrollment"),
    enabled: kind === "enrollment",
  });

  const distribution = useQuery({
    queryKey: ["reports", "distribution", bucket],
    queryFn: () => api<DistributionReport>("/reports/distribution", { query: { bucket } }),
    enabled: kind === "distribution",
  });

  const pending =
    summary.isPending ||
    course.isPending ||
    teacher.isPending ||
    termReport.isPending ||
    assessments.isPending ||
    enrollment.isPending ||
    distribution.isPending;

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
    </div>
  );
}
