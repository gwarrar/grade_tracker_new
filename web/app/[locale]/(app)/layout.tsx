/**
 * Application shell.
 *
 * A route group, so `(app)` adds this layout without appearing in any URL —
 * /students, not /app/students.
 *
 * The guard runs here rather than in each page: a page added later is protected by
 * existing in this directory, which is a far harder thing to forget than a call.
 */

import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppNav } from "@/components/app/app-nav";
import { CommandPalette } from "@/components/app/command-palette";
import { QueryProvider } from "@/app/query-provider";
import { getServerSession } from "@/lib/server-session";

export default async function AppLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [me, t] = await Promise.all([getServerSession(), getTranslations("nav")]);

  // Locale-prefixed by hand: this is `next/navigation`'s redirect, which knows
  // nothing about the routing config, and dropping the prefix would send a German
  // user to the English sign-in page.
  if (!me) redirect(`/${locale}/login`);

  return (
    <QueryProvider>
      <div className="min-h-dvh bg-bg">
        {/* Visible only when focused. Every page here starts with a nav of five
            links; without this a keyboard user tabs through all of them on every
            single page before reaching the content. */}
        <a
          href="#content"
          className="sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-brand focus:px-4 focus:py-2 focus:text-sm focus:text-brand-contrast"
        >
          {t("skip")}
        </a>
        <AppNav me={me} />
        <main id="content" className="mx-auto max-w-7xl px-6 py-8">
          {children}
        </main>
        {/* Inside QueryProvider — it searches through the same cache. */}
        <CommandPalette me={me} />
      </div>
    </QueryProvider>
  );
}
