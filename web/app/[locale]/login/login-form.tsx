"use client";

/**
 * Sign-in form.
 *
 * A real form element with a real submit, so the browser's own validation, the
 * Enter key and password managers all work without being reimplemented.
 *
 * No TanStack Query here, deliberately: this page sits outside the `(app)` group
 * and so outside its QueryProvider, and there is nothing to cache — one POST, then
 * a navigation into a tree that mounts its own client.
 *
 * Errors arrive as machine codes and are translated here; the backend ships no
 * message catalogue, which is what keeps it free of presentation concerns.
 */

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { useRouter } from "@/i18n/navigation";
import { api, ApiError } from "@/lib/api";

export function LoginForm() {
  const t = useTranslations();
  const router = useRouter();
  const [code, setCode] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setCode(null);
    setPending(true);

    try {
      await api("/auth/login", {
        method: "POST",
        body: {
          email: String(data.get("email") ?? ""),
          password: String(data.get("password") ?? ""),
        },
      });
      // `refresh` as well as `replace`: the destination's guard reads the session
      // on the server, and without a refresh it may answer from the cached render
      // taken before the cookie existed.
      // The dashboard, not the student list: it is the only page that opens with an
      // answer rather than a directory, and it is scoped, so every role gets a
      // useful first screen instead of a table they may have one row in.
      router.replace("/dashboard");
      router.refresh();
    } catch (error) {
      setCode(error instanceof ApiError ? error.code : "NETWORK_ERROR");
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div>
        <label htmlFor="email" className="block text-sm text-muted">
          {t("auth.email")}
        </label>
        <input
          id="email"
          name="email"
          type="email"
          required
          autoComplete="username"
          autoFocus
          className="mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
        />
      </div>

      <div>
        <label htmlFor="password" className="block text-sm text-muted">
          {t("auth.password")}
        </label>
        <input
          id="password"
          name="password"
          type="password"
          required
          autoComplete="current-password"
          className="mt-1.5 w-full rounded-lg border border-line bg-bg px-3 py-2 text-text outline-none focus-visible:border-brand focus-visible:ring-2 focus-visible:ring-brand/30"
        />
      </div>

      {/* role=alert so the failure is announced. A red border alone tells a screen
          reader user nothing, and this is the one message they most need. */}
      {code && (
        <p role="alert" className="rounded-lg bg-fail-bg px-3 py-2 text-sm text-fail">
          {t(`error.${code}` as "error.unknown")}
        </p>
      )}

      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-lg bg-brand px-4 py-2.5 font-medium text-brand-contrast transition-opacity hover:opacity-90 disabled:opacity-60"
      >
        {pending ? t("auth.signingIn") : t("auth.signIn")}
      </button>
    </form>
  );
}
