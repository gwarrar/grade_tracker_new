"use client";

/**
 * The institution-wide activity feed.
 *
 * Read-only by construction: the trail is append-only at the database level, so
 * this page renders no write controls at all — only filters, paging and the
 * record of what happened.
 *
 * Filters and the page number live in the URL, exactly as the grades list does:
 * a filtered feed is linkable, Back steps through filter changes, and a refresh
 * keeps what you were looking at.
 */

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { AuditEntryLine } from "@/components/app/audit";
import { Pager } from "@/components/app/pager";
import { api, ApiError, type Response } from "@/lib/api";
import { useErrorMessage } from "@/lib/use-api-error";
import { queryKeys } from "@/lib/query-keys";
import { formatNumber } from "@/lib/format";
import { useUrlParam } from "@/lib/use-selection";

type Feed = Response<"/audit", "get">;

const PAGE_SIZE = 25;

/** The entity kinds the trail records, for the filter. */
const ENTITIES = [
  "grade",
  "student",
  "course",
  "enrollment",
  "user",
  "note",
  "organization",
  "i18n_override",
  "ai_provider",
  "ai_routing",
] as const;

const ACTIONS = ["create", "update", "delete"] as const;

export function AuditView({ locale }: { locale: string }) {
  const t = useTranslations();
  const tError = useErrorMessage();

  const [entity, setEntity] = useUrlParam("entity");
  const [action, setAction] = useUrlParam("action");
  const [dateFrom, setDateFrom] = useUrlParam("date_from");
  const [dateTo, setDateTo] = useUrlParam("date_to");
  const [pageParam, setPage] = useUrlParam("page", "1");
  const page = Math.max(1, Number(pageParam) || 1);

  const filtered = Boolean(entity || action || dateFrom || dateTo);

  const feed = useQuery({
    queryKey: queryKeys.audit.list({ entity, action, dateFrom, dateTo, page }),
    queryFn: () =>
      api<Feed>("/audit", {
        query: {
          size: PAGE_SIZE,
          page,
          // Empty strings would become `?entity=` and filter on nothing.
          ...(entity ? { entity } : {}),
          ...(action ? { action } : {}),
          ...(dateFrom ? { date_from: dateFrom } : {}),
          ...(dateTo ? { date_to: dateTo } : {}),
        },
      }),
    placeholderData: (previous) => previous,
  });

  /** The entity kind as a label, falling back to the raw name for future kinds. */
  const entityLabel = (kind: string): string =>
    (ENTITIES as readonly string[]).includes(kind)
      ? t(`audit.entity.${kind}` as "audit.entity.grade")
      : kind;

  return (
    <>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          {t("admin.audit.title")}
          {feed.data && (
            <span className="numeric ms-3 text-base font-normal text-subtle">
              {formatNumber(feed.data.total, locale)}
            </span>
          )}
        </h1>
      </div>

      <p className="mb-4 text-sm text-muted">{t("admin.audit.intro")}</p>

      <fieldset className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-line bg-surface px-4 py-3">
        <legend className="sr-only">{t("filter.label")}</legend>

        <label className="flex flex-col gap-1 text-xs text-subtle">
          {t("audit.entityLabel")}
          <select
            value={entity}
            onChange={(event) => setEntity(event.target.value)}
            className="w-48 rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          >
            <option value="">{t("filter.all")}</option>
            {ENTITIES.map((kind) => (
              <option key={kind} value={kind}>
                {t(`audit.entity.${kind}` as "audit.entity.grade")}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-subtle">
          {t("audit.actionLabel")}
          <select
            value={action}
            onChange={(event) => setAction(event.target.value)}
            className="w-36 rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          >
            <option value="">{t("filter.all")}</option>
            {ACTIONS.map((verb) => (
              <option key={verb} value={verb}>
                {t(`audit.action.${verb}` as "audit.action.create")}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-subtle">
          {t("filter.from")}
          <input
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
            className="rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-subtle">
          {t("filter.to")}
          <input
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
            className="rounded-lg border border-line bg-bg px-2 py-1.5 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
          />
        </label>

        {filtered && (
          <button
            type="button"
            onClick={() => {
              setEntity(null);
              setAction(null);
              setDateFrom(null);
              setDateTo(null);
            }}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
          >
            {t("filter.clear")}
          </button>
        )}
      </fieldset>

      <div className="overflow-hidden rounded-xl border border-line bg-surface">
        {feed.isPending && (
          <p className="px-4 py-8 text-center text-sm text-subtle">{t("stats.loading")}</p>
        )}
        {feed.error instanceof ApiError && (
          <p role="alert" className="px-4 py-8 text-center text-sm text-fail">
            {tError(feed.error.code)}
          </p>
        )}
        {feed.isSuccess && feed.data.items.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-subtle">{t("stats.noData")}</p>
        )}
        {feed.isSuccess && feed.data.items.length > 0 && (
          <ul className="px-4">
            {feed.data.items.map((entry) => (
              <AuditEntryLine
                key={entry.id}
                entry={entry}
                locale={locale}
                prefix={`${entityLabel(entry.entity)} ${entry.entity_id}`}
              />
            ))}
          </ul>
        )}

        <Pager
          page={page}
          size={PAGE_SIZE}
          total={feed.data?.total ?? 0}
          locale={locale}
          labels={{
            previous: t("pager.previous"),
            next: t("pager.next"),
            status: (current, pages) => t("pager.page", { page: current, pages }),
          }}
          onPage={(next) => setPage(String(next))}
        />
      </div>
    </>
  );
}
