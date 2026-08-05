/**
 * Bulk import page.
 *
 * Guarded on the server as well as by the API. Students and courses require an
 * administrator; grades require a teacher, which an administrator also satisfies.
 * Rendering the wizard for someone whose every request will 403 is a worse
 * experience than a redirect.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { ImportView } from "./import-view";
import { can } from "@/lib/permissions";
import { requireSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("admin.import.title") };
}

export default async function AdminImportPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  await requireSession(locale, can.importData);

  return <ImportView locale={locale} />;
}
