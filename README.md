# Grade Tracker

Grade Tracker is a FastAPI and Next.js application for academic records, reporting, AI-assisted workflows, and the planned multi-institution learning platform.

## Project documentation

- [Secure SaaS and LMS implementation plan](PROJECT_IMPLEMENTATION_PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Architecture decisions](docs/DECISIONS.md)
- [Backend guide](backend/README.md)
- [Frontend guide](web/README.md)
- [OpenAPI document](docs/openapi.json)

The implementation plan is the source of truth for roadmap order, security, backup and recovery, performance budgets, hybrid video storage, SaaS tenancy, billing, AI, and LMS scope.

## Local development

Prerequisites:

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 22
- pnpm 10

Create the root environment file once:

```powershell
Copy-Item .env.example .env
```

Edit `.env`, replace `SECRET_KEY`, and configure an AI provider key only if AI features are being tested. Never commit `.env`.

Install dependencies once (`uv sync` in `backend`, `pnpm install` in `web`), then run both servers with one command:

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
pnpm install
pnpm dev
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
pnpm test
pnpm lint
pnpm typecheck
pnpm build
```

