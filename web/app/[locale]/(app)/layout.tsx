/**
 * Application shell.
 *
 * A route group, so `(app)` adds this layout without appearing in any URL —
 * /students, not /app/students.
 *
 * The guard runs here rather than in each page: a page added later is protected by
 * existing in this directory, which is a far harder thing to forget than a call.
 */

import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppNav } from "@/components/app/app-nav";
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
  const me = await getServerSession();

  // Locale-prefixed by hand: this is `next/navigation`'s redirect, which knows
  // nothing about the routing config, and dropping the prefix would send a German
  // user to the English sign-in page.
  if (!me) redirect(`/${locale}/login`);

  return (
    <QueryProvider>
      <div className="min-h-dvh bg-bg">
        <AppNav me={me} />
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </div>
    </QueryProvider>
  );
}
