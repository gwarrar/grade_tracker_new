"use client";

/**
 * The one and only appearance of a generated password.
 *
 * The API returns these in the response that created them and never again — they
 * are stored hashed, so a lost one is replaced by a reset rather than recovered.
 * That makes this component the last chance to write them down, which is why it
 * is loud, offers a file for the bulk case, and does not dismiss itself.
 *
 * One component for one account and for four hundred, because the difference is a
 * row count. Three pages create accounts and all three showed a different thing
 * before this existed.
 */

import { useTranslations } from "next-intl";
import { useState } from "react";

import { toCsv } from "@/lib/csv";

export interface Credential {
  /** The sign-in address. */
  email: string;
  /** The generated password, in plain text, for this render only. */
  password: string;
  /** Who it belongs to, when a list of addresses is not enough to tell. */
  name?: string;
}

/** Above this many, the list scrolls rather than pushing the page down. */
const SCROLL_AFTER = 6;

export function CredentialsCard({
  title,
  rows,
  onDismiss,
}: {
  title: string;
  rows: Credential[];
  onDismiss: () => void;
}) {
  const t = useTranslations("credentials");
  const tAction = useTranslations("action");
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  if (rows.length === 0) return null;

  const csv = () =>
    toCsv([
      [t("name"), t("email"), t("password")],
      ...rows.map((row) => [row.name ?? "", row.email, row.password]),
    ]);

  function download() {
    // A Blob URL rather than a data: URI — a cohort of several hundred exceeds
    // what some browsers accept in an address.
    const url = URL.createObjectURL(new Blob([csv()], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "sign-in-details.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div role="status" className="rounded-xl border border-warn/40 bg-warn-bg p-5">
      <p className="text-sm font-medium text-warn">{title}</p>
      <p className="mt-1 text-xs text-warn">{t("once")}</p>
      <p className="mt-1 text-xs text-warn">{t("mustChange")}</p>

      <div
        className={`mt-3 space-y-1.5 ${
          rows.length > SCROLL_AFTER ? "max-h-64 overflow-y-auto pe-1" : ""
        }`}
      >
        {rows.map((row) => (
          <div key={row.email} className="flex flex-wrap items-center gap-3">
            <code className="numeric rounded bg-surface px-3 py-1.5 text-sm text-text">
              {row.password}
            </code>
            <span className="numeric min-w-0 truncate text-xs text-warn">
              {row.name ? `${row.name} · ` : ""}
              {row.email}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => {
            // `navigator.clipboard` is undefined outside a secure context, and a
            // school LAN deployment on plain http is exactly that. Unguarded this
            // threw in the handler and copied nothing, silently -- on the one card
            // whose whole purpose is that the password is never shown again.
            const only = rows.length === 1 ? rows[0] : undefined;
            const text = only ? only.password : csv();
            if (!navigator.clipboard) {
              setCopyFailed(true);
              return;
            }
            navigator.clipboard.writeText(text).then(
              () => setCopied(true),
              () => setCopyFailed(true),
            );
          }}
          className="rounded-lg border border-warn/40 px-2.5 py-1 text-xs text-warn transition-opacity hover:opacity-80"
        >
          {copyFailed ? t("copyFailed") : copied ? t("copied") : t("copy")}
        </button>
        {rows.length > 1 && (
          <button
            type="button"
            onClick={download}
            className="rounded-lg border border-warn/40 px-2.5 py-1 text-xs text-warn transition-opacity hover:opacity-80"
          >
            {t("download")}
          </button>
        )}
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-lg px-2.5 py-1 text-xs text-warn transition-opacity hover:opacity-80"
        >
          {tAction("close")}
        </button>
      </div>
    </div>
  );
}
