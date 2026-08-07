/**
 * Builds the `<style>` block that applies an organisation's palette at runtime.
 *
 * A pure function rather than JSX so it can be tested. The two things it gets right
 * are both invisible when they are wrong, which is why they are here rather than
 * inlined in the component:
 *
 * **Specificity.** The previous version emitted plain `:root`, which loses to
 * `tokens.css`'s `:root:not(.light):not(.dark)` (0,3,0 against 0,1,0). That selector
 * is the classless case — a user whose theme is "system", which is the shipped
 * default — so the organisation's colours applied only once somebody explicitly
 * toggled light or dark, and silently did not otherwise. Explicit light and dark
 * happened to work on source order, which is a tie-break, not a design. Doubling
 * doubling `:root` raises every rule above the tokens it is meant to override, so placement
 * of the tag stops mattering.
 *
 * **Print.** `globals.css` resets the surfaces to paper for `@media print`, and it
 * would lose to the raised specificity here. The background rules are therefore
 * wrapped in `@media screen`: a categorical exclusion, because a specificity race
 * against a rule inside a `prefers-color-scheme` query is not winnable. Brand
 * colours stay outside it — printed reports carrying the institution's colours is
 * what that stylesheet is for.
 */

import { readableTextOn, type ModePair } from "./contrast";

export interface BrandingColors {
  primary: ModePair;
  accent: ModePair;
  background: ModePair;
}

/** Every declaration that depends on the brand colours, for one mode. */
function brandBlock(color: string, accent: string): string {
  return [
    `  --brand-primary: ${color};`,
    `  --brand-primary-contrast: ${readableTextOn(color)};`,
    `  --brand-accent: ${accent};`,
  ].join("\n");
}

/**
 * The page backdrop and the step away from it that rows and chips sit on.
 *
 * `--bg-subtle` is derived rather than configured because it is a *relative*
 * token — hover rows, the active nav item, keyboard chips. Left at a fixed grey it
 * would clash the moment the page is tinted, and asking for a second colour to
 * solve that is asking the wrong person.
 *
 * Mixing toward `--text` is what makes one expression correct in both modes:
 * `--text` is near-black in light and near-white in dark, so the same rule darkens
 * a light background and lightens a dark one — the direction the shipped
 * `#fbfbfa → #f4f4f2` and `#08080a → #101013` pairs already go.
 */
function backgroundBlock(color: string): string {
  return [
    `  --bg: ${color};`,
    `  --bg-subtle: color-mix(in oklab, ${color} 96%, var(--text));`,
  ].join("\n");
}

/**
 * Render an organisation's colours as CSS.
 *
 * @param colors - The primary, accent and background pairs from `GET /org/branding`.
 * @returns A stylesheet to inline in `<head>`.
 */
export function brandingCss(colors: BrandingColors): string {
  const { primary, accent, background } = colors;

  // The classless selector, matching tokens.css so the OS preference still decides.
  // Emitting the dark values unconditionally would hand them to every "system" user
  // whose OS prefers light.
  const auto = ":root:root:not(.light):not(.dark)";

  return `
:root:root {
${brandBlock(primary.light, accent.light)}
}
:root:root.dark {
${brandBlock(primary.dark, accent.dark)}
}
@media (prefers-color-scheme: dark) {
  ${auto} {
${brandBlock(primary.dark, accent.dark)}
  }
}
@media screen {
  :root:root {
${backgroundBlock(background.light)}
  }
  :root:root.dark {
${backgroundBlock(background.dark)}
  }
  @media (prefers-color-scheme: dark) {
    ${auto} {
${backgroundBlock(background.dark)}
    }
  }
}`.trim();
}
