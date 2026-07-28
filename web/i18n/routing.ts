/**
 * Locale routing.
 *
 * A `[locale]` path segment rather than a cookie, so `/de/students` is a real,
 * shareable URL. That matters for the marketing pages — cookie-selected language
 * gives every language one URL, which search engines cannot index separately and a
 * user cannot send to a colleague.
 */

import { defineRouting } from "next-intl/routing";

export const locales = ["en", "de", "fr"] as const;
export type Locale = (typeof locales)[number];

export const routing = defineRouting({
  locales,
  defaultLocale: "en",
  // Always prefix, including the default. The alternative leaves "/" and "/en"
  // serving identical content at two URLs — a duplicate-content problem and an
  // ambiguity in every internal link.
  localePrefix: "always",
});
