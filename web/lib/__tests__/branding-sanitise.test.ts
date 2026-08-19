import { describe, expect, it } from "vitest";

import { sanitiseColors } from "@/components/branding/branding";

const OK = {
  primary: { light: "#2e5bff", dark: "#7c9bff" },
  accent: { light: "#00a37a", dark: "#3dd9ac" },
  background: { light: "#fbfbfa", dark: "#08080a" },
};

describe("sanitiseColors", () => {
  it("passes plain hex through untouched, in both notations", () => {
    expect(sanitiseColors(OK)).toEqual(OK);
    const short = { ...OK, primary: { light: "#abc", dark: "#DEF" } };
    expect(sanitiseColors(short).primary).toEqual({ light: "#abc", dark: "#DEF" });
  });

  it("replaces a value that would close the style element", () => {
    const attack = {
      ...OK,
      primary: { light: "#000</style><script>alert(1)</script>", dark: "#7c9bff" },
    };

    const result = sanitiseColors(attack);

    expect(result.primary.light).toBe("#2e5bff");
    expect(JSON.stringify(result)).not.toContain("</style>");
    expect(JSON.stringify(result)).not.toContain("script");
  });

  it("replaces a value that would escape the declaration without any script", () => {
    // The quieter half: no tag, just a brace, and the whole application is blank.
    const attack = { ...OK, background: { light: "#fff; } html { display: none } :root {", dark: "#08080a" } };

    expect(sanitiseColors(attack).background.light).toBe("#fbfbfa");
  });

  it("replaces values that are merely not colours", () => {
    const junk = {
      primary: { light: "", dark: "rgb(1,2,3)" },
      accent: { light: "red", dark: "#12345" },
      background: { light: "var(--x)", dark: "#08080a" },
    };

    const result = sanitiseColors(junk);

    expect(result.primary).toEqual(OK.primary);
    expect(result.accent).toEqual(OK.accent);
    expect(result.background.light).toBe("#fbfbfa");
    // The one good value in the object survives.
    expect(result.background.dark).toBe("#08080a");
  });
});
