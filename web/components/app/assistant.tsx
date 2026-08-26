"use client";

/**
 * The assistant, and the evidence behind what it says.
 *
 * The design decision that matters here is that the tool transcript is **not**
 * collapsed away by default when the answer contains figures. A confident
 * sentence with no visible source is indistinguishable from a correct one; the
 * same sentence sitting above the rows it came from can be checked in a glance.
 *
 * Nothing here can write. `/ai/command` returns a *proposal*, and the confirm
 * card below submits it through the ordinary endpoint, with the ordinary
 * validation and the ordinary audit entry.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { api, ApiError, type Response } from "@/lib/api";
import { academicRoots } from "@/lib/query-keys";

type Answer = Response<"/ai/ask", "post">;
type Proposal = Response<"/ai/command", "post">;
type ToolRecord = Answer["records"][number];

/**
 * Ask a question and show the answer with its sources.
 *
 * @param onClose - Called when the panel should close.
 */
export function AssistantPanel({ onClose }: { onClose: () => void }) {
  const t = useTranslations("assistant");
  const tError = useTranslations("error");
  const tAction = useTranslations("action");
  const reduced = useReducedMotion();
  const [code, setCode] = useState<string | null>(null);

  const ask = useMutation({
    mutationFn: (question: string) =>
      api<Answer>("/ai/ask", { method: "POST", body: { question } }),
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
    onSuccess: () => setCode(null),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = String(new FormData(event.currentTarget).get("question") ?? "").trim();
    if (question) ask.mutate(question);
  }

  const answer = ask.data;

  return (
    <div className="rounded-xl border border-line bg-surface p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-medium text-text">{t("ask")}</h2>
          {/* Stated up front, not buried in settings. The person typing a
              student's name deserves to know where it is going. */}
          <p className="mt-1 text-xs text-subtle">{t("privacy")}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={tAction("close")}
          className="rounded-md px-2 py-1 text-lg leading-none text-subtle transition-colors hover:text-text"
        >
          ×
        </button>
      </div>

      <form onSubmit={onSubmit} className="mt-4 flex gap-2">
        <input
          name="question"
          // The panel opens only on an explicit click, and asking a question is the
          // single thing it is for: focus follows the action the user just took
          // rather than jumping unbidden.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          placeholder={t("askPlaceholder")}
          className="flex-1 rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
        />
        <button
          type="submit"
          disabled={ask.isPending}
          className="shrink-0 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-brand-contrast transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {ask.isPending ? t("thinking") : t("ask")}
        </button>
      </form>

      {code && (
        <p role="alert" className="mt-4 rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
          {tError(code as "unknown")}
        </p>
      )}

      <AnimatePresence mode="wait">
        {answer && (
          <motion.div
            key={answer.text}
            initial={reduced ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="mt-5"
          >
            {/* aria-live, because the answer arrives without any focus change —
                a screen-reader user would otherwise never learn it had. */}
            <p aria-live="polite" className="text-sm leading-relaxed text-text">
              {answer.text}
            </p>

            {answer.reasoning && (
              <details className="mt-4 rounded-lg border border-line bg-bg-subtle px-3 py-2">
                <summary className="cursor-pointer text-xs font-medium text-muted hover:text-text">
                  {t("reasoning")}
                </summary>
                <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-subtle">
                  {answer.reasoning}
                </p>
              </details>
            )}

            {answer.truncated && (
              <p
                role="note"
                className="mt-3 rounded-lg border border-warn/40 bg-warn-bg px-3 py-2 text-xs text-warn"
              >
                {t("truncated")}
              </p>
            )}

            {answer.records.length > 0 && <Sources records={answer.records} />}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** The queries behind an answer, rendered as tables rather than JSON. */
function Sources({ records }: { records: ToolRecord[] }) {
  const t = useTranslations("assistant");

  return (
    <section className="mt-6 border-t border-line pt-4">
      <h3 className="text-xs font-medium uppercase tracking-wide text-subtle">
        {t("sources")}
      </h3>
      <p className="mt-1 text-xs text-subtle">{t("sourcesHint")}</p>

      <div className="mt-3 space-y-4">
        {records.map((record, index) => (
          <div key={`${record.tool}-${index}`}>
            <p className="numeric text-xs text-muted">
              {record.tool}
              {Object.keys(record.arguments).length > 0 && (
                <span className="text-subtle"> {JSON.stringify(record.arguments)}</span>
              )}
            </p>
            <ResultTable result={record.result} />
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * Render a tool result as a table when it is row-shaped, and as key/value pairs
 * otherwise.
 *
 * Not a JSON dump: the point of showing the evidence is that a teacher can read
 * it, and a teacher does not read JSON.
 */
function ResultTable({ result }: { result: Record<string, unknown> }) {
  // The array-valued key, if any, is the rows. Both `grades` and `results` are
  // shaped this way, so the component does not need to know which tool ran.
  const rowsEntry = Object.entries(result).find(
    ([, value]) => Array.isArray(value) && value.length > 0,
  );

  if (result.error) {
    return (
      <p className="numeric mt-1 rounded bg-fail-bg px-2 py-1 text-xs text-fail">
        {String(result.error)}
      </p>
    );
  }

  if (!rowsEntry) {
    const pairs = Object.entries(result).filter(([, value]) => value !== null);
    return (
      <dl className="mt-1 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
        {pairs.map(([key, value]) => (
          <div key={key} className="flex justify-between gap-2 border-b border-line py-0.5">
            <dt className="text-subtle">{key}</dt>
            <dd className="numeric text-text">{formatCell(value)}</dd>
          </div>
        ))}
      </dl>
    );
  }

  const rows = rowsEntry[1] as Record<string, unknown>[];
  const columns = Object.keys(rows[0]);

  return (
    <div className="mt-1 overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-line text-left text-subtle">
            {columns.map((column) => (
              <th key={column} scope="col" className="px-2 py-1 font-medium">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-b border-line last:border-0">
              {columns.map((column) => (
                <td key={column} className="numeric px-2 py-1 text-muted">
                  {formatCell(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Render one cell, without letting an object become "[object Object]". */
function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * A proposed action, awaiting confirmation.
 *
 * The palette hands this whatever `/ai/command` returned. Confirming submits it
 * through the ordinary endpoint — same validation, same audit entry, same
 * permissions. The assistant's only privilege is filling in the form.
 */
export function ConfirmCard({
  proposal,
  onDone,
  onCancel,
}: {
  proposal: Proposal;
  onDone: () => void;
  onCancel: () => void;
}) {
  const t = useTranslations("assistant");
  const tError = useTranslations("error");
  const tAction = useTranslations("action");
  const queryClient = useQueryClient();
  const [code, setCode] = useState<string | null>(null);

  const perform = useMutation({
    mutationFn: () => {
      // Routed to the real endpoint. There is no "apply what the AI said" API,
      // deliberately — that would be a second write path with different rules.
      switch (proposal.action) {
        case "record_grade":
          return api("/grades", { method: "POST", body: proposal.params });
        case "enrol_student": {
          const { course_id: courseId, ...rest } = proposal.params as Record<string, unknown>;
          return api(`/courses/${String(courseId)}/enrollments`, {
            method: "POST",
            body: rest,
          });
        }
        default:
          throw new ApiError("VALIDATION_ERROR", 422);
      }
    },
    onSuccess: () => {
      // The palette can propose a write to any academic entity, so it refreshes the
      // same set a list screen does -- but still not the admin screens, which no
      // proposed action can reach.
      for (const queryKey of academicRoots) void queryClient.invalidateQueries({ queryKey });
      onDone();
    },
    onError: (error) => setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR"),
  });

  if (!proposal.action) {
    return <p className="p-4 text-sm text-muted">{proposal.message}</p>;
  }

  return (
    <div className="p-4">
      <h3 className="text-sm font-medium text-text">
        {t(`action.${proposal.action}` as "action.record_grade")}
      </h3>
      <p className="mt-1 text-xs text-subtle">{t("confirmHint")}</p>

      <dl className="mt-3 space-y-1 rounded-lg bg-bg-subtle px-3 py-2 text-sm">
        {Object.entries(proposal.params).map(([key, value]) => (
          <div key={key} className="flex justify-between gap-4">
            <dt className="text-subtle">{key}</dt>
            <dd className="numeric text-text">{formatCell(value)}</dd>
          </div>
        ))}
      </dl>

      {code && (
        <p role="alert" className="mt-3 rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
          {tError(code as "unknown")}
        </p>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={() => perform.mutate()}
          disabled={perform.isPending}
          className="rounded-lg bg-brand px-3 py-1.5 text-sm text-brand-contrast transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {t("confirm")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
        >
          {tAction("cancel")}
        </button>
      </div>
    </div>
  );
}
