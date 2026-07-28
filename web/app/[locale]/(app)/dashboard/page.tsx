/**
 * Dashboard page.
 *
 * The band order comes from the organisation's grading scale rather than a
 * hardcoded A–F, so an institution using a different scale gets its own bands in
 * its own order.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { DashboardView } from "./dashboard-view";
import { getBranding } from "@/components/branding/branding";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("nav.dashboard") };
}

export default async function DashboardPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const branding = await getBranding();
  const bands = branding.grading_scale.map((band) => band.label);

  return (
    <Suspense>
      <DashboardView locale={locale} bands={bands} />
    </Suspense>
  );
}
