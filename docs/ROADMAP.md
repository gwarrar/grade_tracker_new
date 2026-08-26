# Roadmap

What is actually open, in the order it will be built.

`PROJECT_IMPLEMENTATION_PLAN.md` — the SaaS and LMS pivot — is **on hold with no
start date**. It is a real plan and it has not been abandoned, but nothing in it
is being worked on, and reading it as the current backlog sends you to the wrong
work. This file is the current backlog.

---

## 1. Component test coverage

Seven components have DOM tests out of sixteen. Three of the last four defects
reported from using the application were ones a component test would have caught
first — a hidden tooltip that a type checker cannot see, a header that renders
the wrong thing, a form that submits a field it never showed.

Priority is cost-of-failure, not file size. In order:

| Screen | Why it is first | State |
|---|---|---|
| Student account creation | Generated passwords are stored hashed and shown once. A card that drops a row destroys a credential nobody can recover. | **Done** — `credentials.dom.test.tsx`, `student-account-link.dom.test.tsx` |
| The grade edit panel | It writes to a transcript. | Open |
| The assessments editor | Round-trips an ordered list through `FormData` — the failure mode is silent reordering. | Open |
| Branding: grading scale and the contrast refusal | The refusal path is the one that protects readability, and nothing exercises it in a browser. | Open |
| The import wizard | It is the only bulk write, and its per-row error reporting is what makes a partial import survivable. | Open |

Not a coverage target. A component gets a test when being wrong about it is
expensive, and the table is that list.

**The thing blocking the rest**, as of 2026-08-26: there is no shared render
helper, so every DOM test rebuilds ~25 lines of `NextIntlClientProvider` +
`QueryClientProvider` scaffolding by hand. That fixed cost per file is why the
eight view components — 5,481 lines — have no tests at all. Write the helper
first; the four rows above get much cheaper afterwards.

The frontend coverage floor in `web/vitest.config.ts` is set just under what the
suite reaches today. Raise it as these land.

## 2. Trend chart

`ReportingService.distribution_report` already returns ordered buckets with
zero-filled bands, and its own docstring says the payload was shaped for a stacked
area chart. What the reports screen does with it today is render one horizontal
bar group per bucket — which shows each month accurately and answers nothing about
the movement between them, which is the entire question.

Hand-rolled SVG, following the reasoning already written at
`web/components/app/distribution.tsx:18`: a charting dependency here ships a
rendering engine to draw a handful of shapes.

## 3. Saved views

Filters already live in URL parameters via `useUrlParam`, so a saved view is a
named query string and very little else. Persisted per user rather than in the
browser, so it survives a different machine.

The most speculative of the three. It gets built last because nobody has yet
asked for it twice.

---

## Not on this list, and why

- **A second server process, Docker, Redis, Sentry.** Each is one command away
  the moment there is a second machine or a second developer. See
  `DECISIONS.md` §15.
- **Postgres.** Triggered by topology, not data volume. `DECISIONS.md` §1.
- **Narrowing teacher visibility in the summary report.** Decided as-is;
  `DECISIONS.md` §20 records what would reverse it.
