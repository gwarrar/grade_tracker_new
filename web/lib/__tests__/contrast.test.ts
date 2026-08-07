/**
 * WCAG contrast maths.
 *
 * The dual-mode check is the point: an administrator picks a colour on a white
 * screen and cannot see that it is invisible to every dark-mode user.
 */

import { describe, expect, it } from "vitest";
import {
  checkBackground,
  checkBothModes,
  checkContrast,
  contrastRatio,
  parseHex,
  readableTextOn,
  suggestDarkVariant,
} from "../contrast";

describe("parseHex", () => {
  it("accepts long and short form, with or without a hash", () => {
    expect(parseHex("#ffffff")).toEqual([255, 255, 255]);
    expect(parseHex("ffffff")).toEqual([255, 255, 255]);
    expect(parseHex("#fff")).toEqual([255, 255, 255]);
  });

  it("rejects anything else", () => {
    for (const input of ["", "#ff", "#gggggg", "rgb(0,0,0)", "blue"]) {
      expect(parseHex(input)).toBeNull();
    }
  });
});

describe("contrastRatio", () => {
  it("gives 21 for black on white", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 1);
  });

  it("gives 1 for a colour against itself", () => {
    expect(contrastRatio("#2e5bff", "#2e5bff")).toBeCloseTo(1, 2);
  });

  it("is symmetric", () => {
    expect(contrastRatio("#2e5bff", "#ffffff")).toBeCloseTo(
      contrastRatio("#ffffff", "#2e5bff"),
      5,
    );
  });
});

describe("checkContrast", () => {
  it("classifies WCAG levels", () => {
    const black = checkContrast("#000000", "#ffffff");
    expect(black.passesAA).toBe(true);
    expect(black.passesAAA).toBe(true);

    const faint = checkContrast("#cccccc", "#ffffff");
    expect(faint.passesAA).toBe(false);
  });
});

describe("checkBothModes", () => {
  it("accepts the shipped default palette", () => {
    expect(checkBothModes("#2e5bff", "#7c9bff").usable).toBe(true);
  });

  it("rejects a colour readable on white but not on near-black", () => {
    // The exact trap the checker exists for: an admin picks navy on a light screen
    // and every dark-mode user gets an invisible button.
    const result = checkBothModes("#000080", "#000080");
    expect(result.light.passesAALarge).toBe(true);
    expect(result.dark.passesAALarge).toBe(false);
    expect(result.usable).toBe(false);
  });

  it("rejects a colour readable on black but not on white", () => {
    const result = checkBothModes("#ffff99", "#ffff99");
    expect(result.dark.passesAALarge).toBe(true);
    expect(result.light.passesAALarge).toBe(false);
    expect(result.usable).toBe(false);
  });
});

describe("suggestDarkVariant", () => {
  it("lightens a dark brand colour until it passes", () => {
    const suggested = suggestDarkVariant("#000080");
    expect(checkContrast(suggested, "#08080a").passesAALarge).toBe(true);
  });

  it("leaves an already-usable colour usable", () => {
    expect(checkContrast(suggestDarkVariant("#7c9bff"), "#08080a").passesAALarge).toBe(true);
  });

  it("returns the input unchanged when it cannot be parsed", () => {
    expect(suggestDarkVariant("nonsense")).toBe("nonsense");
  });
});

describe("readableTextOn", () => {
  it("picks dark text on a light background and light text on a dark one", () => {
    expect(readableTextOn("#ffffff")).toBe("#08080a");
    expect(readableTextOn("#000000")).toBe("#ffffff");
    expect(readableTextOn("#2e5bff")).toBe("#ffffff");
  });
});

describe("configured backgrounds", () => {
  it("judges brand colours against the background in force", () => {
    // The gate has to follow the configuration. A mid-blue readable on the shipped
    // near-black is not readable on a lighter charcoal, and validating against the
    // shipped value would have passed it anyway.
    const shipped = checkBothModes("#2e5bff", "#5b7cff");
    const lighter = checkBothModes("#2e5bff", "#5b7cff", {
      light: "#fbfbfa",
      dark: "#5a5a68",
    });

    expect(shipped.dark.ratio).toBeGreaterThan(lighter.dark.ratio);
  });

  it("aims the dark suggestion at the background it is given", () => {
    const forShipped = suggestDarkVariant("#00332a");
    const forLighter = suggestDarkVariant("#00332a", "#6a6a75");

    // A lighter backdrop needs a lighter counterpart to clear the same threshold.
    expect(forLighter).not.toBe(forShipped);
  });
});

describe("checkBackground", () => {
  it("accepts the shipped backgrounds", () => {
    // A gate that rejects its own defaults is a gate nobody trusts.
    expect(checkBackground("#fbfbfa", "#08080a").usable).toBe(true);
  });

  it("rejects a light background that swallows body text", () => {
    // `--text` is #14140f and is not configurable, so a mid-grey page is unreadable
    // no matter what the brand colours do — and the brand gate would not notice,
    // because a dark brand colour on a dark page can still pass.
    expect(checkBackground("#5a5a5a", "#08080a").usable).toBe(false);
  });

  it("rejects a dark background that is too pale for its text", () => {
    expect(checkBackground("#fbfbfa", "#9a9aa0").usable).toBe(false);
  });

  it("is decided by the worse of body and muted text", () => {
    // Muted text fails first, so a background that passes only `--text` must still
    // be refused — half-legible is not a state worth shipping.
    const result = checkBackground("#7d7d76", "#08080a");
    expect(result.light.passesAA).toBe(false);
  });
});
