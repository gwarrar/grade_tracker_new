# Grade Tracker — Frontend

Next.js (App Router, Turbopack), React 19, TypeScript, Tailwind 4, next-intl,
TanStack Query, vitest.

**Read `AGENTS.md` before writing code.** This is not the Next.js most references
describe; check `node_modules/next/dist/docs/` for the version actually installed.

## Running it

Use the root launcher — `.\dev.cmd` from the project root starts both halves. See
the root `README.md` for the rest.

**Always `corepack pnpm`, never bare `pnpm`.** `package.json` pins `pnpm@11.18.0`
and `.npmrc` sets a shared `store-dir`. A globally installed `pnpm` is usually
older and refuses to work against a `node_modules` that 11 built; the error names
a store mismatch rather than a version, which makes it easy to misread.

**Never run `pnpm build` while the dev server is up.** Both write `.next` and
Turbopack's cache does not survive two writers — it stops emitting chunks
mid-build, every route then answers 500, and no ordinary restart clears it.
`.\dev.cmd fresh` is the recovery.

```powershell
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm test
corepack pnpm gen:api     # after the backend's OpenAPI document changes
```

## Layout

| Path | Holds |
|---|---|
| `app/[locale]/` | Routes. One `*-view.tsx` client component per screen, kept whole rather than split into a component tree nobody can follow. |
| `components/app/` | Pieces shared across screens. `detail-fields.tsx` is the form primitives every panel is built from. |
| `components/ui/` | Generic: `Modal`, `Confirm`. |
| `lib/` | Pure functions — formatting, contrast, permissions, the API client. Almost all of the test suite lives against these. |
| `messages/` | `en` / `de` / `fr`. All three must carry every key; `message-keys.test.ts` fails otherwise. |

`lib/api-schema.d.ts` is generated from `docs/openapi.json`. Do not edit it —
change the backend and re-run `gen:api`.

## Testing

vitest runs in `node` by default. A test needing a DOM opts in **per file**:

```ts
/**
 * @vitest-environment jsdom
 */
```

vitest 4 removed `environmentMatchGlobs`, so there is no glob-based alternative.

### The jsdom trap, which has produced false positives twice

**jsdom applies no CSS and returns zeroed rects.** Tailwind classes have no
computed effect and every `getBoundingClientRect()` is `0`. So:

- `getComputedStyle(el).display` is never `"none"` however the class reads.
- `toBeVisible()` and `toHaveAccessibleDescription()` pass against an element that
  a browser would hide entirely.

Both were probed against a deliberately reintroduced bug and both stayed green.
When the decision *is* the class — `opacity-0` rather than `hidden`, `fixed`
rather than `absolute` — assert the class list and say in the test why. It reads
like the wrong instinct, which is exactly why it needs the comment.

**A test that cannot fail is worse than no test**, because it reports safety that
is not there. When a test is written for a specific bug, break the code and watch
it go red before trusting it.
