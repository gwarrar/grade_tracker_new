"use client";

/**
 * Account administration.
 *
 * The interesting behaviour is the API's, not this page's — no self-demotion, no
 * granting a role at or above your own, no removing the last superadmin. This
 * page's job is to make those refusals legible: it disables the controls it knows
 * will be refused, and translates the codes for the ones it cannot predict.
 *
 * Disabling is a courtesy, not the enforcement. Every rule is checked server-side
 * regardless of what this page renders.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { api, ApiError, type Response } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { atLeast, type Me, type Role } from "@/lib/session";
import { useDebounced } from "@/lib/use-selection";

type User = Response<"/admin/users", "get">[number];
type Created = Response<"/admin/users", "post">;

const ROLES: Role[] = ["student", "teacher", "admin", "superadmin"];

export function UsersView({ me, locale }: { me: Me; locale: string }) {
  const t = useTranslations("admin.users");
  const tError = useTranslations("error");
  const tAction = useTranslations("action");
  const tRole = useTranslations("role");
  const tAuth = useTranslations("auth");
  const tNav = useTranslations("nav");
  const tStats = useTranslations("stats");
  const tField = useTranslations("admin.ai");
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [includeInactive, setIncludeInactive] = useState(true);
  const [adding, setAdding] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [secret, setSecret] = useState<{ email: string; password: string } | null>(null);
  const query = useDebounced(search.trim());

  const users = useQuery({
    queryKey: ["admin", "users", { q: query, includeInactive }],
    queryFn: () =>
      api<User[]>("/admin/users", {
        query: { q: query, include_inactive: includeInactive },
      }),
    placeholderData: (previous) => previous,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
  const onError = (error: unknown) =>
    setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR");

  const create = useMutation({
    mutationFn: (body: Record<string, string>) =>
      api<Created>("/admin/users", { method: "POST", body }),
    onSuccess: (result) => {
      setAdding(false);
      setCode(null);
      setSecret({ email: result.user.email, password: result.initial_password });
      void refresh();
    },
    onError,
  });

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: number; role: string }) =>
      api(`/admin/users/${id}/role`, { method: "PUT", body: { role } }),
    onSuccess: () => {
      setCode(null);
      void refresh();
    },
    onError,
  });

  const setActive = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      api(`/admin/users/${id}/active`, { method: "PUT", body: { is_active: active } }),
    onSuccess: () => {
      setCode(null);
      void refresh();
    },
    onError,
  });

  const reset = useMutation({
    mutationFn: (user: User) =>
      api<{ temporary_password: string }>(`/admin/users/${user.id}/reset-password`, {
        method: "POST",
      }).then((result) => ({ email: user.email, password: result.temporary_password })),
    onSuccess: (result) => {
      setCode(null);
      setSecret(result);
      void refresh();
    },
    onError,
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setCode(null);
    create.mutate({
      email: String(data.get("email") ?? ""),
      full_name: String(data.get("full_name") ?? ""),
      role: String(data.get("role") ?? "teacher"),
    });
  }

  // What this account may grant. A superadmin may grant anything; anyone else may
  // grant only strictly below themselves — the same rule the service enforces.
  const grantable = ROLES.filter(
    (role) => me.role === "superadmin" || !atLeast(role, me.role as Role),
  );

  const rows = users.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text">{t("title")}</h1>
          <p className="mt-1 text-sm text-muted">{t("intro")}</p>
        </div>
        <button
          type="button"
          onClick={() => setAdding((current) => !current)}
          className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:text-text"
        >
          {adding ? tAction("cancel") : t("add")}
        </button>
      </div>

      {secret && (
        <OneTimePassword
          email={secret.email}
          password={secret.password}
          onDismiss={() => setSecret(null)}
        />
      )}

      {code && (
        <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
          {tError(code as "unknown")}
        </p>
      )}

      {adding && (
        <form
          onSubmit={onSubmit}
          className="grid gap-4 rounded-xl border border-line bg-surface p-6 sm:grid-cols-3"
        >
          <label className="block">
            <span className="block text-sm text-muted">{tField("name")}</span>
            <input
              name="full_name"
              required
              placeholder="Katrin Weber"
              className="mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text outline-none focus-visible:border-brand"
            />
          </label>
          <label className="block">
            <span className="block text-sm text-muted">{tAuth("email")}</span>
            <input
              name="email"
              type="email"
              required
              className="numeric mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text outline-none focus-visible:border-brand"
            />
          </label>
          <label className="block">
            <span className="block text-sm text-muted">{t("role")}</span>
            <select
              name="role"
              defaultValue="teacher"
              className="mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm text-text outline-none focus-visible:border-brand"
            >
              {grantable.map((role) => (
                <option key={role} value={role}>
                  {tRole(role)}
                </option>
              ))}
            </select>
          </label>
          <div className="sm:col-span-3">
            <button
              type="submit"
              disabled={create.isPending}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-brand-contrast transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {tAction("save")}
            </button>
          </div>
        </form>
      )}

      <div className="flex flex-wrap items-center gap-4">
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t("search")}
          aria-label={t("search")}
          className="w-64 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-text outline-none focus-visible:border-brand"
        />
        <label className="flex items-center gap-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(event) => setIncludeInactive(event.target.checked)}
            className="accent-[var(--brand-primary)]"
          />
          {t("showInactive")}
        </label>
      </div>

      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("title")}</caption>
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-subtle">
              <th scope="col" className="px-4 py-2.5 font-medium">
                {tNav("profile")}
              </th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("role")}
              </th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                {t("status")}
              </th>
              <th scope="col" className="px-4 py-2.5 text-end font-medium">
                {t("sessions")}
              </th>
              <th scope="col" className="px-4 py-2.5 text-end font-medium">
                <span className="sr-only">{tAction("edit")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((user) => {
              const isSelf = user.id === me.user_id;
              // Refusals this page can predict. The server checks all of them
              // again — this only avoids offering a button that cannot work.
              const outranksMe =
                me.role !== "superadmin" && atLeast(user.role, me.role as Role);
              const locked = isSelf || outranksMe;

              return (
                <tr key={user.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5">
                    <span className="text-text">{user.full_name}</span>
                    <span className="numeric ms-2 text-xs text-subtle">{user.email}</span>
                    {user.student_id && (
                      <span className="numeric ms-2 rounded bg-bg-subtle px-1.5 py-0.5 text-xs text-subtle">
                        {user.student_id}
                      </span>
                    )}
                  </td>

                  <td className="px-4 py-2.5">
                    <label className="sr-only" htmlFor={`role-${user.id}`}>
                      {t("role")}
                    </label>
                    <select
                      id={`role-${user.id}`}
                      value={user.role}
                      disabled={locked}
                      onChange={(event) =>
                        setRole.mutate({ id: user.id, role: event.target.value })
                      }
                      className="rounded-lg border border-line bg-bg px-2 py-1 text-sm text-text outline-none focus-visible:border-brand disabled:opacity-50"
                    >
                      {/* The current role is always present even when it is not
                          grantable, or the select would render blank for a
                          superadmin row viewed by an admin. */}
                      {[...new Set([user.role, ...grantable])].map((role) => (
                        <option key={role} value={role}>
                          {tRole(role as Role)}
                        </option>
                      ))}
                    </select>
                  </td>

                  <td className="px-4 py-2.5">
                    <span className={user.is_active ? "text-pass" : "text-subtle"}>
                      {user.is_active ? t("active") : t("inactive")}
                    </span>
                  </td>

                  <td className="numeric px-4 py-2.5 text-end text-muted">
                    {formatNumber(user.session_count, locale)}
                  </td>

                  <td className="px-4 py-2.5 text-end">
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        disabled={locked}
                        onClick={() => reset.mutate(user)}
                        className="rounded-lg border border-line px-2.5 py-1 text-xs text-muted transition-colors hover:text-text disabled:opacity-40"
                      >
                        {t("resetPassword")}
                      </button>
                      <button
                        type="button"
                        disabled={locked}
                        onClick={() =>
                          setActive.mutate({ id: user.id, active: !user.is_active })
                        }
                        className="rounded-lg border border-line px-2.5 py-1 text-xs text-muted transition-colors hover:text-text disabled:opacity-40"
                      >
                        {user.is_active ? t("deactivate") : t("activate")}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {users.isPending && (
          <p className="px-4 py-8 text-center text-sm text-subtle">{tStats("loading")}</p>
        )}
        {!users.isPending && rows.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-subtle">
            {tStats("noData")}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * A password shown exactly once.
 *
 * Deliberately loud and deliberately manual to dismiss: it cannot be recovered,
 * and a toast that fades after four seconds would lose it while the administrator
 * was still reading the name.
 */
function OneTimePassword({
  email,
  password,
  onDismiss,
}: {
  email: string;
  password: string;
  onDismiss: () => void;
}) {
  const t = useTranslations("admin.users");
  const tAction = useTranslations("action");
  const [copied, setCopied] = useState(false);

  return (
    <div
      role="status"
      className="rounded-xl border border-warn/40 bg-warn-bg p-5"
    >
      <p className="text-sm font-medium text-warn">{t("created")}</p>
      <p className="mt-1 text-xs text-warn">{t("passwordOnce")}</p>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <code className="numeric rounded bg-surface px-3 py-1.5 text-sm text-text">
          {password}
        </code>
        <span className="numeric text-xs text-warn">{email}</span>

        <button
          type="button"
          onClick={() => {
            void navigator.clipboard.writeText(password);
            setCopied(true);
          }}
          className="rounded-lg border border-warn/40 px-2.5 py-1 text-xs text-warn transition-opacity hover:opacity-80"
        >
          {copied ? t("copied") : t("copy")}
        </button>
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
