import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";
import tseslint from "typescript-eslint";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // `eslint-config-next` bundles about eight jsx-a11y rules -- alt text, aria prop
  // names, role validity. The ones that catch a control nobody can reach are not
  // among them: an input with no label, a click handler on a div, an autofocus that
  // moves a screen reader without warning. This adds the recommended set.
  //
  // Rules only, no `plugins` key: eslint-config-next has already registered the
  // plugin, and flat config treats a second registration of the same name as an
  // error rather than a merge.
  {
    files: ["**/*.{ts,tsx}"],
    rules: jsxA11y.flatConfigs.recommended.rules,
  },
  // Type-aware rules. `eslint-config-next/typescript` ships the subset that needs
  // no type information, which leaves out the two that matter most in a codebase
  // built on TanStack Query: a mutation whose promise nobody awaits fails silently,
  // and an async function passed where a void callback is expected turns a rejection
  // into an unhandled one. Both are invisible to a non-type-aware linter.
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "@typescript-eslint": tseslint.plugin },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": [
        "error",
        // A form's `onSubmit` is the one place an async handler is idiomatic React,
        // and every one of ours already catches through a mutation.
        { checksVoidReturn: { attributes: false } },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
