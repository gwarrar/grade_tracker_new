/**
 * Locale-aware parsing and formatting.
 *
 * `parseLocaleNumber` is the highest-stakes function on the frontend. A German
 * teacher typing 88,5 into a grade field must not record 88 — `parseFloat` does
 * exactly that, silently, and the result is a wrong mark in a student's record.
 */

import { describe, expect, it } from "vitest";
import {
  formatDate,
  formatNumber,
  formatNumberForInput,
  formatPercent,
  parseLocaleNumber,
} from "../format";

describe("parseLocaleNumber", () => {
  it("parses a decimal point in English", () => {
    expect(parseLocaleNumber("88.5", "en")).toBe(88.5);
  });

  it("parses a decimal comma in German", () => {
    // parseFloat("88,5") returns 88 -- the bug this function exists to prevent.
    expect(parseLocaleNumber("88,5", "de")).toBe(88.5);
  });

  it("parses a decimal comma in French", () => {
    expect(parseLocaleNumber("88,5", "fr")).toBe(88.5);
  });

  it("strips English thousands separators", () => {
    expect(parseLocaleNumber("1,234.5", "en")).toBe(1234.5);
  });

  it("strips German thousands separators", () => {
    expect(parseLocaleNumber("1.234,5", "de")).toBe(1234.5);
  });

  it("tolerates the non-breaking spaces French grouping actually uses", () => {
    // These survive a copy-paste out of a spreadsheet.
    expect(parseLocaleNumber("1\u00a0234,5", "fr")).toBe(1234.5);
    expect(parseLocaleNumber("1\u202f234,5", "fr")).toBe(1234.5);
  });

  it("parses integers", () => {
    expect(parseLocaleNumber("85", "de")).toBe(85);
  });

  it("parses a leading decimal separator", () => {
    expect(parseLocaleNumber("0,5", "de")).toBe(0.5);
  });

  it("returns null rather than NaN for nonsense", () => {
    // Null is checkable; NaN silently poisons every arithmetic operation downstream.
    for (const input of ["", "   ", "abc", "8,5,5", "--3", "8..5"]) {
      expect(parseLocaleNumber(input, "en")).toBeNull();
    }
  });

  it("round-trips through formatNumber in every shipped locale", () => {
    for (const locale of ["en", "de", "fr"]) {
      const formatted = formatNumber(88.5, locale);
      expect(parseLocaleNumber(formatted, locale)).toBe(88.5);
    }
  });
});

describe("formatNumber", () => {
  it("uses the locale's decimal separator", () => {
    expect(formatNumber(88.5, "en")).toBe("88.5");
    expect(formatNumber(88.5, "de")).toBe("88,5");
  });

  it("renders missing data as an em dash, not zero", () => {
    // Absent data and a score of zero are different facts.
    expect(formatNumber(null, "en")).toBe("—");
    expect(formatNumber(undefined, "en")).toBe("—");
    expect(formatNumber(0, "en")).toBe("0");
  });
});

describe("formatPercent", () => {
  it("formats per locale", () => {
    expect(formatPercent(87.5, "en")).toContain("87.5");
    expect(formatPercent(87.5, "de")).toContain("87,5");
  });

  it("renders null as an em dash", () => {
    expect(formatPercent(null, "en")).toBe("—");
  });
});

describe("formatDate", () => {
  it("formats an ISO date per locale", () => {
    expect(formatDate("2026-01-15", "en")).toContain("2026");
    expect(formatDate("2026-01-15", "de")).toContain("2026");
  });

  it("does not shift the day across timezones", () => {
    // Parsed as UTC. Without that, a user west of Greenwich sees 14 January for a
    // grade dated the 15th.
    expect(formatDate("2026-01-15", "en", { day: "numeric" })).toBe("15");
  });

  it("passes through an unparseable value rather than showing Invalid Date", () => {
    expect(formatDate("not-a-date", "en")).toBe("not-a-date");
  });

  it("renders null as an em dash", () => {
    expect(formatDate(null, "en")).toBe("—");
  });
});

describe("parseLocaleNumber — malformed grouping", () => {
  it("rejects grouping that is not in threes", () => {
    // Naively stripping separators turned "8,5,5" into 855: a plausible-looking
    // number the user never typed, recorded without complaint.
    expect(parseLocaleNumber("8,5,5", "en")).toBeNull();
    expect(parseLocaleNumber("1,23", "en")).toBeNull();
    expect(parseLocaleNumber("1.23.456", "de")).toBeNull();
  });

  it("still accepts correct grouping", () => {
    expect(parseLocaleNumber("1,234", "en")).toBe(1234);
    expect(parseLocaleNumber("1,234,567.8", "en")).toBe(1234567.8);
    expect(parseLocaleNumber("1.234.567,8", "de")).toBe(1234567.8);
  });
});

describe("formatNumberForInput", () => {
  it("keeps every digit, because the value it seeds is submitted back", () => {
    // Three equally-weighted assessments. `formatNumber` caps at two fraction
    // digits, so opening a grade to fix a typo in its title rewrote the weight to
    // 0.33 and moved the course average, with nothing said.
    expect(formatNumberForInput(0.3333, "en")).toBe("0.3333");
    expect(formatNumberForInput(88.756, "en")).toBe("88.756");
    expect(formatNumber(0.3333, "en")).toBe("0.33");
  });

  it("uses the locale's decimal separator, so parseLocaleNumber reads it back", () => {
    expect(formatNumberForInput(0.3333, "de")).toBe("0,3333");
    expect(parseLocaleNumber(formatNumberForInput(0.3333, "de"), "de")).toBe(0.3333);
    expect(parseLocaleNumber(formatNumberForInput(1234.5, "fr"), "fr")).toBe(1234.5);
  });

  it("omits grouping, which a field about to be edited should not carry", () => {
    expect(formatNumberForInput(1234.5, "en")).toBe("1234.5");
    expect(formatNumberForInput(1234.5, "de")).toBe("1234,5");
  });

  it("renders absent as empty rather than an em dash", () => {
    expect(formatNumberForInput(null, "en")).toBe("");
    expect(formatNumberForInput(undefined, "en")).toBe("");
  });
});
