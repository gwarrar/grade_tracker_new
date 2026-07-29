/**
 * The dark values exist twice and must stay identical.
 *
 * Once under `.dark`, for an explicit choice. Once under
 * `@media (prefers-color-scheme: dark)`, for "follow the system" — which is what
 * lets the theme work with no JavaScript and no pre-hydration script.
 *
 * Duplication in CSS is not avoidable here: a media query and a class cannot share
 * one rule. What *is* avoidable is silent drift, where someone edits one block and
 * auto-mode quietly stops matching dark-mode. Hence this file.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "tokens.css"), "utf8");

/** Every `--name: value` declaration inside the first block matching `pattern`. */
function declarationsIn(pattern: RegExp): Map<string, string> {
  const match = pattern.exec(css);
  if (!match) throw new Error(`block not found: ${pattern}`);

  const declarations = new Map<string, string>();
  for (const line of match[1].split("\n")) {
    const parsed = /^\s*(--[\w-]+)\s*:\s*(.+?);/.exec(line);
    if (parsed) declarations.set(parsed[1], parsed[2].trim());
  }
  return declarations;
}

const explicit = declarationsIn(/\n\.dark \{\n([\s\S]*?)\n\}\n/);
const viaQuery = declarationsIn(
  /@media \(prefers-color-scheme: dark\) \{\n\s*:root:not\(\.light\):not\(\.dark\) \{\n([\s\S]*?)\n {2}\}/,
);

describe("dark tokens", () => {
  it("both blocks are non-trivial", () => {
    // Guards the comparisons below: two empty maps are trivially equal, and the
    // suite would pass while the file said nothing.
    expect(explicit.size).toBeGreaterThan(20);
    expect(viaQuery.size).toBeGreaterThan(20);
  });

  it("the OS query defines exactly the same names as .dark", () => {
    expect([...viaQuery.keys()].sort()).toEqual([...explicit.keys()].sort());
  });

  it("every value matches", () => {
    const different = [...explicit.entries()]
      .filter(([name, value]) => viaQuery.get(name) !== value)
      .map(([name]) => name);

    expect(different).toEqual([]);
  });
});

describe("light tokens", () => {
  const light = declarationsIn(/\n:root \{\n([\s\S]*?)\n\}\n/);

  it("every dark token has a light counterpart", () => {
    // The rule the design system rests on: a token defined in only one mode is a
    // colour that disappears in the other.
    const missing = [...explicit.keys()].filter((name) => !light.has(name));

    // --ring is the documented exception: it is a reference to --brand-primary,
    // which is itself redefined per mode, so it needs no second definition.
    expect(missing.filter((name) => name !== "--ring")).toEqual([]);
  });
});
