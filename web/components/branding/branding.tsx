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
import { readableTextOn } from "@/lib/contrast";

/** The public branding payload from `GET /org/branding`. */
export interface Branding {
  name: string;
  short_name: string;
  logo_path: string | null;
  favicon_path: string | null;
  colors: {
    primary: { light: string; dark: string };
    accent: { light: string; dark: string };
  };
  default_locale: string;
  enabled_locales: string[];
  default_theme: string;
  timezone: string;
  grading_scale: { min_percentage: number; label: string }[];
}

const FALLBACK: Branding = {
  name: "Grade Tracker",
  short_name: "GT",
  logo_path: null,
  favicon_path: null,
  colors: {
    primary: { light: "#2e5bff", dark: "#7c9bff" },
    accent: { light: "#00a37a", dark: "#3dd9ac" },
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
};

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
      // Re-read periodically so a branding change appears without a redeploy,
      // but not on every request -- this is on the critical path of every page.
      next: { revalidate: 60 },
    });
    if (!response.ok) return FALLBACK;
    return (await response.json()) as Branding;
  } catch {
    return FALLBACK;
  }
}

/**
 * Render the brand colours as scoped custom properties.
 *
 * Overrides the defaults in `tokens.css` for both themes at once: `:root` carries
 * the light values, `.dark` the dark ones, exactly as the token file does.
 */
export function BrandingStyle({ branding }: { branding: Branding }) {
  const { primary, accent } = branding.colors;

  const css = `
:root {
  --brand-primary: ${primary.light};
  --brand-primary-contrast: ${readableTextOn(primary.light)};
  --brand-accent: ${accent.light};
}
.dark {
  --brand-primary: ${primary.dark};
  --brand-primary-contrast: ${readableTextOn(primary.dark)};
  --brand-accent: ${accent.dark};
}`.trim();

  return <style dangerouslySetInnerHTML={{ __html: css }} />;
}
