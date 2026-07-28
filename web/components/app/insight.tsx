"use client";

/**
 * A generated summary of a course's or student's performance.
 *
 * Loaded on demand, never automatically. Generating an insight the moment a panel
 * opens would bill for every idle click, and most panels are opened to read a
 * figure rather than a narrative.
 *
 * The cache badge is shown deliberately. An administrator reading the usage page
 * should be able to reconcile it with what the interface actually did.
 */

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { api, ApiError, type Response } from "@/lib/api";

type Insight = Response<"/ai/insight/{entity_type}/{entity_id}", "get">;

const RISK_STYLE: Record<string, string> = {
  none: "bg-pass-bg text-pass",
  low: "bg-pass-bg text-pass",
  medium: "bg-warn-bg text-warn",
  high: "bg-fail-bg text-fail",
};

export function InsightBlock({
  entityType,
  entityId,
}: {
  entityType: "course" | "student";
  entityId: string;
}) {
  const t = useTranslations("assistant");
  const tError = useTranslations("error");
  const [code, setCode] = useState<string | null>(null);

  const generate = useMutation({
    mutationFn: () => api<Insight>(`/ai/insight/${entityType}/${entityId}`),
    onSuccess: () => setCode(null),
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  const insight = generate.data;

  return (
    <section className="mt-8 border-t border-line pt-6">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-sm font-medium text-text">{t("insight")}</h3>
        <button
          type="button"
          onClick={() => generate.mutate()}
          disabled={generate.isPending}
          className="rounded-lg border border-line px-3 py-1.5 text-xs text-muted transition-colors hover:text-text disabled:opacity-60"
        >
          {generate.isPending
            ? t("thinking")
            : insight
              ? t("regenerate")
              : t("insight")}
        </button>
      </div>

      {code && (
        <p role="alert" className="mt-3 rounded-lg bg-fail-bg px-3 py-2 text-xs text-fail">
          {tError(code as "unknown")}
        </p>
      )}

      {insight && (
        <div aria-live="polite" className="mt-4 space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded px-2 py-0.5 text-xs ${RISK_STYLE[insight.risk_level] ?? "bg-bg-subtle text-subtle"}`}
            >
              {t(`risk.${insight.risk_level}` as "risk.none")}
            </span>
            <span className="rounded bg-bg-subtle px-2 py-0.5 text-xs text-subtle">
              {t(`trend.${insight.trend}` as "trend.unknown")}
            </span>
            {insight.cached && (
              <span className="text-xs text-subtle">{t("cached")}</span>
            )}
          </div>

          <p className="leading-relaxed text-text">{insight.summary}</p>

          {insight.factors.length > 0 && (
            <div>
              <h4 className="text-xs font-medium uppercase tracking-wide text-subtle">
                {t("factors")}
              </h4>
              <ul className="mt-1.5 space-y-1 text-muted">
                {insight.factors.map((factor) => (
                  <li key={factor} className="flex gap-2">
                    <span aria-hidden className="text-subtle">
                      —
                    </span>
                    {factor}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {insight.suggested_actions.length > 0 && (
            <div>
              <h4 className="text-xs font-medium uppercase tracking-wide text-subtle">
                {t("actions")}
              </h4>
              <ul className="mt-1.5 space-y-1 text-muted">
                {insight.suggested_actions.map((action) => (
                  <li key={action} className="flex gap-2">
                    <span aria-hidden className="text-subtle">
                      —
                    </span>
                    {action}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
