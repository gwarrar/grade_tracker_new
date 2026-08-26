# Grade Tracker — Frontend

Next.js 16 (App Router, Turbopack), React 19, TypeScript, Tailwind 4, next-intl,
TanStack Query, vitest.

## This is not the Next.js you know

Version 16 has breaking changes — APIs, conventions and file structure may all differ
from older references and from what a model was trained on. **Read the relevant guide
in `node_modules/next/dist/docs/` before writing code**, and heed deprecation
notices. The installed version is the authority, not a blog post.

## Running it

Use the root launcher: `.\dev.cmd` from the project root starts both halves. See the
root `README.md` for the rest.

**Always `corepack pnpm`, never bare `pnpm`.** `package.json` pins `pnpm@11.18.0` and
`.npmrc` sets a shared `store-dir`. A globally installed `pnpm` is usually older and
refuses to work against a `node_modules` that 11 built; the error names a store
mismatch rather than a version, which makes it easy to misread.

**Never run `pnpm build` while the dev server is up.** Both write `.next` and
Turbopack's cache does not survive two writers — it stops emitting chunks mid-build,
every route then answers 500, and no ordinary restart clears it. `.\dev.cmd fresh` is
the recovery.

```powershell
corepack pnpm check          # typecheck + lint + tests, in one
corepack pnpm test:coverage  # with the coverage floor applied
corepack pnpm gen:api        # after the backend's OpenAPI document changes
```

## Layout

| Path | Holds |
|---|---|
| `app/[locale]/` | Routes. `localePrefix: "always"`, so every path carries its locale. One `*-view.tsx` client component per screen. |
| `components/app/` | Pieces shared across screens. |
| `components/ui/` | Generic: `Modal`, `Confirm`. |
| `lib/` | Pure functions and hooks — the API client, query keys, formatting, contrast, permissions. Most of the test suite lives here. |
| `messages/` | `en` / `de` / `fr`. All three must carry every key. |

`lib/api-schema.d.ts` is generated from `docs/openapi.json`. Do not edit it — change
the backend and re-run `gen:api`. CI regenerates and diffs both.

### Routing and locale

`i18n/navigation.ts` exports the locale-aware `Link`, `useRouter` and `redirect`.
**Use those, not `next/navigation`** — the bare router drops the prefix and lands a
German user on the English page. Inside a client component, read the current locale
with next-intl's `useLocale()` rather than threading it down as a prop.

## The data layer

Four things, and using them is not optional if you want the cache to behave.

**`lib/api.ts`** — the typed client. `Response<"/students", "get">` derives the
response type from the generated schema, so a renamed field is a compile error rather
than `undefined` at runtime. It throws `ApiError` carrying the backend's `code`.

**`lib/query-keys.ts`** — every cache key. Never write a key literal inline. Two
defects came from doing that: the same student report cached under both
`["report",…]` and `["reports",…]` so one screen showed a stale average, and a
picker's key nested under another picker's so invalidating one silently invalidated a
query with different parameters. `lib/__tests__/query-keys.test.ts` pins both.

Use `root` as the invalidation handle, and `academicRoots` after a write that touches
a student, course, grade or enrolment — one shared list, so it cannot drift the way
three private ones did.

**`lib/use-api-error.ts`** — `errorCode(error)` for the code, `useApiError()` for a
translated sentence. This is the only place an error code is cast to a message key;
it used to be written out forty-five times.

**`components/app/list-status.tsx`** — loading, error and empty for a list. Use it
rather than writing the branches: all three list screens once wrote loading and empty
and forgot error, so a failed request rendered "No data" and told a teacher their
course was empty.

## The design system

`app/globals.css` defines the classes. Reach for them before writing Tailwind:

| Class | For |
|---|---|
| `.btn`, `.btn-primary`, `.btn-ghost`, `.btn-danger` | Buttons |
| `.field-input` | Text inputs outside `detail-fields` |
| `.data-table` | Tables |
| `.badge`, `.badge-pass`, `.badge-warn` | Status pills |
| `.empty` | The loading/empty/error slab — usually via `ListStatus` |

`components/app/detail-fields.tsx` holds the form primitives — `Field`, `Input`,
`Select`, `Textarea`, `FormError`, `PanelHeader`, `FieldHelp`. Use them rather than
raw inputs: they wire `id`/`htmlFor` and `aria-describedby`, which a hand-rolled
`<input>` reliably forgets.

Three properties of `FieldHelp` look like styling and are not — hover *and* focus,
hidden by opacity rather than `display`, positioned `fixed`. Each was a live defect
first; `docs/DECISIONS.md` §19 explains all three.

## Testing

vitest runs in `node` by default. A test needing a DOM opts in **per file**:

```ts
/**
 * @vitest-environment jsdom
 */
```

vitest 4 removed `environmentMatchGlobs`, so there is no glob-based alternative.

Coverage is measured over `lib/` and `components/` with a floor in
`vitest.config.ts`, deliberately not over `app/` — including the untested view
components would peg the floor to the backlog rather than to the change in hand.

### The jsdom trap, which has produced false positives twice

**jsdom applies no CSS and returns zeroed rects.** Tailwind classes have no computed
effect and every `getBoundingClientRect()` is `0`. So:

- `getComputedStyle(el).display` is never `"none"` however the class reads.
- `toBeVisible()` and `toHaveAccessibleDescription()` pass against an element a
  browser would hide entirely.

Both were probed against a deliberately reintroduced bug and both stayed green. When
the decision *is* the class — `opacity-0` rather than `hidden`, `fixed` rather than
`absolute` — assert the class list and say in the test why. It reads like the wrong
instinct, which is exactly why it needs the comment.

**A test that cannot fail is worse than no test**, because it reports safety that is
not there. When a test is written for a specific bug, break the code and watch it go
red before trusting it.

## What the linter enforces beyond the defaults

`eslint.config.mjs` adds the full `jsx-a11y` recommended set on top of the eight
rules `eslint-config-next` bundles — the ones that catch a control nobody can reach
are not among the defaults — and two type-aware rules,
`@typescript-eslint/no-floating-promises` and `no-misused-promises`. In a codebase
built on TanStack Query, a mutation whose promise nobody awaits fails silently.

`tsconfig.json` runs `strict` plus `noUncheckedIndexedAccess`, so `array[0]` is
`T | undefined` until you prove otherwise. That flag found eight real cases in
shipped code when it was turned on.
