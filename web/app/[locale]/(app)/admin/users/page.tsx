/**
 * Accounts page.
 *
 * Admin and above. Guarded here as well as by the API — rendering a table whose
 * every control will 403 is a worse experience than a redirect.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { UsersView } from "./users-view";
import { can } from "@/lib/permissions";
import { requireSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("admin.users.title") };
}

export default async function AdminUsersPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const me = await requireSession(locale, can.manageUsers);

  return <UsersView me={me} locale={locale} />;
}
