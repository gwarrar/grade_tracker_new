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
