"use client";

/**
 * Read-only rendering of audit entries — with no write controls at all.
 *
 * The trail is append-only at the database level, so the honest way to display it
 * offers nothing to click: no edit, no delete, no retry. Each entry renders its
 * before/after snapshots as a compact field-level diff — a reader wants
 * "score 78 → 82", not a JSON blob.
 */

import { useTranslations } from "next-intl";

import type { components } from "@/lib/api-schema";
import { formatDate, formatNumber } from "@/lib/format";

export type AuditEntry = components["schemas"]["AuditEntryResponse"];
export type AuditFeedEntry = components["schemas"]["AuditFeedEntryResponse"];

/** One snapshot value as a reader wants to see it. */
function formatValue(value: unknown, locale: string): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return formatNumber(value, locale);
  if (typeof value === "string") return value === "" ? '""' : value;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * The fields that differ between the two snapshots.
 *
 * One function serves all three verbs: a create has no before, a delete has no
 * after, and an update reports only the keys that actually changed.
 */
function fieldChanges(entry: AuditEntry): { key: string; from: unknown; to: unknown }[] {
  const before = entry.before ?? {};
  const after = entry.after ?? {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
  return keys
    .map((key) => ({ key, from: before[key], to: after[key] }))
    .filter((change) => JSON.stringify(change.from) !== JSON.stringify(change.to));
}

/**
 * One entry: the action, who did it and when, followed by the field-level diff.
 *
 * @param entry - The audit entry to render.
 * @param locale - BCP-47 locale tag for the timestamp and figures.
 * @param prefix - Optional lead-in for the feed, where the entity is not known
 *   from context — e.g. the kind and id of the thing that changed.
 */
export function AuditEntryLine({
  entry,
  locale,
  prefix,
}: {
  entry: AuditEntry;
  locale: string;
  prefix?: string;
}) {
  const t = useTranslations();
  const actor = entry.actor_name ?? t("audit.system");

  return (
    <li className="border-b border-line py-3 last:border-0">
      <p className="text-sm text-text">
        {prefix && <span className="font-medium">{prefix} · </span>}
        {t(`audit.action.${entry.action}` as "audit.action.create")}
        <span className="text-subtle">
          {" · "}
          {actor}
        </span>
        <time dateTime={entry.at} className="numeric text-subtle">
          {" · "}
          {formatDate(entry.at, locale, { dateStyle: "medium", timeStyle: "short" })}
        </time>
      </p>
      <ul className="mt-1 space-y-0.5 text-sm text-muted">
        {fieldChanges(entry).map((change) => (
          <li key={change.key} className="numeric">
            <span className="font-mono text-xs text-subtle">{change.key}</span>{" "}
            {change.from === undefined ? (
              formatValue(change.to, locale)
            ) : change.to === undefined ? (
              formatValue(change.from, locale)
            ) : (
              <>
                {formatValue(change.from, locale)}
                <span aria-hidden> → </span>
                {formatValue(change.to, locale)}
              </>
            )}
          </li>
        ))}
      </ul>
    </li>
  );
}
