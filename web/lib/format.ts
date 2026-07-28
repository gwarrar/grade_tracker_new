/**
 * Locale-aware number and date formatting.
 *
 * Native `Intl`, no library. This is correctness rather than polish: German writes
 * 88,5 where English writes 88.5, and a grade input that silently parses "88,5" as
 * 88 is a wrong mark in a student's record.
 */

/**
 * Format a number for display.
 *
 * @param value - The number, or null for missing data.
 * @param locale - BCP-47 locale tag.
 * @param options - Passed through to `Intl.NumberFormat`.
 * @returns The formatted string, or an em dash for null.
 */
export function formatNumber(
  value: number | null | undefined,
  locale: string,
  options: Intl.NumberFormatOptions = {},
): string {
  // An em dash, not "0" -- absent data and a score of zero are different facts,
  // and a report that renders them identically is misleading.
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2, ...options }).format(value);
}

/**
 * Format a percentage.
 *
 * @param value - A percentage in 0–100, or null.
 * @param locale - BCP-47 locale tag.
 * @returns e.g. `87.5%` in English, `87,5 %` in French.
 */
export function formatPercent(value: number | null | undefined, locale: string): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value / 100);
}

/**
 * Format an ISO date.
 *
 * @param iso - `YYYY-MM-DD` or a full ISO timestamp.
 * @param locale - BCP-47 locale tag.
 * @param options - Passed through to `Intl.DateTimeFormat`.
 * @returns e.g. `15 Jan 2026`, `15. Jan. 2026`, `15 janv. 2026`.
 */
export function formatDate(
  iso: string | null | undefined,
  locale: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: "medium" },
): string {
  if (!iso) return "—";
  const date = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, { timeZone: "UTC", ...options }).format(date);
}

/**
 * Parse a number the user typed, in their own locale's notation.
 *
 * A German user types `88,5` and means 88.5. `Number("88,5")` is `NaN`, and
 * `parseFloat("88,5")` is **88** — silently dropping the fraction and recording a
 * wrong mark. Neither is acceptable on a grade field, which is why this exists
 * rather than a bare `Number()` call at the call site.
 *
 * @param input - What the user typed.
 * @param locale - BCP-47 locale tag, used to determine the decimal separator.
 * @returns The parsed number, or null if it is not a number at all.
 */
export function parseLocaleNumber(input: string, locale: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) return null;

  // Ask Intl what this locale actually uses rather than hardcoding a list.
  const parts = new Intl.NumberFormat(locale).formatToParts(12345.6);
  const decimal = parts.find((p) => p.type === "decimal")?.value ?? ".";
  const group = parts.find((p) => p.type === "group")?.value ?? ",";

  // Validate grouping before stripping it. Naively removing the separators turns
  // "8,5,5" into "855" \u2014 a plausible-looking number the user never typed, recorded
  // as a mark without complaint. Every group after the first must be exactly three
  // digits.
  const segments = trimmed.split(group);
  if (segments.length > 1 && !segments.slice(1).every((s) => /^\d{3}(\D|$)/.test(s))) {
    return null;
  }

  const normalised = segments
    .join("")
    .replace(decimal, ".")
    // Non-breaking and narrow no-break spaces are what French grouping actually
    // uses, and they survive a copy-paste from a spreadsheet.
    .replace(/[\s\u00a0\u202f]/g, "");

  if (!/^[+-]?\d*\.?\d+$/.test(normalised)) return null;

  const value = Number(normalised);
  return Number.isFinite(value) ? value : null;
}
