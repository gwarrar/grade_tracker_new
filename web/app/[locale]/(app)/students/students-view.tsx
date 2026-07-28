"use client";

/**
 * Students list with the sliding detail panel.
 *
 * Selection lives in the URL (`?id=S001`), not in component state. That single
 * decision is what makes a selected student linkable, makes the Back button close
 * the panel, and survives a refresh — none of which `useState` gives you.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { MasterDetail } from "@/components/app/master-detail";
import { usePathname, useRouter } from "@/i18n/navigation";
import { api, ApiError, type Response } from "@/lib/api";
import { formatNumber } from "@/lib/format";

type Student = Response<"/students/{student_id}", "get">;
type Page = Response<"/students", "get">;

const PAGE_SIZE = 50;

export function StudentsView({ locale }: { locale: string }) {
  const t = useTranslations();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const queryClient = useQueryClient();

  const selectedId = params.get("id");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");

  // Debounced, so typing six characters is one request rather than six. 250ms is
  // below the threshold where a search field feels laggy and above the interval
  // between keystrokes.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const list = useQuery({
    queryKey: ["students", { q: query }],
    queryFn: () => api<Page>("/students", { query: { q: query, size: PAGE_SIZE } }),
    // Keeps the previous rows on screen while a new search resolves, instead of
    // collapsing the table to a spinner on every keystroke.
    placeholderData: (previous) => previous,
  });

  const detail = useQuery({
    queryKey: ["student", selectedId],
    queryFn: () => api<Student>(`/students/${selectedId}`),
    enabled: selectedId !== null,
  });

  function select(id: string | null) {
    // `scroll: false`, or the browser jumps to the top and the row you clicked
    // leaves the viewport just as the panel opens.
    router.push(id ? `${pathname}?id=${encodeURIComponent(id)}` : pathname, {
      scroll: false,
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
            <StudentDetail
              key={selectedId}
              student={detail.data}
              loading={detail.isPending}
              error={detail.error}
              onClose={() => select(null)}
              onSaved={() => {
                // Both caches: the panel shows the new name, and so does the row
                // behind it.
                void queryClient.invalidateQueries({ queryKey: ["student", selectedId] });
                void queryClient.invalidateQueries({ queryKey: ["students"] });
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
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("student.id")}
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("student.one")}
                </th>
                <th scope="col" className="px-4 py-2.5 text-end font-medium">
                  {t("grade.other")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((student) => {
                const active = student.student_id === selectedId;
                return (
                  <tr
                    key={student.student_id}
                    // The row is a <tr> with a <button> inside rather than a
                    // clickable <tr>: a table row is not focusable and not
                    // announced as actionable, so keyboard users could not open a
                    // record at all.
                    className={`border-b border-line last:border-0 transition-colors ${
                      active ? "bg-bg-subtle" : "hover:bg-bg-subtle"
                    }`}
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
                    <td className="px-4 py-2.5 text-text">
                      {student.first_name} {student.last_name}
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
            <p className="px-4 py-8 text-center text-sm text-subtle">…</p>
          )}
          {!list.isPending && rows.length === 0 && (
            <p className="px-4 py-8 text-center text-sm text-subtle">{t("stats.noData")}</p>
          )}
        </div>
      </MasterDetail>
    </>
  );
}

/** The detail panel: read-only until Edit, then a form that PATCHes. */
function StudentDetail({
  student,
  loading,
  error,
  onClose,
  onSaved,
}: {
  student: Student | undefined;
  loading: boolean;
  error: unknown;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations();
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (body: Record<string, string>) =>
      api(`/students/${student?.student_id}`, { method: "PATCH", body }),
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
    save.mutate({
      first_name: String(data.get("first_name") ?? ""),
      last_name: String(data.get("last_name") ?? ""),
      email: String(data.get("email") ?? ""),
    });
  }

  return (
    <div className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          {loading && <p className="text-sm text-subtle">…</p>}
          {student && (
            <>
              <h2 className="truncate text-lg font-medium text-text">
                {student.first_name} {student.last_name}
              </h2>
              <p className="numeric mt-0.5 text-sm text-subtle">{student.student_id}</p>
            </>
          )}
          {error instanceof ApiError && (
            <p role="alert" className="text-sm text-fail">
              {t(`error.${error.code}` as "error.unknown")}
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={onClose}
          aria-label={t("action.close")}
          className="rounded-md px-2 py-1 text-lg leading-none text-subtle transition-colors hover:text-text"
        >
          ×
        </button>
      </div>

      {student && !editing && (
        <>
          <dl className="mt-6 space-y-3 text-sm">
            <Field label={t("auth.email")} value={student.email} />
            <Field label={t("course.other")} value={String(student.enrolled_count)} numeric />
            <Field label={t("grade.other")} value={String(student.grade_count)} numeric />
          </dl>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="mt-6 rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
          >
            {t("action.edit")}
          </button>
        </>
      )}

      {student && editing && (
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <Input name="first_name" label={t("student.firstName")} value={student.first_name} />
          <Input name="last_name" label={t("student.lastName")} value={student.last_name} />
          <Input name="email" label={t("auth.email")} value={student.email} type="email" />

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

function Field({
  label,
  value,
  numeric,
}: {
  label: string;
  value: string;
  numeric?: boolean;
}) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-subtle">{label}</dt>
      <dd className={`truncate text-text ${numeric ? "numeric" : ""}`}>{value}</dd>
    </div>
  );
}

function Input({
  name,
  label,
  value,
  type = "text",
}: {
  name: string;
  label: string;
  value: string;
  type?: string;
}) {
  return (
    <div>
      <label htmlFor={name} className="block text-sm text-muted">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        // Uncontrolled with a default: the form is remounted per student by the
        // `key` on the panel, so there is no stale value to guard against and no
        // re-render per keystroke.
        defaultValue={value}
        required
        className="mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
      />
    </div>
  );
}
