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
import { requireSession } from "@/lib/server-session";

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

  // No capability check: every role may *read* the directory, and the API scopes the
  // rows. `me` is fetched here rather than in the view so the role is known before
  // the first paint — a client-side lookup would render an Edit button and then
  // remove it, which is worse than never showing it.
  const me = await requireSession(locale);

  // useSearchParams needs a Suspense boundary above it, or the whole route opts
  // out of static rendering with a build-time error.
  return (
    <Suspense>
      <StudentsView me={me} locale={locale} />
    </Suspense>
  );
}
