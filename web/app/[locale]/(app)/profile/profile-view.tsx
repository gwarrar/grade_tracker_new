"use client";

/**
 * Profile: identity, password, and the devices this account is signed in on.
 *
 * "Change my password" and "sign out my other devices" are the baseline of any
 * account system — shipping authentication without them is shipping half of it.
 * The session list is the honest version of that second one: it names each device
 * rather than offering a single opaque button.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Field } from "@/components/app/detail-fields";
import { api, ApiError, type Response } from "@/lib/api";
import type { Me } from "@/lib/session";
import { formatDate } from "@/lib/format";

type Session = Response<"/profile/sessions", "get">[number];

export function ProfileView({ me, locale }: { me: Me; locale: string }) {
  const t = useTranslations();

  return (
    <div className="mx-auto max-w-2xl space-y-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          {t("profile.title")}
        </h1>
        <dl className="mt-6 space-y-3 rounded-xl border border-line bg-surface p-6 text-sm">
          <Field label={t("profile.name")} value={me.full_name} />
          <Field label={t("auth.email")} value={me.email} />
          <Field label={t("profile.role")} value={t(`role.${me.role}` as "role.student")} />
          {me.student_id && (
            <Field label={t("student.id")} value={me.student_id} numeric />
          )}
        </dl>
      </div>

      <PasswordSection />
      <SessionsSection locale={locale} />
    </div>
  );
}

function PasswordSection() {
  const t = useTranslations();
  const [code, setCode] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const change = useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api("/profile/password", { method: "POST", body }),
    onSuccess: () => {
      setDone(true);
      setCode(null);
    },
    onError: (err) => {
      setDone(false);
      setCode(err instanceof ApiError ? err.code : "NETWORK_ERROR");
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const next = String(data.get("new_password") ?? "");

    // Checked here rather than server-side: the backend has no business knowing
    // the field was typed twice, and a round trip to say "these differ" is a round
    // trip that tells the user nothing they could not be told instantly.
    if (next !== String(data.get("confirm_password") ?? "")) {
      setDone(false);
      setCode("__mismatch");
      return;
    }

    setCode(null);
    change.mutate(
      { current_password: String(data.get("current_password") ?? ""), new_password: next },
      { onSuccess: () => form.reset() },
    );
  }

  return (
    <section>
      <h2 className="text-lg font-medium text-text">{t("profile.changePassword")}</h2>

      <form onSubmit={onSubmit} className="mt-4 space-y-4 rounded-xl border border-line bg-surface p-6">
        <Secret name="current_password" label={t("profile.currentPassword")} autoComplete="current-password" />
        <Secret name="new_password" label={t("profile.newPassword")} autoComplete="new-password" />
        <Secret name="confirm_password" label={t("profile.confirmPassword")} autoComplete="new-password" />

        {code && (
          <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
            {code === "__mismatch"
              ? t("profile.mismatch")
              : t(`error.${code}` as "error.unknown")}
          </p>
        )}
        {done && (
          <p role="status" className="rounded-lg bg-pass-bg px-3 py-2 text-sm text-pass">
            {t("profile.passwordChanged")}
          </p>
        )}

        <button
          type="submit"
          disabled={change.isPending}
          className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-brand-contrast transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {t("action.save")}
        </button>
      </form>
    </section>
  );
}

function SessionsSection({ locale }: { locale: string }) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const sessions = useQuery({
    queryKey: ["profile", "sessions"],
    queryFn: () => api<Session[]>("/profile/sessions"),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["profile", "sessions"] });

  const revoke = useMutation({
    mutationFn: (token: string) =>
      api(`/profile/sessions/${token}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  const revokeOthers = useMutation({
    mutationFn: () => api("/profile/sessions/revoke-others", { method: "POST" }),
    onSuccess: refresh,
  });

  const rows = sessions.data ?? [];
  const others = rows.filter((session) => !session.is_current).length;

  return (
    <section>
      <h2 className="text-lg font-medium text-text">{t("profile.sessions")}</h2>

      <ul className="mt-4 divide-y divide-line rounded-xl border border-line bg-surface">
        {rows.map((session) => (
          <li key={session.token_sha256} className="flex items-center gap-4 px-6 py-4">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-text">
                {session.user_agent || "—"}
                {session.is_current && (
                  <span className="ms-2 rounded bg-bg-subtle px-1.5 py-0.5 text-xs text-subtle">
                    {t("profile.thisDevice")}
                  </span>
                )}
              </p>
              <p className="numeric mt-0.5 text-xs text-subtle">
                {session.ip_address} · {t("profile.lastSeen")}{" "}
                {formatDate(session.last_seen_at ?? session.created_at, locale)}
              </p>
            </div>

            {/* The current session is revoked by signing out, not from this list —
                a button that logs you out while labelled the same as five others
                is a trap. */}
            {!session.is_current && (
              <button
                type="button"
                onClick={() => revoke.mutate(session.token_sha256)}
                disabled={revoke.isPending}
                className="shrink-0 rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text disabled:opacity-60"
              >
                {t("profile.revoke")}
              </button>
            )}
          </li>
        ))}

        {sessions.isPending && (
          <li className="px-6 py-8 text-center text-sm text-subtle">…</li>
        )}
      </ul>

      {others > 0 && (
        <button
          type="button"
          onClick={() => revokeOthers.mutate()}
          disabled={revokeOthers.isPending}
          className="mt-4 rounded-lg border border-line px-4 py-2 text-sm text-muted transition-colors hover:text-text disabled:opacity-60"
        >
          {t("profile.revokeOthers")}
        </button>
      )}
    </section>
  );
}

function Secret({
  name,
  label,
  autoComplete,
}: {
  name: string;
  label: string;
  autoComplete: string;
}) {
  return (
    <div>
      <label htmlFor={name} className="block text-sm text-muted">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type="password"
        required
        autoComplete={autoComplete}
        className="mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
      />
    </div>
  );
}
