/**
 * AI configuration page.
 *
 * Guarded on the server as well as by the API. The role check below is not the
 * lock — every endpoint enforces superadmin independently — but rendering the
 * page for someone who will get 403 on every request in it is a worse experience
 * than a clean redirect.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { AiView } from "./ai-view";
import { can } from "@/lib/permissions";
import { requireSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("admin.ai.title") };
}

export default async function AdminAiPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  await requireSession(locale, can.manageAi);

  return <AiView locale={locale} />;
}
