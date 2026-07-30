/**
 * Courses page.
 *
 * A thin server component: it fixes the request locale and hands it to the client
 * view, which needs it for Intl formatting and for parsing what the user types.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { Suspense } from "react";

import { CoursesView } from "./courses-view";
import { requireSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("course.other") };
}

export default async function Page({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  // Every role may read the course list; the API scopes which courses. `me` decides
  // only what the panel offers to change.
  const me = await requireSession(locale);

  // useSearchParams needs a Suspense boundary above it, or the route opts out of
  // static rendering with a build-time error.
  return (
    <Suspense>
      <CoursesView me={me} locale={locale} />
    </Suspense>
  );
}
