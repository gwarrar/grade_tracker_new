/**
 * Per-request message loading.
 *
 * Merges the organisation's overrides over the shipped translations, so an
 * administrator renaming "Students" to "Auszubildende" takes effect without a
 * rebuild. See `services/localization.py` for why that layer exists.
 *
 * Overrides arrive as flat dotted keys (`nav.students`); the message files are
 * nested, so they are expanded before merging.
 */

import { getRequestConfig } from "next-intl/server";

import { API_BASE } from "@/lib/api";
import { applyOverrides, type Messages } from "./merge";
import de from "../messages/de.json";
import en from "../messages/en.json";
import fr from "../messages/fr.json";
import { type Locale, locales, routing } from "./routing";

// A static map rather than `import(\`../messages/${locale}.json\`)`. Turbopack
// cannot resolve a template-literal relative import into a module context, and it
// fails at prerender rather than at build. Listing them also makes the bundle
// deterministic and a missing file a compile error instead of a runtime one.
const SHIPPED: Record<Locale, Messages> = { en, de, fr };

/**
 * Fetch this organisation's overrides.
 *
 * Failure is not fatal: the shipped translations are already correct, so an
 * unreachable API costs a rename, not the interface.
 *
 * @param locale - Which language.
 * @returns Dotted key to replacement text, empty on failure.
 */
async function fetchOverrides(locale: string): Promise<Record<string, string>> {
  try {
    const response = await fetch(`${API_BASE}/org/i18n/${locale}`, {
      next: { revalidate: 60 },
    });
    if (!response.ok) return {};
    return (await response.json()) as Record<string, string>;
  } catch {
    return {};
  }
}

export default getRequestConfig(async ({ requestLocale }) => {
  // Next 16: this is a Promise. Synchronous access was removed, not deprecated.
  const requested = await requestLocale;
  const locale = locales.includes(requested as Locale)
    ? (requested as Locale)
    : routing.defaultLocale;

  const overrides = await fetchOverrides(locale);

  return { locale, messages: applyOverrides(SHIPPED[locale], overrides) };
});
