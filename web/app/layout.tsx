/**
 * Root layout.
 *
 * Next.js 16: `params` and `searchParams` are Promises everywhere and must be
 * awaited — synchronous access was removed, not deprecated. See
 * `node_modules/next/dist/docs/01-app/02-guides/upgrading/version-16.md`.
 */

import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";
import type { ReactNode } from "react";

import { BrandingStyle, getBranding } from "@/components/branding/branding";
import { ThemeProvider } from "@/components/theme/theme-provider";
import "./globals.css";

// Self-hosted by next/font: no render-blocking request to Google, no layout shift
// as the fallback is swapped out, and no third-party request from a page that
// displays student records.
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

export async function generateMetadata(): Promise<Metadata> {
  const branding = await getBranding();
  return {
    title: { default: branding.name, template: `%s · ${branding.short_name || branding.name}` },
    description: "Student grade management: records, reports and analysis.",
    icons: branding.favicon_path ? { icon: branding.favicon_path } : undefined,
  };
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const branding = await getBranding();

  return (
    // suppressHydrationWarning because next-themes writes the theme class onto
    // <html> before React hydrates. That mismatch is the mechanism preventing the
    // flash of wrong theme, not a bug to fix.
    <html lang={branding.default_locale} suppressHydrationWarning>
      <head>
        <BrandingStyle branding={branding} />
      </head>
      <body className={`${sans.variable} ${mono.variable}`}>
        <ThemeProvider defaultTheme={branding.default_theme}>{children}</ThemeProvider>
      </body>
    </html>
  );
}
