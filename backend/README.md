# Grade Tracker — Backend

A domain core, a REST API over it, and a provider-agnostic AI agent beside it.
FastAPI, stdlib `sqlite3`, no ORM.

## Layers

Dependencies flow one way only. Nothing on the left ever imports something on its right.

```
api/routers  →  services  →  storage  →  models
   (HTTP)      (use cases)     (SQL)     (domain)
```

| Package | Owns | Must not contain |
|---|---|---|
| `api/` | Routing, cookies, serialisation, status codes | Business rules, SQL, transactions |
| `services/` | Use cases, transactions, audit writes, policy | HTTP types, `Request`/`Response` |
| `notenverwaltung/storage/` | Entity CRUD, scoped pagination, the connection | Anything above it |
| `notenverwaltung/models/` | Dataclasses and their validation | Everything else |

`llm/` sits beside `services/`: `services/ai.py` calls into it, and it reaches back
out only to storage, through a `ToolContext`.

**Where SQL is allowed:** in `storage/`, and in the service that owns a use case.
Not in a router — that half is enforced. `tests/unit/test_architecture.py` parses
every module with `ast` and fails the build on an upward import, on SQL in a router,
or on a router importing `sqlite3` or the storage package at all. A router holding a
connection has taken on the transaction boundary, and the audit row that must commit
with the change it describes.

### `notenverwaltung/` stands alone on purpose

It imports no FastAPI and knows nothing about HTTP, so it can be exercised from a
REPL or a test with no application around it. That is not incidental tidiness: it is
what keeps the coursework core demonstrable independently of the product built on it,
and it is why `GradeBook` carries averages, search and JSON/CSV interchange that the
API never calls — `services/` computes the same quantities in SQL against a scope,
which is the right answer for a web request and the wrong one for the core.

## Quick start

```powershell
uv sync
Copy-Item ..\.env.example ..\.env      # then edit
uv run python -m api.migrate
uv run python -m api.seed
uv run uvicorn api.main:app --reload
```

API documentation at <http://localhost:8000/docs>.

## A request, end to end

`GET /grades?course_id=CS101`:

1. **CORS** — the only middleware. `api/config.py` rejects a wildcard origin at
   startup, because a wildcard and credentialed requests are incompatible.
2. **`get_db`** opens a connection for this request and closes it with the response.
   `foreign_keys = ON`, `busy_timeout = 5000`, `journal_mode = WAL`.
3. **`get_principal`** reads the `gt_session` cookie, SHA-256s it, and joins
   `sessions → users`. A missing, expired or deactivated row becomes `401`. A
   principal still owing a first password change is refused everything except
   `/auth/me`, `/auth/logout` and the password-change endpoint.
4. **Role gate** — `require_role(minimum)`, surfaced as the `TeacherUser`,
   `AdminUser` and `SuperAdminUser` aliases. It asserts the caller may perform the
   *action*; it never asserts anything about rows.
5. **Service call.** The router parses input, calls one service method, returns its
   result. Routers are roughly ten lines.
6. **Scoping.** The service composes a `Scope` from the principal and hands it to
   storage, which splices `scope.sql` into `WHERE` with `scope.params` bound.
7. **Response**, or a domain exception that `api/problems.py` converts to RFC-9457
   `application/problem+json`.

## Adding an endpoint

1. **Model or migration**, if the shape is new. Numbered `.sql`, portable, additive.
2. **Storage**, if it needs SQL the store or `queries.py` does not already have.
3. **Service method.** Own the transaction here — `with transaction(self._conn):`
   around the write *and* its `audit.record(...)`, so neither can land without the
   other. Raise a domain exception carrying its own `code`; `problems.py` maps it
   generically, so a new error needs no handler change.
4. **Response model** in `api/schemas/`. Not inline in the router: every field
   carries a description and an example, and those become the OpenAPI document and
   from there the frontend's TypeScript types.
5. **Router.** Parse, delegate, return. No SQL, no transaction, no `conn`.
6. **Tests.** One for the use case, one for the role gate, and one in
   `tests/api/test_leaks.py` if the endpoint exposes anything scoped.
7. **Regenerate the spec** — `uv run python scripts/export_openapi.py`, then
   `corepack pnpm gen:api` in `web/`. CI diffs both and fails on drift.

## Checks

```powershell
uv run pytest --cov      # 865 tests; ≥85% over notenverwaltung/, services/, llm/ and api/
uv run ruff check .      # pycodestyle, pyflakes, isort, pep8-naming, pydocstyle,
                         # pyupgrade, annotations, bugbear, bandit, comprehensions, simplify
uv run ruff format --check .
uv run pyright           # strict, over src/ tests/ and scripts/
```

Docstrings and type annotations are mandatory, not encouraged — `D` and `ANN` are in
the ruff selection. Tests are exempt from both.

## Migrations

Numbered `.sql` files in `migrations/`, applied in filename order, each in its own
transaction, recorded in `schema_migrations`. Additive only, and portable SQL: no
`AUTOINCREMENT`, no `INSERT OR REPLACE`, no SQLite date functions, timestamps as
ISO-8601 `TEXT`. `../docs/ARCHITECTURE.md` §6 lists them; `../docs/DECISIONS.md` §1
says why the portability rules exist.

`003` is absent by design — it created a table for a search feature that was never
built and was deleted. The numbering was left alone so recorded versions keep
matching filenames.

**Testing one has a trap.** The `sqlite_conn` fixture already applies every migration
when it builds the connection, so a test that inserts rows and then calls
`apply_migrations` is testing a no-op — and a backfill assertion against it passes
for the wrong reason. Two tests did exactly that before it was noticed. To exercise a
migration for real, undo it first:

```python
conn.execute("DROP TABLE course_assessments")
conn.execute("DELETE FROM schema_migrations WHERE version = '011_course_assessments'")
apply_migrations(conn)
```

A second trap, for data migrations: a `WHERE` clause matching a JSON string will miss
rows the application has already rewritten, because `json.dumps` uses different
separators from the seed literal. Match both spellings, or match on something that is
not a serialized document. Migration 010 shipped broken for this reason and had to be
widened.

## Further reading

- `../docs/ARCHITECTURE.md` — the request lifecycle, authorization and the LLM layer
  in full
- `../docs/DECISIONS.md` — why each choice was made, and what would reverse it
- `../SECURITY.md` — the threat model and the limits that are known and accepted
