/**
 * Activity feed page.
 *
 * Admin and above. Guarded here as well as by the API — rendering a trail whose
 * every request will 403 is a worse experience than a redirect.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { AuditView } from "./audit-view";
import { can } from "@/lib/permissions";
import { requireSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("admin.audit.title") };
}

export default async function AdminAuditPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  await requireSession(locale, can.viewAudit);

  // useSearchParams needs a Suspense boundary above it, or the route opts out of
  // static rendering with a build-time error.
  return (
    <Suspense>
      <AuditView locale={locale} />
    </Suspense>
  );
}
