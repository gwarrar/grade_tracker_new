"use client";

/**
 * Application navigation.
 *
 * Links are filtered by role here *and* enforced by the API. This copy exists so
 * nobody is shown a door they cannot open; it is not the lock — a student who
 * types /admin still gets a 403 from the server.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Link, usePathname, useRouter } from "@/i18n/navigation";
import { LocaleSwitcher } from "@/components/ui/locale-switcher";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { api } from "@/lib/api";
import { atLeast, type Me } from "@/lib/session";

// Only routes that exist. A nav that lists /reports before /reports is built is a
// link straight to a 404 — worse than the feature being absent, because it reads
// as broken rather than as not-yet-there. Restored as each page lands.
const LINKS = [
  { href: "/students", key: "students", min: "student" },
  { href: "/courses", key: "courses", min: "student" },
  { href: "/grades", key: "grades", min: "student" },
  { href: "/admin/ai", key: "admin", min: "superadmin" },
] as const;

export function AppNav({ me }: { me: Me }) {
  const t = useTranslations();
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();

  const signOut = useMutation({
    mutationFn: () => api("/auth/logout", { method: "POST" }),
    onSuccess: () => {
      // Clear every cached query, not just the session: the cache still holds the
      // previous user's students, and the next sign-in on this browser would show
      // them for a moment before refetching.
      queryClient.clear();
      router.replace("/login");
      router.refresh();
    },
  });

  const visible = LINKS.filter((link) => atLeast(me.role, link.min));

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
        <Link href="/students" className="text-sm font-medium tracking-tight text-text">
          {t("app.name")}
        </Link>

        <nav className="flex gap-1 text-sm" aria-label={t("nav.dashboard")}>
          {visible.map((link) => {
            // startsWith, so /students?id=S001 keeps the Students tab lit. `usePathname`
            // from next-intl already has the locale prefix stripped.
            const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-md px-2.5 py-1.5 transition-colors ${
                  active ? "bg-bg-subtle text-text" : "text-muted hover:text-text"
                }`}
              >
                {t(`nav.${link.key}`)}
              </Link>
            );
          })}
        </nav>

        <div className="ms-auto flex items-center gap-2">
          <LocaleSwitcher label={t("locale.label")} />
          <ThemeToggle />
          <Link
            href="/profile"
            className="max-w-40 truncate rounded-md px-2.5 py-1.5 text-sm text-muted transition-colors hover:text-text"
            title={me.email}
          >
            {me.full_name}
          </Link>
          <button
            type="button"
            onClick={() => signOut.mutate()}
            disabled={signOut.isPending}
            className="rounded-md border border-line px-2.5 py-1.5 text-sm text-muted transition-colors hover:text-text disabled:opacity-60"
          >
            {t("nav.signOut")}
          </button>
        </div>
      </div>
    </header>
  );
}
