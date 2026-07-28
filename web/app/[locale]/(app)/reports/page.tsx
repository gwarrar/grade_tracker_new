/**
 * Reports page.
 *
 * Teacher and above. A summary over every student cannot be meaningfully scoped
 * to one of them, so the API refuses it for a student and this page redirects
 * rather than rendering an interface where every request would 403.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { ReportsView } from "./reports-view";
import { getBranding } from "@/components/branding/branding";
import { getServerSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("report.title") };
}

export default async function ReportsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const me = await getServerSession();
  if (!me) redirect(`/${locale}/login`);
  if (me.role === "student") redirect(`/${locale}/dashboard`);

  const branding = await getBranding();

  return (
    <Suspense>
      <ReportsView locale={locale} bands={branding.grading_scale.map((band) => band.label)} />
    </Suspense>
  );
}
