/**
 * Profile page.
 *
 * The principal is read on the server — the shell's guard already fetched it, and
 * passing it down avoids a second identical request from the browser purely to
 * render a name that is already known.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { redirect } from "next/navigation";

import { ProfileView } from "./profile-view";
import { getServerSession } from "@/lib/server-session";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("profile.title") };
}

export default async function ProfilePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  // The layout guard has already run; this is a type narrowing, not a second
  // check. Rendering with a null principal is not representable.
  const me = await getServerSession();
  if (!me) redirect(`/${locale}/login`);

  return <ProfileView me={me} locale={locale} />;
}
