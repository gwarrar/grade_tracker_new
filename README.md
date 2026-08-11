# Grade Tracker

Grade Tracker is a FastAPI and Next.js application for academic records, reporting, AI-assisted workflows, and the planned multi-institution learning platform.

## Project documentation

- [Roadmap](docs/ROADMAP.md) — what is being built next
- [Architecture](docs/ARCHITECTURE.md)
- [Architecture decisions](docs/DECISIONS.md) — each with what would reverse it
- [Backend guide](backend/README.md)
- [Frontend guide](web/README.md)
- [OpenAPI document](docs/openapi.json)
- [Secure SaaS and LMS implementation plan](PROJECT_IMPLEMENTATION_PLAN.md) — **on hold**

`docs/ROADMAP.md` is the current backlog. The SaaS and LMS implementation plan is on hold with no start date: it remains the reference for security posture, backup and recovery, performance budgets, hybrid video storage, tenancy, billing and LMS scope *when that work begins*, but nothing in it is being worked on now, and reading it as the backlog sends you to the wrong work.

## Local development

Prerequisites:

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 22
- pnpm 11, via Corepack — **run it as `corepack pnpm`, not `pnpm`**

`web/package.json` pins `pnpm@11.18.0` and `web/.npmrc` sets a shared `store-dir`.
A `pnpm` installed globally is usually an older one, and it will refuse to work
against a `node_modules` that pnpm 11 built — the error names a store mismatch,
not a version, which is why it is worth stating here. `corepack pnpm` always
resolves to the pinned version. If Corepack has not been enabled on this machine:

```powershell
corepack enable
corepack prepare pnpm@11.18.0 --activate
```

Create the root environment file once:

```powershell
Copy-Item .env.example .env
```

Edit `.env`, replace `SECRET_KEY`, and configure an AI provider key only if AI features are being tested. Never commit `.env`.

Install dependencies once (`uv sync` in `backend`, `corepack pnpm install` in `web`), then run both servers with one command:

```powershell
.\dev.cmd            # migrate, seed if empty, start both, wait until they answer
.\dev.cmd stop
.\dev.cmd restart    # after a backend change: uvicorn runs without --reload here
.\dev.cmd fresh      # restart, deleting web/.next first — for a broken dev build
.\dev.cmd status
.\dev.cmd logs
```

With no argument it **starts** rather than restarts: anything already listening is left
alone, and it says so. After changing backend code, use `restart`.

Do not run `pnpm build` while the frontend is up. Both write `web/.next`, and Turbopack's
cache does not survive two writers — it stops emitting chunks mid-build, every route then
answers 500, and no ordinary restart clears it because the production marker it looks for
is already gone. Stop the servers first, or run `.\dev.cmd fresh` afterwards.

Run it from a terminal opened **in this folder**, and keep the leading `.\`. `dev.cmd` is a wrapper that works from both PowerShell and `cmd.exe` and finds the project regardless of the current directory; `dev.ps1` beside it holds the actual logic and can be called directly from PowerShell if preferred.

Both servers are detached and windowless, so closing the terminal that launched them leaves them running and `logs` is the only way to read their output — it is written to `backend/.dev-logs/` and `web/.dev-logs/`.

Every demo account uses the password printed by the seed. `admin@gradetracker.test` is the superadmin, `registrar@gradetracker.test` the admin, `t.weber@gradetracker.test` a teacher, and the seeded student login is printed too.

To run the two halves by hand instead, start the backend in the first PowerShell terminal:

```powershell
Set-Location backend
uv sync
uv run python -m api.migrate
uv run python -m api.seed
uv run uvicorn api.main:app --reload
```

Start the frontend in a second PowerShell terminal:

```powershell
Set-Location web
corepack pnpm install
corepack pnpm dev
```

Open:

- Application: <http://localhost:3000>
- API documentation: <http://localhost:8000/docs>

## Verification

Backend:

```powershell
Set-Location backend
uv run pytest --cov
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Frontend:

```powershell
Set-Location web
corepack pnpm test
corepack pnpm lint
corepack pnpm typecheck
corepack pnpm build     # not while the dev server is up — see above
```

