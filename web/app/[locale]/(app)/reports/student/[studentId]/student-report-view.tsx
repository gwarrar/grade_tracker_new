"use client";

/**
 * A student's report, laid out to be read and to be printed.
 *
 * Print rather than a generated PDF. The browser already renders this page with the
 * institution's own branding, fonts and locale; a server-side PDF library would be a
 * large dependency reproducing that, worse, in a second layout that then has to be
 * kept in step with this one. `@media print` in globals.css hides the chrome and
 * forces the light palette — nobody wants a black page from their printer.
 *
 * CSV export is a real endpoint, because a spreadsheet is a different artefact from a
 * printed page and the server already knows how to translate its headers.
 */

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { StudentRecord } from "@/components/app/student-record";
import { API_BASE, api, ApiError, type Response } from "@/lib/api";
import { errorCode, useErrorMessage } from "@/lib/use-api-error";
import { queryKeys } from "@/lib/query-keys";
import { formatDate } from "@/lib/format";

type Report = Response<"/reports/student/{student_id}", "get">;
type Courses = Response<"/students/{student_id}/courses", "get">;

export function StudentReportView({
  studentId,
  locale,
}: {
  studentId: string;
  locale: string;
}) {
  const t = useTranslations();
  const tError = useErrorMessage();

  const report = useQuery({
    queryKey: queryKeys.reports.student(studentId),
    queryFn: () => api<Report>(`/reports/student/${studentId}`),
  });

  const courses = useQuery({
    queryKey: queryKeys.students.courses(studentId),
    queryFn: () => api<Courses>(`/students/${studentId}/courses`),
  });

  if (report.error instanceof ApiError) {
    return (
      <p role="alert" className="rounded-lg bg-fail-bg px-4 py-3 text-sm text-fail">
        {tError(errorCode(report.error))}
      </p>
    );
  }

  return (
    <article className="mx-auto max-w-4xl">
      <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text">
            {report.data?.student_name ?? studentId}
          </h1>
          <p className="numeric mt-1 text-sm text-subtle">
            {studentId}
            {report.data?.email ? ` · ${report.data.email}` : ""}
          </p>
          {/* Only on paper: a printed report with no date is undatable once it
              leaves the building. On screen it is noise, since the data is live. */}
          <p className="mt-1 hidden text-xs text-subtle print:block">
            {t("report.generated", { date: formatDate(new Date().toISOString(), locale) })}
          </p>
        </div>

        <div className="no-print flex flex-wrap gap-2">
          <a
            href={`${API_BASE}/reports/student/${encodeURIComponent(studentId)}/export.csv?locale=${locale}`}
            download
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
          >
            {t("report.download")}
          </a>
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded-lg bg-brand px-3 py-1.5 text-sm text-brand-contrast transition-opacity hover:opacity-90"
          >
            {t("report.print")}
          </button>
        </div>
      </header>

      {report.isPending && <p className="text-sm text-subtle">{t("stats.loading")}</p>}

      {report.data && (
        <StudentRecord report={report.data} courses={courses.data ?? []} locale={locale} />
      )}
    </article>
  );
}
