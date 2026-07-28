"use client";

/**
 * The headline numbers, the shape of the results, and who needs attention.
 *
 * Everything here is scoped by the API, so a teacher's dashboard describes their
 * courses and a student's describes themselves — the page does no filtering of
 * its own and could not widen the scope if it tried.
 */

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Distribution } from "@/components/app/distribution";
import { StatTile } from "@/components/app/stat-tile";
import { Link } from "@/i18n/navigation";
import { api, type Response } from "@/lib/api";
import { formatNumber, formatPercent } from "@/lib/format";

type Dashboard = Response<"/analytics/dashboard", "get">;
type Ranked = Response<"/analytics/at-risk", "get">;

export function DashboardView({ locale, bands }: { locale: string; bands: string[] }) {
  const t = useTranslations();

  const summary = useQuery({
    queryKey: ["analytics", "dashboard"],
    queryFn: () => api<Dashboard>("/analytics/dashboard"),
  });

  const atRisk = useQuery({
    queryKey: ["analytics", "at-risk"],
    queryFn: () => api<Ranked>("/analytics/at-risk"),
  });

  const top = useQuery({
    queryKey: ["analytics", "top-students"],
    queryFn: () => api<Ranked>("/analytics/top-students", { query: { limit: 5 } }),
  });

  const data = summary.data;

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight text-text">{t("nav.dashboard")}</h1>

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
          label={t("stats.average")}
          // null is "no grades yet", which is not the same as zero. An em dash
          // says so; 0% would be a false statement about the cohort.
          value={
            data?.average_percentage != null
              ? formatPercent(data.average_percentage, locale)
              : "—"
          }
          hint={data ? `${formatNumber(data.grade_count, locale)} ${t("grade.other")}` : undefined}
        />
        <StatTile
          label={t("stats.passRate")}
          value={data?.pass_rate != null ? formatPercent(data.pass_rate, locale) : "—"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Distribution
          distribution={data?.distribution ?? {}}
          order={bands}
          locale={locale}
        />

        <div className="space-y-6">
          <RankedList
            title={t("stats.atRisk")}
            rows={atRisk.data ?? []}
            locale={locale}
            tone="fail"
          />
          <RankedList
            title={t("stats.topStudents")}
            rows={top.data ?? []}
            locale={locale}
            tone="pass"
          />
        </div>
      </div>
    </div>
  );
}

/** A short leaderboard. Links through, because a name here is a question. */
function RankedList({
  title,
  rows,
  locale,
  tone,
}: {
  title: string;
  rows: Ranked;
  locale: string;
  tone: "pass" | "fail";
}) {
  const t = useTranslations("stats");

  return (
    <section className="rounded-xl border border-line bg-surface p-6">
      <h2 className="text-sm font-medium text-text">{title}</h2>

      {rows.length === 0 ? (
        <p className="mt-4 text-center text-sm text-subtle">{t("noData")}</p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {rows.map((row) => (
            <li key={row.student_id}>
              <Link
                href={`/students?id=${encodeURIComponent(row.student_id)}`}
                className="flex items-center justify-between gap-4 py-2 text-sm transition-colors hover:text-text"
              >
                <span className="min-w-0 truncate text-muted">{row.name}</span>
                <span
                  className={`numeric shrink-0 ${tone === "fail" ? "text-fail" : "text-pass"}`}
                >
                  {formatPercent(row.average_percentage, locale)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
