/**
 * The video's palette, taken from the application's own dark tokens.
 *
 * Hard-coded rather than imported from `web/app/tokens.css`: this package is
 * deliberately not part of the app's build, and a video that silently changes
 * when someone rebrands the product is worse than one that needs a manual edit.
 */

export const theme = {
  bg: "#08080a",
  surface: "#111114",
  surfaceRaised: "#17171c",
  line: "#26262e",
  text: "#f4f4f5",
  muted: "#a1a1aa",
  subtle: "#71717a",
  brand: "#7c7cf0",
  accent: "#4ade80",
  fail: "#f87171",
  warn: "#fbbf24",
} as const;

export const font = {
  sans: '"Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
  mono: 'ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, monospace',
} as const;
