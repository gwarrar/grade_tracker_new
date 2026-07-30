/**
 * Grades page.
 *
 * A thin server component: it fixes the request locale and hands it to the client
 * view, which needs it for Intl formatting and for parsing what the user types.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { GradesView } from "./grades-view";
import { getBranding } from "@/components/branding/branding";
import { requireSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("grade.other") };
}

export default async function Page({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  // A student may read this page — it is where they see their own marks. What they
  // may not do is change them, which is what `me` decides below.
  const me = await requireSession(locale);

  // The grade bands come from the organisation, not from a constant: an institution
  // that renamed or re-cut its scale must see its own bands in the filter.
  const branding = await getBranding();

  // useSearchParams needs a Suspense boundary above it, or the route opts out of
  // static rendering with a build-time error.
  return (
    <Suspense>
      <GradesView
        me={me}
        locale={locale}
        bands={branding.grading_scale.map((band) => band.label)}
      />
    </Suspense>
  );
}
