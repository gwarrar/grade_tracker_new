import { describe, expect, it } from "vitest";

import { validateGradingScale } from "../grading-scale";

const DEFAULT_SCALE = [
  { min_percentage: 90, label: "A" },
  { min_percentage: 80, label: "B" },
  { min_percentage: 70, label: "C" },
  { min_percentage: 60, label: "D" },
  { min_percentage: 0, label: "F" },
];

describe("validateGradingScale", () => {
  it("rejects out-of-order bands", () => {
    expect(
      validateGradingScale([
        { min_percentage: 80, label: "B" },
        { min_percentage: 90, label: "A" },
        { min_percentage: 0, label: "F" },
      ]),
    ).toBe("order");
  });

  it("rejects a scale without a band at zero", () => {
    expect(
      validateGradingScale([
        { min_percentage: 90, label: "A" },
        { min_percentage: 10, label: "F" },
      ]),
    ).toBe("zero");
  });

  it("rejects duplicate thresholds", () => {
    expect(
      validateGradingScale([
        { min_percentage: 90, label: "A" },
        { min_percentage: 90, label: "A-" },
        { min_percentage: 0, label: "F" },
      ]),
    ).toBe("duplicate");
  });

  it("rejects thresholds outside a finite percentage range", () => {
    expect(
      validateGradingScale([
        { min_percentage: Number.POSITIVE_INFINITY, label: "A" },
        { min_percentage: 0, label: "F" },
      ]),
    ).toBe("percentage");
    expect(
      validateGradingScale([
        { min_percentage: 101, label: "A" },
        { min_percentage: 0, label: "F" },
      ]),
    ).toBe("percentage");
  });

  it("rejects blank displayed labels", () => {
    expect(
      validateGradingScale([
        { min_percentage: 90, label: "   " },
        { min_percentage: 0, label: "F" },
      ]),
    ).toBe("label");
  });

  it("accepts the valid default", () => {
    expect(validateGradingScale(DEFAULT_SCALE)).toBeNull();
  });
});

describe("grade points", () => {
  it("accepts a scale that prices nothing", () => {
    // Points are optional: a GPA only means something once somebody decides what an
    // A is worth, and an institution that never does is not in an invalid state.
    expect(validateGradingScale([{ min_percentage: 0, label: "F" }])).toBeNull();
  });

  it("accepts a scale that prices every band", () => {
    expect(
      validateGradingScale([
        { min_percentage: 90, label: "A", points: 4 },
        { min_percentage: 0, label: "F", points: 0 },
      ]),
    ).toBeNull();
  });

  it("accepts points that run opposite to the thresholds", () => {
    // A German 1-6 scale awards its lowest number to its highest threshold. Any rule
    // tying points to percentage would silently invert it.
    expect(
      validateGradingScale([
        { min_percentage: 92, label: "1", points: 1 },
        { min_percentage: 0, label: "6", points: 6 },
      ]),
    ).toBeNull();
  });

  it("rejects negative points", () => {
    expect(
      validateGradingScale([{ min_percentage: 0, label: "F", points: -1 }]),
    ).toBe("points");
  });

  it("rejects points that are not a number", () => {
    // An emptied box sends null, which is unset; NaN is a typo and must not save.
    expect(
      validateGradingScale([{ min_percentage: 0, label: "F", points: Number.NaN }]),
    ).toBe("points");
  });
});
