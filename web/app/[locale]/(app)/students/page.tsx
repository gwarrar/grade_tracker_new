/**
 * Students page.
 *
 * A thin server component: it fixes the request locale and hands the locale to the
 * client view, which needs it for `Intl` formatting. All data loading happens in
 * the client so that selecting a row is instant rather than a server round trip.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { StudentsView } from "./students-view";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("student.other") };
}

export default async function StudentsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  // useSearchParams needs a Suspense boundary above it, or the whole route opts
  // out of static rendering with a build-time error.
  return (
    <Suspense>
      <StudentsView locale={locale} />
    </Suspense>
  );
}
