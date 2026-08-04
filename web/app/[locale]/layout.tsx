/**
 * Root layout.
 *
 * Lives under `[locale]` rather than at `app/` because it owns `<html lang>`, and
 * only this segment knows the language. With a layout above it, every page shipped
 * `lang="en"` regardless of content — which is not cosmetic: screen readers choose
 * pronunciation from that attribute, so a German page was being announced with
 * English phonetics.
 *
 * Next 16: `params` is a Promise. Synchronous access was removed, not deprecated.
 */

import { cookies } from "next/headers";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { assetUrl, BrandingStyle, getBranding } from "@/components/branding/branding";
import { ThemeProvider } from "@/components/theme/theme-provider";
import { COOKIE, normalise } from "@/components/theme/theme";
import { routing } from "@/i18n/routing";
import "../globals.css";

// Self-hosted by next/font: no render-blocking request to Google, no layout shift
// as the fallback swaps out, and no third-party request from a page showing student
// records.
const sans = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-sans-loaded",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono-loaded",
  display: "swap",
});

/** Pre-render every locale rather than resolving them on first request. */
export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const [branding, t] = await Promise.all([
    getBranding(),
    getTranslations({ locale, namespace: "app" }),
  ]);

  return {
    title: { default: t("name"), template: `%s · ${branding.short_name || t("name")}` },
    description: t("tagline"),
    icons: branding.favicon_path ? { icon: assetUrl(branding.favicon_path) } : undefined,
  };
}

export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  // An unknown locale is a 404, not a silent fallback to English. Serving content at
  // /xx/students that claims to be a real page hides broken links.
  if (!hasLocale(routing.locales, locale)) notFound();

  // Required for static rendering; without it every page becomes dynamic.
  setRequestLocale(locale);

  const [branding, jar] = await Promise.all([getBranding(), cookies()]);

  // The explicit choice, straight from the cookie into the first byte of HTML.
  // "system" deliberately writes no class: that hands the decision to the
  // prefers-color-scheme block in tokens.css, which needs no JavaScript at all.
  const chosen = normalise(jar.get(COOKIE)?.value ?? branding.default_theme);
  const themeClass = chosen === "system" ? undefined : chosen;

  return (
    // suppressHydrationWarning is still needed here, though no longer for the
    // theme — the server renders that class from the cookie now. It is for browser
    // extensions. LanguageTool adds data-lt-installed, Grammarly and password
    // managers add their own, all onto <html> before React hydrates, and React
    // reports every one as a mismatch the developer cannot act on.
    //
    // It suppresses exactly one level, so a genuine mismatch anywhere inside still
    // reports normally.
    <html lang={locale} className={themeClass} suppressHydrationWarning>
      <head>
        <BrandingStyle branding={branding} />
      </head>
      <body className={`${sans.variable} ${mono.variable}`}>
        <ThemeProvider>
          <NextIntlClientProvider>{children}</NextIntlClientProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
