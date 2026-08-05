/**
 * Translation completeness and the override merge.
 *
 * A key present in English and missing in German does not fail the build — the user
 * simply sees `nav.students` where a label should be. Only a test catches that, and
 * only before it ships.
 */

import { describe, expect, it } from "vitest";

import de from "../../messages/de.json";
import en from "../../messages/en.json";
import fr from "../../messages/fr.json";
import { applyOverrides } from "../../i18n/merge";
import { locales, routing } from "../../i18n/routing";

type Tree = Record<string, unknown>;

/** Flatten a nested message tree into dotted key paths. */
function flatten(tree: Tree, prefix = ""): Set<string> {
  const keys = new Set<string>();
  for (const [key, value] of Object.entries(tree)) {
    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      for (const nested of flatten(value as Tree, `${prefix}${key}.`)) keys.add(nested);
    } else {
      keys.add(`${prefix}${key}`);
    }
  }
  return keys;
}

const CATALOGUES: Record<string, Tree> = { en, de, fr };

describe("routing", () => {
  it("ships a catalogue for every configured locale", () => {
    expect(Object.keys(CATALOGUES).sort()).toEqual([...locales].sort());
  });

  it("always prefixes the locale", () => {
    // Otherwise "/" and "/en" serve identical content at two URLs.
    expect(routing.localePrefix).toBe("always");
  });
});

describe("catalogue parity", () => {
  const english = flatten(en as Tree);

  it("English defines a non-trivial catalogue", () => {
    // Guards the comparisons below: an empty baseline would make them vacuous.
    expect(english.size).toBeGreaterThan(50);
  });

  for (const [locale, catalogue] of Object.entries(CATALOGUES)) {
    if (locale === "en") continue;

    it(`${locale} defines every English key`, () => {
      const missing = [...english].filter((key) => !flatten(catalogue as Tree).has(key));
      expect(missing).toEqual([]);
    });

    it(`${locale} defines no key English lacks`, () => {
      // A stray key is dead weight nobody will ever remove, because nothing
      // references it and nothing reports it.
      const extra = [...flatten(catalogue as Tree)].filter((key) => !english.has(key));
      expect(extra).toEqual([]);
    });

    it(`${locale} leaves no value untranslated`, () => {
      const shared = [...english].filter((k) => flatten(catalogue as Tree).has(k));
      const read = (tree: Tree, path: string) =>
        path.split(".").reduce<unknown>((node, part) => (node as Tree)?.[part], tree);

      // Words that are legitimately identical across locales: proper nouns, language
      // names in their own language, and cognates. Listed explicitly so each one is a
      // conscious decision — a blanket exemption would let a genuinely missed
      // translation through unnoticed.
      const allowed = new Set([
        "app.name",
        "locale.en",
        "locale.de",
        "locale.fr",
        "grade.max", // "Maximum" in all three
        "grade.date", // "Date" is the French word too
        "theme.system", // "Auto" in French
        "admin.title", // "Administration" is the French word too
        "admin.ai.name", // "Name" is the German word too
        "profile.name", // likewise
        "admin.ai.kind", // "Type" in French
        "admin.ai.effort", // "Effort" in French
        "assistant.title", // "Assistant" is the French word too
        "admin.users.status", // "Status" is the German word too
        "audit.system", // "System" is the German word too
        "audit.actionLabel", // "Action" is the French word too
      ]);
      const untranslated = shared.filter(
        (key) => !allowed.has(key) && read(en as Tree, key) === read(catalogue as Tree, key),
      );
      expect(untranslated).toEqual([]);
    });
  }
});

describe("every API error code has a message", () => {
  // The backend emits codes and no prose, so a code with no entry here reaches the
  // user as a raw identifier like STUDENT_NOT_FOUND.
  const CODES = [
    "STUDENT_NOT_FOUND", "COURSE_NOT_FOUND", "GRADE_NOT_FOUND", "DUPLICATE_ENTRY",
    "COURSE_FULL", "VALIDATION_ERROR", "NOT_AUTHENTICATED", "FORBIDDEN",
    "INVALID_CREDENTIALS", "ACCOUNT_DISABLED", "TOO_MANY_ATTEMPTS",
    "PAYLOAD_TOO_LARGE", "NO_GRADES_RECORDED", "OVERRIDE_NOT_FOUND",
  ];

  for (const [locale, catalogue] of Object.entries(CATALOGUES)) {
    it(`${locale} covers every backend code`, () => {
      const errors = (catalogue as Tree).error as Record<string, string>;
      expect(CODES.filter((code) => !errors[code])).toEqual([]);
    });

    it(`${locale} has a fallback for an unrecognised code`, () => {
      expect(((catalogue as Tree).error as Record<string, string>).unknown).toBeTruthy();
    });
  }
});

describe("applyOverrides", () => {
  const base = { nav: { students: "Students", courses: "Courses" }, top: "Top" } as Tree;

  it("returns the original when there is nothing to override", () => {
    expect(applyOverrides(base, {})).toBe(base);
  });

  it("replaces a nested value", () => {
    const merged = applyOverrides(base, { "nav.students": "Auszubildende" }) as Tree;
    expect((merged.nav as Tree).students).toBe("Auszubildende");
    expect((merged.nav as Tree).courses).toBe("Courses");
  });

  it("replaces a top-level value", () => {
    expect((applyOverrides(base, { top: "Oben" }) as Tree).top).toBe("Oben");
  });

  it("does not mutate the source", () => {
    // The catalogues are imported modules. Mutating one would leak an organisation's
    // overrides into every later request in the same process.
    applyOverrides(base, { "nav.students": "Changed" });
    expect((base.nav as Tree).students).toBe("Students");
  });

  it("ignores an override whose path runs through a string", () => {
    // "top" is a string, so "top.deeper" addresses nothing. Writing it anyway would
    // replace the string with an object and break every reference to it.
    const merged = applyOverrides(base, { "top.deeper": "x" }) as Tree;
    expect(merged.top).toBe("Top");
  });

  it("ignores an override for a path that does not exist", () => {
    const merged = applyOverrides(base, { "nothing.here": "x" }) as Tree;
    expect(merged).toEqual(base);
  });
});
