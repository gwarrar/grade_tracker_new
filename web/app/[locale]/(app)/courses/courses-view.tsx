"use client";

/**
 * Courses list with the sliding detail panel.
 *
 * The panel shows the register alongside the course, because "who is enrolled" is
 * the question anyone opening a course is actually asking — and it is the one
 * place where an enrolled-but-ungraded student is visible at all.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Field, Input, PanelHeader } from "@/components/app/detail-fields";
import { InsightBlock } from "@/components/app/insight";
import { MasterDetail } from "@/components/app/master-detail";
import { api, ApiError, type Response } from "@/lib/api";
import { formatNumber, parseLocaleNumber } from "@/lib/format";
import { useDebounced, useSelection } from "@/lib/use-selection";

type Course = Response<"/courses/{course_id}", "get">;
type Page = Response<"/courses", "get">;
type Register = Response<"/courses/{course_id}/enrollments", "get">;

const PAGE_SIZE = 50;

export function CoursesView({ locale }: { locale: string }) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const [selectedId, select] = useSelection();
  const [search, setSearch] = useState("");
  const query = useDebounced(search.trim());

  const list = useQuery({
    queryKey: ["courses", { q: query }],
    queryFn: () => api<Page>("/courses", { query: { q: query, size: PAGE_SIZE } }),
    placeholderData: (previous) => previous,
  });

  const detail = useQuery({
    queryKey: ["course", selectedId],
    queryFn: () => api<Course>(`/courses/${selectedId}`),
    enabled: selectedId !== null,
  });

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

        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("action.search")}
          aria-label={t("action.search")}
          className="w-56 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
        />
      </div>

      <MasterDetail
        detailKey={selectedId}
        detail={
          selectedId && (
            <CourseDetail
              key={selectedId}
              courseId={selectedId}
              course={detail.data}
              loading={detail.isPending}
              error={detail.error}
              locale={locale}
              onClose={() => select(null)}
              onSaved={() => {
                void queryClient.invalidateQueries({ queryKey: ["course", selectedId] });
                void queryClient.invalidateQueries({ queryKey: ["courses"] });
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
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("course.id")}
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("course.one")}
                </th>
                <th scope="col" className="px-4 py-2.5 text-end font-medium">
                  {t("enrollment.enrolled")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((course) => {
                const active = course.course_id === selectedId;
                return (
                  <tr
                    key={course.course_id}
                    className={`border-b border-line last:border-0 transition-colors ${
                      active ? "bg-bg-subtle" : "hover:bg-bg-subtle"
                    }`}
                  >
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
                    <td className="numeric px-4 py-2.5 text-end text-muted">
                      {formatNumber(course.enrolled_count, locale)}
                      <span className="text-subtle">
                        {" / "}
                        {formatNumber(course.max_students, locale)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {list.isPending && <p className="px-4 py-8 text-center text-sm text-subtle">…</p>}
          {!list.isPending && rows.length === 0 && (
            <p className="px-4 py-8 text-center text-sm text-subtle">{t("stats.noData")}</p>
          )}
        </div>
      </MasterDetail>
    </>
  );
}

function CourseDetail({
  courseId,
  course,
  loading,
  error,
  locale,
  onClose,
  onSaved,
}: {
  courseId: string;
  course: Course | undefined;
  loading: boolean;
  error: unknown;
  locale: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations();
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState<string | null>(null);

  const register = useQuery({
    queryKey: ["course", courseId, "enrollments"],
    queryFn: () => api<Register>(`/courses/${courseId}/enrollments`),
    enabled: !editing,
  });

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/courses/${courseId}`, { method: "PATCH", body }),
    onSuccess: () => {
      setEditing(false);
      setCode(null);
      onSaved();
    },
    onError: (err) => setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR"),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);

    // Parsed against the active locale, so a German user's "1,5" credits is 1.5
    // and not 15. A null means the text was not a number in this locale — reported
    // rather than silently coerced.
    const credits = parseLocaleNumber(String(data.get("credits") ?? ""), locale);
    if (credits === null) {
      setCode("VALIDATION_ERROR");
      return;
    }

    save.mutate({
      name: String(data.get("name") ?? ""),
      term: String(data.get("term") ?? "") || null,
      credits,
    });
  }

  return (
    <div className="rounded-xl border border-line bg-surface p-6">
      <PanelHeader
        title={course?.name ?? "…"}
        subtitle={course?.course_id}
        closeLabel={t("action.close")}
        onClose={onClose}
      />

      {loading && <p className="mt-4 text-sm text-subtle">…</p>}
      {error instanceof ApiError && (
        <p role="alert" className="mt-4 text-sm text-fail">
          {t(`error.${error.code}` as "error.unknown")}
        </p>
      )}

      {course && !editing && (
        <>
          <dl className="mt-6 space-y-3 text-sm">
            <Field label={t("course.term")} value={course.term ?? "—"} />
            <Field
              label={t("course.credits")}
              value={formatNumber(course.credits, locale)}
              numeric
            />
            <Field label={t("nav.profile")} value={course.teacher_name ?? "—"} />
            <Field
              label={t("enrollment.graded")}
              value={formatNumber(course.graded_count, locale)}
              numeric
            />
          </dl>

          <button
            type="button"
            onClick={() => setEditing(true)}
            className="mt-6 rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
          >
            {t("action.edit")}
          </button>

          <h3 className="mt-8 text-sm font-medium text-text">{t("enrollment.other")}</h3>
          <ul className="mt-3 divide-y divide-line rounded-lg border border-line">
            {(register.data ?? []).map((entry) => (
              <li
                key={entry.student_id}
                className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
              >
                <span className="min-w-0 truncate text-text">
                  {entry.first_name} {entry.last_name}
                </span>
                {/* The distinction the schema was missing: enrolled and graded are
                    not the same state, and only this view shows the difference. */}
                <span className="numeric shrink-0 text-xs text-subtle">
                  {entry.grade_count > 0
                    ? `${formatNumber(entry.grade_count, locale)} ${t("grade.other")}`
                    : t("enrollment.notAssessed")}
                </span>
              </li>
            ))}
            {register.data?.length === 0 && (
              <li className="px-3 py-4 text-center text-sm text-subtle">
                {t("stats.noData")}
              </li>
            )}
          </ul>

          <InsightBlock entityType="course" entityId={courseId} />
        </>
      )}

      {course && editing && (
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <Input name="name" label={t("course.one")} value={course.name} />
          <Input name="term" label={t("course.term")} value={course.term ?? ""} required={false} />
          <Input
            name="credits"
            label={t("course.credits")}
            value={formatNumber(course.credits, locale)}
            inputMode="decimal"
          />

          {code && (
            <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
              {t(`error.${code}` as "error.unknown")}
            </p>
          )}

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={save.isPending}
              className="rounded-lg bg-brand px-3 py-1.5 text-sm text-brand-contrast transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {t("action.save")}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setCode(null);
              }}
              className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
            >
              {t("action.cancel")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
