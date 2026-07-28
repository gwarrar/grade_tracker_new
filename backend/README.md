# Grade Tracker — Backend

Student grade management: a domain core, a REST API, and a provider-agnostic AI agent.

## Layers

Dependencies flow one way only. Nothing on the right ever imports something on its left.

```
api/routers  →  services  →  storage  →  models
   (HTTP)       (use cases)   (SQL)     (domain)
```

- **`notenverwaltung/models`** — dataclasses with validation. No I/O.
- **`notenverwaltung/storage`** — the `GradeStore` ABC and its SQLite / in-memory implementations. The only place SQL exists.
- **`services`** — use cases. Owns transactions and audit-log writes.
- **`api`** — HTTP. Parses, delegates, serializes. No business logic, no SQL.
- **`llm`** — the `LLMProvider` ABC and a provider-agnostic agent loop.

## Quick start

```powershell
uv sync
copy ..\.env.example ..\.env      # then edit
uv run python -m api.migrate
uv run python -m api.seed
uv run uvicorn api.main:app --reload
```

API docs at <http://localhost:8000/docs>.

## Checks

```powershell
uv run pytest --cov      # ≥85% on notenverwaltung/ and services/
uv run ruff check
uv run ruff format --check
uv run pyright
```

See `../docs/ARCHITECTURE.md` for the request lifecycle and authorization model, and
`../docs/DECISIONS.md` for why each choice was made and what would reverse it.
