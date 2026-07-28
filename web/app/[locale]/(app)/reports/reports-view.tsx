"use client";

/**
 * The institution-wide summary and per-course reports.
 *
 * The API returns numbers and identifiers with no sentences in them, and the
 * wording is assembled here. That is what lets a report read in German without
 * the server holding a German phrasebook — and it is why the CSV export is the
 * one place a locale has to travel to the backend, since a downloaded file has
 * no frontend to render it.
 */

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Distribution } from "@/components/app/distribution";
import { StatTile } from "@/components/app/stat-tile";
import { API_BASE, api, type Response } from "@/lib/api";
import { formatNumber, formatPercent } from "@/lib/format";

type Summary = Response<"/reports/summary", "get">;
type CourseReport = Response<"/reports/course/{course_id}", "get">;
type Courses = Response<"/courses", "get">;

export function ReportsView({ locale, bands }: { locale: string; bands: string[] }) {
  const t = useTranslations();
  const [courseId, setCourseId] = useState("");

  const summary = useQuery({
    queryKey: ["reports", "summary"],
    queryFn: () => api<Summary>("/reports/summary"),
  });

  const courses = useQuery({
    queryKey: ["courses", "all"],
    queryFn: () => api<Courses>("/courses", { query: { size: 100 } }),
  });

  const report = useQuery({
    queryKey: ["reports", "course", courseId],
    queryFn: () => api<CourseReport>(`/reports/course/${courseId}`),
    enabled: courseId !== "",
  });

  const data = summary.data;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text">{t("report.title")}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">{t("report.hint")}</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label={t("student.other")}
          value={data ? formatNumber(data.student_count, locale) : "—"}
        />
        <StatTile
          label={t("course.other")}
          value={data ? formatNumber(data.course_count, locale) : "—"}
        />
        <StatTile
          label={t("grade.other")}
          value={data ? formatNumber(data.grade_count, locale) : "—"}
        />
        <StatTile
          label={t("stats.average")}
          value={
            data?.overall_average_percentage != null
              ? formatPercent(data.overall_average_percentage, locale)
              : "—"
          }
        />
      </div>

      {data && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Distribution distribution={data.distribution} order={bands} locale={locale} />

          <section className="rounded-xl border border-line bg-surface p-6">
            <h2 className="text-sm font-medium text-text">{t("stats.atRisk")}</h2>
            <p className="numeric mt-1 text-xs text-subtle">
              {t("report.threshold")}: {formatPercent(data.at_risk_threshold, locale)}
            </p>

            {data.at_risk_students.length === 0 ? (
              <p className="mt-4 text-center text-sm text-subtle">{t("stats.noData")}</p>
            ) : (
              <ul className="mt-3 divide-y divide-line text-sm">
                {data.at_risk_students.map((student) => (
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
      )}

      <section className="rounded-xl border border-line bg-surface p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-sm font-medium text-text">{t("course.one")}</h2>

          <div className="flex items-center gap-2">
            <label htmlFor="course" className="sr-only">
              {t("report.pick")}
            </label>
            <select
              id="course"
              value={courseId}
              onChange={(event) => setCourseId(event.target.value)}
              className="rounded-lg border border-line bg-bg px-3 py-1.5 text-sm text-text outline-none focus-visible:border-brand"
            >
              <option value="">{t("report.pick")}</option>
              {(courses.data?.items ?? []).map((course) => (
                <option key={course.course_id} value={course.course_id}>
                  {course.course_id} — {course.name}
                </option>
              ))}
            </select>

            {courseId && (
              // A plain anchor with `download`: the browser's own file handling
              // beats anything reconstructed from a fetch and a blob URL, and the
              // session cookie rides along. The locale goes to the server here
              // because a downloaded file has no frontend to translate its headers.
              <a
                href={`${API_BASE}/reports/course/${encodeURIComponent(courseId)}/export.csv?locale=${locale}`}
                download
                className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
              >
                {t("action.export")}
              </a>
            )}
          </div>
        </div>

        {report.data && (
          <div className="mt-6 space-y-6">
            <div className="grid gap-4 sm:grid-cols-3">
              <StatTile
                label={t("stats.average")}
                value={
                  report.data.average_score != null
                    ? formatNumber(report.data.average_score, locale)
                    : "—"
                }
                hint={`${t("grade.max")}: ${formatNumber(report.data.max_grade, locale)}`}
              />
              <StatTile
                label={t("stats.passRate")}
                value={
                  report.data.pass_rate != null
                    ? formatPercent(report.data.pass_rate, locale)
                    : "—"
                }
              />
              <StatTile
                label={t("report.graded")}
                value={formatNumber(report.data.graded_student_count, locale)}
              />
            </div>

            <Distribution
              distribution={report.data.distribution}
              order={bands}
              locale={locale}
            />
          </div>
        )}

        {courseId && report.isPending && (
          <p className="mt-6 text-center text-sm text-subtle">…</p>
        )}
      </section>
    </div>
  );
}
