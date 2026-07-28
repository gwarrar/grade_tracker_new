/**
 * The shipped brand colours must be readable in both themes.
 *
 * The contrast checker was written to gate what an administrator picks. It had
 * never been pointed at the defaults the product ships with — which is the one
 * palette every installation sees before anyone customises anything, and the one
 * nobody is prompted to check.
 */

import { describe, expect, it } from "vitest";

import { checkBothModes, checkContrast, readableTextOn } from "../contrast";

// The FALLBACK branding in components/branding/branding.tsx. Duplicated here
// deliberately: importing it would pull a server component and its fetch into a
// unit test, and a copy that drifts is exactly what this test would catch.
const PRIMARY = { light: "#2e5bff", dark: "#7c9bff" };
const ACCENT = { light: "#00a37a", dark: "#3dd9ac" };

describe("shipped brand colours", () => {
  it("primary passes AA against both surfaces", () => {
    const result = checkBothModes(PRIMARY.light, PRIMARY.dark);

    expect(
      result.usable,
      `light ${result.light.ratio.toFixed(2)}:1, dark ${result.dark.ratio.toFixed(2)}:1`,
    ).toBe(true);
  });

  it("accent passes AA against both surfaces", () => {
    const result = checkBothModes(ACCENT.light, ACCENT.dark);

    expect(
      result.usable,
      `light ${result.light.ratio.toFixed(2)}:1, dark ${result.dark.ratio.toFixed(2)}:1`,
    ).toBe(true);
  });

  it("rejects a colour that only works in one theme", () => {
    // The counterweight. Near-black passes on a light surface and fails on a dark
    // one, and `usable` must say so — otherwise the two tests above would pass for
    // a checker that returned true unconditionally.
    const result = checkBothModes("#111111", "#111111");

    expect(result.light.passesAA).toBe(true);
    expect(result.dark.passesAA).toBe(false);
    expect(result.usable).toBe(false);
  });

  it("picks readable text to sit on a solid brand fill", () => {
    // What --brand-primary-contrast resolves to: the colour of a label inside a
    // filled button, which is a different question from the fill's own legibility.
    expect(checkContrast(readableTextOn(PRIMARY.light), PRIMARY.light).passesAA).toBe(true);
    expect(checkContrast(readableTextOn(ACCENT.dark), ACCENT.dark).passesAA).toBe(true);
  });
});
