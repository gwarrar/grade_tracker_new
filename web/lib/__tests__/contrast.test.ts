/**
 * WCAG contrast maths.
 *
 * The dual-mode check is the point: an administrator picks a colour on a white
 * screen and cannot see that it is invisible to every dark-mode user.
 */

import { describe, expect, it } from "vitest";
import {
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
