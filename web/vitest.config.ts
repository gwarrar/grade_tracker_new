import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * Two things this file exists for, both of which were absent.
 *
 * **A DOM.** There was no vitest config at all, so the environment was `node` and
 * every test was a pure function. Nothing exercised an event handler, an effect, or
 * a query state transition — and every interface bug this project has actually shipped
 * lived in exactly that gap: a spinner that never stopped because a disabled query
 * stays `pending` forever, a keydown listener that threw on events carrying no `key`,
 * a hydration mismatch from a list built at module scope. A type checker cannot see
 * any of those.
 *
 * **The `@/` alias.** Tests had to reach their subjects by relative path, which is
 * why the contrast maths lives in `lib/` and the components that use it had no tests
 * at all — importing one pulled in `@/lib/api` and failed to resolve.
 *
 * The default environment stays `node`: booting jsdom costs real time and the ~150
 * pure-function tests have no use for it. A file that needs a DOM asks for one with
 * a `@vitest-environment jsdom` docblock. That is per-file rather than a glob
 * because vitest 4 removed `environmentMatchGlobs`, and because a test file saying
 * what it needs at the top beats a pattern in another file that has to be matched
 * by filename.
 */
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "node",
    // Measured, but only over the modules tests actually reach. Including every
    // view would set the floor at whatever the eight untested screens happen to
    // drag it to, which is a number about the backlog rather than about this
    // change -- and a floor that moves with unrelated work is not a gate.
    coverage: {
      provider: "v8",
      include: ["lib/**/*.ts", "components/**/*.tsx"],
      exclude: ["lib/api-schema.d.ts", "**/__tests__/**", "**/*.test.*"],
      reporter: ["text-summary"],
      // Set just under what the suite measures today (lines 50.1, branches 43.9,
      // functions 44.0, statements 49.7). A floor above current coverage fails
      // the build on arrival; a floor at zero is decoration. Raise it when the
      // view tests in docs/ROADMAP.md land.
      thresholds: { lines: 48, functions: 42, branches: 42, statements: 47 },
    },
    setupFiles: ["./vitest.setup.ts"],
  },
});
