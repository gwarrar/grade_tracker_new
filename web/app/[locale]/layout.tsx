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

import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { BrandingStyle, getBranding } from "@/components/branding/branding";
import { ThemeProvider } from "@/components/theme/theme-provider";
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
    icons: branding.favicon_path ? { icon: branding.favicon_path } : undefined,
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

  const branding = await getBranding();

  return (
    // suppressHydrationWarning because next-themes writes the theme class onto
    // <html> before React hydrates. That mismatch is the mechanism preventing the
    // flash of wrong theme, not a bug to fix.
    <html lang={locale} suppressHydrationWarning>
      <head>
        <BrandingStyle branding={branding} />
      </head>
      <body className={`${sans.variable} ${mono.variable}`}>
        <ThemeProvider defaultTheme={branding.default_theme}>
          <NextIntlClientProvider>{children}</NextIntlClientProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
