/**
 * Applies the organisation's brand colours as CSS custom properties.
 *
 * This is the mechanism behind live re-theming. The admin changes a colour, the
 * next page load picks it up, and the entire interface follows — because no
 * component contains a colour, only a reference to `--brand-primary`.
 *
 * Rendered server-side into a `<style>` tag rather than set from an effect, so the
 * brand colours are correct on first paint. Applying them client-side would show
 * the default palette for a frame and then swap, which reads as a broken page.
 */

import { API_BASE } from "@/lib/api";
import { brandingCss, type BrandingColors } from "@/lib/branding-css";
import { DEFAULT_BACKGROUND, parseHex } from "@/lib/contrast";

/** Cache tag for the branding read, revalidated by the branding editor on save. */
export const BRANDING_TAG = "org-branding";

/** The public branding payload from `GET /org/branding`. */
export interface Branding {
  name: string;
  short_name: string;
  logo_path: string | null;
  favicon_path: string | null;
  colors: BrandingColors;
  default_locale: string;
  enabled_locales: string[];
  default_theme: string;
  timezone: string;
  grading_scale: { min_percentage: number; label: string }[];
  updated_at: string | null;
}

const FALLBACK: Branding = {
  name: "Grade Tracker",
  short_name: "GT",
  logo_path: null,
  favicon_path: null,
  colors: {
    primary: { light: "#2e5bff", dark: "#7c9bff" },
    accent: { light: "#00a37a", dark: "#3dd9ac" },
    background: DEFAULT_BACKGROUND,
  },
  default_locale: "en",
  enabled_locales: ["en", "de", "fr"],
  default_theme: "system",
  timezone: "UTC",
  grading_scale: [
    { min_percentage: 90, label: "A" },
    { min_percentage: 80, label: "B" },
    { min_percentage: 70, label: "C" },
    { min_percentage: 60, label: "D" },
    { min_percentage: 0, label: "F" },
  ],
  updated_at: null,
};

/** Resolve an API-served asset for the separately hosted web application. */
export function assetUrl(path: string): string {
  return new URL(path, API_BASE).href;
}

/**
 * Replace any value that is not a plain hex colour with the default.
 *
 * `brandingCss` concatenates these six strings into a `<style>` element that is
 * rendered with `dangerouslySetInnerHTML` in the root layout — on every page,
 * including the ones served before sign-in. The HTML tokeniser ends a `<style>`
 * at the first literal `</style`, so a stored value carrying one would close the
 * element and everything after it would be parsed as markup. A value carrying
 * only a brace would need no script to make the application unusable.
 *
 * The API validates on write and the editor uses `<input type="color">`, so this
 * is the third lock rather than the first. It is here because the other two are
 * upstream of a file that renders untrusted text into markup, and this one costs
 * a regex.
 *
 * @param colors The merged palette.
 * @returns The palette with unparseable values replaced.
 */
export function sanitiseColors(colors: BrandingColors): BrandingColors {
  const safe = (value: string, fallback: string) =>
    parseHex(value) === null ? fallback : value;
  return {
    primary: {
      light: safe(colors.primary.light, FALLBACK.colors.primary.light),
      dark: safe(colors.primary.dark, FALLBACK.colors.primary.dark),
    },
    accent: {
      light: safe(colors.accent.light, FALLBACK.colors.accent.light),
      dark: safe(colors.accent.dark, FALLBACK.colors.accent.dark),
    },
    background: {
      light: safe(colors.background.light, FALLBACK.colors.background.light),
      dark: safe(colors.background.dark, FALLBACK.colors.background.dark),
    },
  };
}

/**
 * Fetch the organisation's public configuration.
 *
 * Falls back to defaults rather than throwing: the sign-in page must render even
 * when the API is down, or a backend restart takes the whole interface with it.
 *
 * @returns The branding payload.
 */
export async function getBranding(): Promise<Branding> {
  try {
    const response = await fetch(`${API_BASE}/org/branding`, {
      // Tagged rather than time-based. A 60-second window meant an administrator
      // saved a colour, watched the page repopulate with the old one, and
      // reasonably concluded the feature was broken. The branding editor
      // revalidates this tag on save, so the change is visible immediately and
      // every other request still gets a cached read.
      next: { tags: [BRANDING_TAG] },
    });
    if (!response.ok) return FALLBACK;
    const payload = (await response.json()) as Branding;
    // Colours merged over the defaults rather than trusted whole. An API predating
    // one of them — a rolling deploy, or a backend somebody forgot to restart —
    // hands back a payload missing that key, and `brandingCss` would read `.light`
    // off undefined and take the root layout with it. Every page, for one absent
    // shade. Same reasoning as the fallback above: this file renders something.
    return {
      ...payload,
      colors: sanitiseColors({ ...FALLBACK.colors, ...payload.colors }),
    };
  } catch {
    return FALLBACK;
  }
}

/**
 * Render the organisation's palette as scoped custom properties.
 *
 * The rules themselves, and why they are shaped the way they are, live in
 * `lib/branding-css.ts` — a pure function, so the specificity and print behaviour
 * they depend on can be tested rather than hoped for.
 */
export function BrandingStyle({ branding }: { branding: Branding }) {
  return <style dangerouslySetInnerHTML={{ __html: brandingCss(branding.colors) }} />;
}
