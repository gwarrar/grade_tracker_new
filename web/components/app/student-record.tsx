"use client";

/**
 * A student's academic record: headline figures, then their marks grouped by course.
 *
 * One component for two readers, because the API already makes them the same request.
 * `GET /reports/student/{id}` returns a student their whole record and returns a
 * teacher only the marks from their own courses, recomputing the average to match. So
 * "a student viewing themselves" needs no separate page and no branch here — the
 * server has already decided what this person may see.
 *
 * Courses with no marks yet come from a second call, because a report built from
 * grades cannot contain a course that has none. That distinction is the reason
 * enrolments are their own table, and showing it is the difference between "you have
 * no marks in Databases" and Databases silently not existing.
 */

import { useTranslations } from "next-intl";

import { StatTile } from "@/components/app/stat-tile";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { groupByCourse, type Line } from "@/lib/grades";

interface GradeLine extends Line {
  grade_id: number;
  title: string;
  score: number;
  max_grade: number;
  letter: string;
  date: string;
}

interface Report {
  average_percentage: number | null;
  passed_count: number;
  failed_count: number;
  courses_graded: number;
  grades: GradeLine[];
}

interface EnrolledCourse {
  course_id: string;
  name: string;
  term?: string | null;
  status: string;
}

export function StudentRecord({
  report,
  courses,
  locale,
}: {
  report: Report;
  /** Every enrolment, so ungraded courses appear too. */
  courses: EnrolledCourse[];
  locale: string;
}) {
  const t = useTranslations();
  const groups = groupByCourse(report.grades);
  const graded = new Set(groups.map((g) => g.course_id));
  const ungraded = courses.filter((course) => !graded.has(course.course_id));

  return (
    <div className="space-y-8">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label={t("stats.average")}
          // null is "not assessed yet", which is not zero. An em dash says so; 0%
          // would be a false statement about the student.
          value={
            report.average_percentage != null
              ? formatPercent(report.average_percentage, locale)
              : "—"
          }
        />
        <StatTile label={t("course.other")} value={formatNumber(courses.length, locale)} />
        <StatTile label={t("grade.passing")} value={formatNumber(report.passed_count, locale)} />
        <StatTile label={t("grade.failing")} value={formatNumber(report.failed_count, locale)} />
      </div>

      {groups.map((group) => (
        <section key={group.course_id}>
          <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-2">
            <h3 className="text-sm font-medium text-text">{group.course_name}</h3>
            <p className="numeric text-xs text-subtle">
              {group.average != null ? formatPercent(group.average, locale) : "—"}
            </p>
          </header>

          <table className="mt-2 w-full text-sm">
            <caption className="sr-only">{group.course_name}</caption>
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-subtle">
                <th scope="col" className="py-1.5 font-medium">
                  {t("grade.title")}
                </th>
                <th scope="col" className="py-1.5 font-medium">
                  {t("grade.date")}
                </th>
                <th scope="col" className="py-1.5 text-end font-medium">
                  {t("grade.score")}
                </th>
                <th scope="col" className="py-1.5 text-end font-medium">
                  {t("grade.percentage")}
                </th>
                <th scope="col" className="py-1.5 text-end font-medium">
                  {t("grade.letter")}
                </th>
              </tr>
            </thead>
            <tbody>
              {group.lines.map((line) => (
                <tr key={line.grade_id} className="border-t border-line/60">
                  <td className="py-1.5 text-text">{line.title || "—"}</td>
                  <td className="numeric py-1.5 text-muted">{formatDate(line.date, locale)}</td>
                  <td className="numeric py-1.5 text-end text-muted">
                    {formatNumber(line.score, locale)} / {formatNumber(line.max_grade, locale)}
                  </td>
                  <td className="numeric py-1.5 text-end">
                    {/* The figure carries the meaning; colour is a second signal, not
                        the only one. */}
                    <span className={line.is_passing ? "text-text" : "text-fail"}>
                      {formatPercent(line.percentage, locale)}
                    </span>
                  </td>
                  <td className="numeric py-1.5 text-end font-medium text-text">{line.letter}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      {ungraded.length > 0 && (
        <section>
          <h3 className="border-b border-line pb-2 text-sm font-medium text-text">
            {t("enrollment.notAssessed")}
          </h3>
          <ul className="mt-2 space-y-1 text-sm">
            {ungraded.map((course) => (
              <li key={course.course_id} className="flex justify-between gap-3 text-muted">
                <span>{course.name}</span>
                <span className="numeric text-xs text-subtle">{course.term ?? "—"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {groups.length === 0 && ungraded.length === 0 && (
        <p className="py-8 text-center text-sm text-subtle">{t("stats.noData")}</p>
      )}
    </div>
  );
}
