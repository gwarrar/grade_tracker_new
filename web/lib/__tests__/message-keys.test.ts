/**
 * Every translation key a component asks for must exist.
 *
 * The parity test next door compares the three catalogues with each other, so a key
 * missing from *all* of them is missing consistently and passes. That is exactly how
 * `nav.audit`, `audit.history`, `audit.empty` and five of the ten framework error
 * codes reached users as literal strings like `error.NOT_FOUND` — nothing renders a
 * page during the test run, and `t()` only fails at runtime.
 *
 * So this reads the source instead: every `t("…")` call, resolved against the
 * `useTranslations("namespace")` it belongs to, has to exist in English.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";

const ROOTS = ["app", "components"];
const SOURCE = /\.tsx?$/;

/** Every .ts/.tsx file under the given directory. */
function sources(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) found.push(...sources(path));
    else if (SOURCE.test(entry)) found.push(path);
  }
  return found;
}

/** Whether a dotted path resolves to a string in the catalogue. */
function resolves(path: string): boolean {
  let node: unknown = en;
  for (const part of path.split(".")) {
    if (typeof node !== "object" || node === null || !(part in node)) return false;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string";
}

/**
 * Translation keys a file asks for, as full dotted paths.
 *
 * A file may hold several `useTranslations` scopes. Rather than track which call
 * each `t()` belongs to — the variable is often renamed, as with `tError` or
 * `tAction` — a key counts as present if it resolves under *any* namespace declared
 * in that file, or at the root. That under-reports a key used with the wrong scope,
 * and never reports one that exists nowhere, which is the failure worth catching.
 */
function keysIn(source: string): string[] {
  const namespaces = [...source.matchAll(/useTranslations\(\s*"([^"]*)"\s*\)/g)].map((m) => m[1]);
  if (/useTranslations\(\s*\)/.test(source)) namespaces.push("");
  if (namespaces.length === 0) return [];

  const calls = [...source.matchAll(/\bt[A-Za-z]*\(\s*"([a-zA-Z0-9_.]+)"/g)].map((m) => m[1]);
  return calls.filter(
    (key) => !namespaces.some((ns) => resolves(ns ? `${ns}.${key}` : key)),
  );
}

describe("every translation key a component uses exists", () => {
  const files = ROOTS.flatMap((root) => sources(root));

  it("finds the source tree", () => {
    // Guards the assertion below: an empty file list would make it vacuous.
    expect(files.length).toBeGreaterThan(20);
  });

  for (const file of files) {
    const missing = keysIn(readFileSync(file, "utf8"));
    if (missing.length === 0) continue;
    it(`${file.replace(/\\/g, "/")} resolves every key`, () => {
      expect(missing).toEqual([]);
    });
  }
});
