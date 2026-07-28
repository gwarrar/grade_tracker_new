/**
 * Sign-in page.
 *
 * Deliberately outside the `(app)` group: that group's layout redirects anyone
 * without a session here, and a sign-in page inside it would redirect to itself.
 */

import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { LoginForm } from "./login-form";
import { locales } from "@/i18n/routing";

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale });
  return { title: t("auth.signIn") };
}

export default async function LoginPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations();

  return (
    <main className="flex min-h-dvh items-center justify-center bg-bg px-6">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold tracking-tight text-text">{t("app.name")}</h1>
        <p className="mt-1 text-sm text-muted">{t("app.tagline")}</p>
        <div className="mt-8">
          <LoginForm />
        </div>
      </div>
    </main>
  );
}
