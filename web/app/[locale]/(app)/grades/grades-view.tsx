"use client";

/**
 * Grades list with the sliding detail panel.
 *
 * This is the page where locale number handling stops being cosmetic. A German
 * user types `88,5`; parsed with `Number()` that is `NaN`, and parsed by stripping
 * the comma it is `885`. Both are wrong, and only one of them is obviously wrong.
 * Every figure goes through `parseLocaleNumber`, which returns null rather than
 * guessing.
 *
 * The edit is optimistic: the score updates on screen immediately and rolls back
 * if the server rejects it. Correcting a mistyped grade is the single most common
 * action here, and a round trip per keystroke-worth of correction is what makes an
 * interface feel slow.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Field, Input, PanelHeader } from "@/components/app/detail-fields";
import { MasterDetail } from "@/components/app/master-detail";
import { api, ApiError, type Response } from "@/lib/api";
import { formatDate, formatNumber, formatPercent, parseLocaleNumber } from "@/lib/format";
import { useDebounced, useSelection } from "@/lib/use-selection";

type Grade = Response<"/grades/{grade_id}", "get">;
type Page = Response<"/grades", "get">;

const PAGE_SIZE = 50;

export function GradesView({ locale }: { locale: string }) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const [selectedId, select] = useSelection();
  const [search, setSearch] = useState("");
  const query = useDebounced(search.trim());

  const list = useQuery({
    queryKey: ["grades", { q: query }],
    queryFn: () => api<Page>("/grades", { query: { q: query, size: PAGE_SIZE } }),
    placeholderData: (previous) => previous,
  });

  const detail = useQuery({
    queryKey: ["grade", selectedId],
    queryFn: () => api<Grade>(`/grades/${selectedId}`),
    enabled: selectedId !== null,
  });

  const rows = list.data?.items ?? [];

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          {t("grade.other")}
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
            <GradeDetail
              key={selectedId}
              gradeId={selectedId}
              grade={detail.data}
              loading={detail.isPending}
              error={detail.error}
              locale={locale}
              onClose={() => select(null)}
              onSaved={() => {
                void queryClient.invalidateQueries({ queryKey: ["grade", selectedId] });
                void queryClient.invalidateQueries({ queryKey: ["grades"] });
              }}
            />
          )
        }
      >
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("grade.other")}</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-subtle">
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("student.one")}
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("grade.title")}
                </th>
                <th scope="col" className="px-4 py-2.5 text-end font-medium">
                  {t("grade.percentage")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((grade) => {
                const active = String(grade.grade_id) === selectedId;
                return (
                  <tr
                    key={grade.grade_id}
                    className={`border-b border-line last:border-0 transition-colors ${
                      active ? "bg-bg-subtle" : "hover:bg-bg-subtle"
                    }`}
                  >
                    <td className="px-4 py-0">
                      <button
                        type="button"
                        onClick={() => select(String(grade.grade_id))}
                        aria-current={active ? "true" : undefined}
                        className="-mx-4 w-[calc(100%+2rem)] px-4 py-2.5 text-start text-text outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
                      >
                        {grade.student_name}
                      </button>
                    </td>
                    <td className="truncate px-4 py-2.5 text-muted">{grade.title}</td>
                    <td className="numeric px-4 py-2.5 text-end">
                      {/* Colour is not the only signal — the pass/fail word is in the
                          panel, and the figure itself carries the meaning. A red
                          number alone excludes anyone who cannot distinguish it. */}
                      <span className={grade.is_passing ? "text-text" : "text-fail"}>
                        {formatPercent(grade.percentage, locale)}
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

function GradeDetail({
  gradeId,
  grade,
  loading,
  error,
  locale,
  onClose,
  onSaved,
}: {
  gradeId: string;
  grade: Grade | undefined;
  loading: boolean;
  error: unknown;
  locale: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/grades/${gradeId}`, { method: "PATCH", body }),

    // Optimistic: write the new figures into the cache before the request lands.
    onMutate: async (body) => {
      const key = ["grade", gradeId];
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<Grade>(key);

      if (previous && typeof body.score === "number") {
        const percentage = (body.score / previous.max_grade) * 100;
        queryClient.setQueryData<Grade>(key, {
          ...previous,
          score: body.score,
          percentage,
          title: String(body.title ?? previous.title),
        });
      }
      return { previous };
    },

    onError: (err, _body, context) => {
      // Roll back to exactly what was there, rather than refetching — the server
      // never accepted the change, so the old value is still correct.
      if (context?.previous) {
        queryClient.setQueryData(["grade", gradeId], context.previous);
      }
      setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR");
    },

    onSuccess: () => {
      setEditing(false);
      setCode(null);
      onSaved();
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);

    const score = parseLocaleNumber(String(data.get("score") ?? ""), locale);
    const weight = parseLocaleNumber(String(data.get("weight") ?? ""), locale);

    // Reported, not coerced. `Number("88,5")` is NaN and would have been sent as
    // null; stripping the separator would have sent 885.
    if (score === null || weight === null) {
      setCode("VALIDATION_ERROR");
      return;
    }

    save.mutate({
      score,
      weight,
      title: String(data.get("title") ?? ""),
      notes: String(data.get("notes") ?? ""),
    });
  }

  return (
    <div className="rounded-xl border border-line bg-surface p-6">
      <PanelHeader
        title={grade?.student_name ?? "…"}
        subtitle={grade && `${grade.course_id} · ${grade.title}`}
        closeLabel={t("action.close")}
        onClose={onClose}
      />

      {loading && <p className="mt-4 text-sm text-subtle">…</p>}
      {error instanceof ApiError && (
        <p role="alert" className="mt-4 text-sm text-fail">
          {t(`error.${error.code}` as "error.unknown")}
        </p>
      )}

      {grade && !editing && (
        <>
          <dl className="mt-6 space-y-3 text-sm">
            <Field
              label={t("grade.score")}
              value={`${formatNumber(grade.score, locale)} / ${formatNumber(grade.max_grade, locale)}`}
              numeric
            />
            <Field
              label={t("grade.percentage")}
              value={formatPercent(grade.percentage, locale)}
              numeric
            />
            <Field
              label={t("stats.average")}
              value={
                <span className={grade.is_passing ? "text-pass" : "text-fail"}>
                  {grade.is_passing ? t("grade.passing") : t("grade.failing")}
                </span>
              }
            />
            <Field label={t("grade.weight")} value={formatNumber(grade.weight, locale)} numeric />
            <Field label={t("grade.date")} value={formatDate(grade.date, locale)} numeric />
            <Field label={t("course.one")} value={grade.course_name} />
          </dl>

          {grade.notes && <p className="mt-4 text-sm text-muted">{grade.notes}</p>}

          <button
            type="button"
            onClick={() => setEditing(true)}
            className="mt-6 rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
          >
            {t("action.edit")}
          </button>
        </>
      )}

      {grade && editing && (
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <Input name="title" label={t("grade.title")} value={grade.title} />
          <Input
            name="score"
            label={t("grade.score")}
            value={formatNumber(grade.score, locale)}
            inputMode="decimal"
            // Spells out the maximum, so "88,5" is entered against a known scale
            // rather than guessed at.
            hint={`${t("grade.max")}: ${formatNumber(grade.max_grade, locale)}`}
          />
          <Input
            name="weight"
            label={t("grade.weight")}
            value={formatNumber(grade.weight, locale)}
            inputMode="decimal"
          />
          <Input
            name="notes"
            label={t("grade.notes")}
            value={grade.notes}
            required={false}
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
