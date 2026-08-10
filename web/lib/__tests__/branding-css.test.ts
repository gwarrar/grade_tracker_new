/**
 * The runtime palette override, and the two silent failures it exists to prevent.
 *
 * 1. **System theme lost the organisation's colours.** The generated CSS used plain
 *    `:root`, which loses to `tokens.css`'s `:root:not(.light):not(.dark)` on
 *    specificity. That selector matches when no theme class is on `<html>`, which is
 *    the "system" default — so branding applied only after somebody explicitly
 *    toggled light or dark, and nothing anywhere reported that it had not.
 * 2. **Print would have inherited the configured backdrop.** `globals.css` resets
 *    the surfaces to paper under `@media print`, and it would lose to the raised
 *    specificity. The background rules are confined to `@media screen` instead.
 *
 * Both are invisible in a browser you happen to have set to light mode, which is
 * why they are asserted on the emitted string rather than trusted to review.
 */

import { describe, expect, it } from "vitest";

import { brandingCss } from "../branding-css";

const COLORS = {
  primary: { light: "#2e5bff", dark: "#7c9bff" },
  accent: { light: "#00a37a", dark: "#3dd9ac" },
  background: { light: "#f0eee6", dark: "#101014" },
};

/** The `@media screen { ... }` body, which is where backgrounds must live. */
function screenBlock(css: string): string {
  const start = css.indexOf("@media screen {");
  expect(start).toBeGreaterThan(-1);
  return css.slice(start);
}

describe("brandingCss", () => {
  const css = brandingCss(COLORS);

  it("outranks the token defaults in every theme", () => {
    // 0,2,0 beats `:root`; 0,3,0 beats `.dark`; 0,4,0 beats the media query's
    // `:root:not(.light):not(.dark)`. Winning on specificity rather than source
    // order means it no longer matters where the <style> tag is placed.
    expect(css).toContain(":root:root {");
    expect(css).toContain(":root:root.dark {");
    expect(css).toContain(":root:root:not(.light):not(.dark) {");
  });

  it("leaves the OS preference in charge for the classless case", () => {
    // Not `:root:not(.light):not(.dark)` unconditionally — that would hand the dark
    // palette to every system-mode user whose OS prefers light.
    const auto = css.indexOf(":root:root:not(.light):not(.dark)");
    const query = css.lastIndexOf("@media (prefers-color-scheme: dark)", auto);
    expect(query).toBeGreaterThan(-1);
  });

  it("applies the dark values only where a dark theme is in force", () => {
    const light = css.slice(css.indexOf(":root:root {"), css.indexOf(":root:root.dark {"));
    expect(light).toContain(COLORS.primary.light);
    expect(light).not.toContain(COLORS.primary.dark);
  });

  it("keeps every background declaration out of print", () => {
    const screen = screenBlock(css);
    const backgrounds = [...css.matchAll(/--bg(?:-subtle)?:/g)];
    expect(backgrounds.length).toBeGreaterThan(0);
    for (const match of backgrounds) {
      expect(match.index).toBeGreaterThan(css.length - screen.length - 1);
    }
  });

  it("keeps the brand colours in print", () => {
    // Deliberate, not an oversight: a printed report carrying the institution's
    // colours is what the print stylesheet is for.
    const screen = screenBlock(css);
    expect(screen).not.toContain("--brand-primary:");
  });

  it("derives the card surfaces from the background too", () => {
    // Left out of the first version, which meant an organisation could tint its page
    // and watch every table, card and modal keep the product's own colour.
    for (const token of ["--surface", "--surface-raised", "--surface-overlay"]) {
      expect(css).toContain(`${token}: color-mix(in oklab, ${COLORS.background.light}`);
    }
  });

  it("lightens the surfaces in both themes", () => {
    // Toward white either way: that is the direction the shipped tokens go in light
    // (#fbfbfa to #ffffff) and in dark (#08080a upward). A card is a step above the
    // page in both, so a mode-dependent rule would only be one more thing to invert.
    const surfaces = [...css.matchAll(/--surface[a-z-]*: color-mix\([^;]+;/g)].map((m) => m[0]);
    expect(surfaces.length).toBeGreaterThan(0);
    for (const rule of surfaces) {
      expect(rule).toContain("white)");
    }
  });

  it("keeps the surfaces out of print with the rest of the background", () => {
    const screen = screenBlock(css);
    const surfaces = [...css.matchAll(/--surface[a-z-]*:/g)];
    expect(surfaces.length).toBeGreaterThan(0);
    for (const match of surfaces) {
      expect(match.index).toBeGreaterThan(css.length - screen.length - 1);
    }
  });

  it("derives the subtle step from the configured background", () => {
    // Fixed grey hover rows on a tinted page is the failure this avoids. Mixing
    // toward --text is what makes one expression right in both modes.
    expect(css).toContain(`color-mix(in oklab, ${COLORS.background.light} 96%, var(--text))`);
    expect(css).toContain(`color-mix(in oklab, ${COLORS.background.dark} 96%, var(--text))`);
  });

  it("picks a readable contrast colour for each primary", () => {
    expect(css).toContain("--brand-primary-contrast:");
  });
});
