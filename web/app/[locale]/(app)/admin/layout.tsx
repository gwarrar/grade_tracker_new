/**
 * Administrative shell.
 *
 * Only the sub-navigation: each page below still guards its own capability, and
 * doing it here as well would put the rule in two places and let them drift. The
 * session lookup is memoised per request, so asking for it here costs nothing.
 */

import type { ReactNode } from "react";

import { AdminNav } from "@/components/app/admin-nav";
import { requireSession } from "@/lib/server-session";

export default async function AdminLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const me = await requireSession(locale);

  return (
    <>
      <AdminNav me={me} />
      {children}
    </>
  );
}
