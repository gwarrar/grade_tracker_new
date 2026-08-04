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

Start the backend in the first PowerShell terminal:

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

