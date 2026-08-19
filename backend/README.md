# Grade Tracker — Backend

Student grade management: a domain core, a REST API, and a provider-agnostic AI agent.

## Layers

Dependencies flow one way only. Nothing on the right ever imports something on its left.

```
api/routers  →  services  →  storage  →  models
   (HTTP)       (use cases)   (SQL)     (domain)
```

- **`notenverwaltung/models`** — dataclasses with validation. No I/O.
- **`notenverwaltung/storage`** — `GradeStore` (entity SQL) and `queries.py` (listing, pagination, scope composition). The only place SQL exists.
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

## Migrations

Numbered `.sql` files in `migrations/`, applied in filename order, each in its own
transaction, recorded in `schema_migrations`. Additive only, and portable SQL —
`../docs/ARCHITECTURE.md` §6 lists them and `../docs/DECISIONS.md` §1 says why.

**Testing one has a trap.** The `sqlite_conn` fixture already applies every
migration when it builds the connection, so a test that inserts rows and then
calls `apply_migrations` is testing a no-op — and a backfill assertion against it
passes for the wrong reason. Two tests did exactly that before it was noticed. To
exercise a migration for real, undo it first:

```python
conn.execute("DROP TABLE course_assessments")
conn.execute("DELETE FROM schema_migrations WHERE version = '011_course_assessments'")
apply_migrations(conn)
```

A second trap, for data migrations: a `WHERE` clause matching a JSON string will
miss rows the application has already rewritten, because `json.dumps` uses
different separators from the seed literal. Match both spellings, or match on
something that is not a serialized document. Migration 010 shipped broken for this
reason and had to be widened.

See `../docs/ARCHITECTURE.md` for the request lifecycle and authorization model, and
`../docs/DECISIONS.md` for why each choice was made and what would reverse it.
