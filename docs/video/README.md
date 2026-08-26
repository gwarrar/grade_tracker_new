# Project overview video

The animated overview embedded at the top of the root `README.md`.

## Why this is its own package

Nothing here is a dependency of the application. `web/` never installs it, CI never
builds it, and `pnpm install` at the app level does not see it — Remotion pulls a
headless Chrome to render, and that cost has no business in a build that only has to
type-check a grade book.

The rendered files in `../media/` are committed; the tooling that produces them is
not required to use the repository.

## Rendering

```powershell
corepack pnpm install --ignore-workspace
corepack pnpm render:mp4     # ../media/overview.mp4  — 1920x1080, 24s
corepack pnpm render:gif     # ../media/overview.gif  — 720px, every 5th frame
corepack pnpm studio         # preview and scrub while editing
```

The GIF is the one the README embeds: GitHub renders an animated GIF inline from a
repository path and will not play an MP4 from one. It is deliberately small — half
scale at every fifth frame, 960x540 and about 2.3 MB — because the whole repository
was 2 MB before it arrived.

**Use `--scale`, never `--width`.** `--width=720` sets the output width and leaves
the height at the composition's 1080, so a 1920-wide frame is *cropped* to its left
720 pixels rather than scaled down. The first GIF shipped that way: the right-hand
third of every scene was missing, and the file was larger for it. `--scale=0.5`
resizes the whole frame and keeps the aspect ratio.

## What it shows, and what it does not

Six four-second scenes: the product, a dashboard, the layering, the scope default,
the AI boundary, and the gates that have to pass before anything merges.

There are **no screenshots of the running application**. Everything is drawn from
the design tokens rather than captured, which keeps it honest — a mocked-up
screenshot that does not match the real screen is worse than no screenshot. If real
captures are wanted, put them in `../media/shots/` and they can be composited in.

The figures on the last scene are real and were measured, not invented. When they
drift, re-render.

## Editing

- `src/Overview.tsx` — the six scenes and their timing
- `src/parts.tsx` — the reusable pieces (`Stat`, `Bar`, `Node`, `Reveal`, …)
- `src/theme.ts` — the palette, copied from the app's dark tokens rather than
  imported, so a rebrand does not silently change the video

Everything animates off `useCurrentFrame()`, never CSS transitions: a renderer draws
frame N directly and never plays the frames before it, so a CSS animation would come
out as a still of its own starting state.
