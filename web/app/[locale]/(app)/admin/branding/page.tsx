import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { BrandingView } from "./branding-view";
import { getBranding } from "@/components/branding/branding";
import { can } from "@/lib/permissions";
import { requireSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "admin.branding" });
  return { title: t("title") };
}

/**
 * Every zone this runtime knows, UTC first.
 *
 * Built here, on the server, and handed to the form as data. Reading it inside the
 * client component meant Node answered during the server render and the browser
 * answered again during hydration, from two different ICU builds — a handful of
 * zones apart, which React reported as a hydration mismatch on the `<select>` every
 * time the page loaded.
 */
const TIME_ZONES = [
  "UTC",
  ...Intl.supportedValuesOf("timeZone").filter((zone) => zone !== "UTC"),
];

export default async function BrandingPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  await requireSession(locale, can.editBranding);

  return <BrandingView initialBranding={await getBranding()} timeZones={TIME_ZONES} />;
}
