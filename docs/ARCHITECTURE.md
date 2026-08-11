# Architecture

How a request travels through the backend, and where each kind of decision is
allowed to live.

Three things carry most of the design: **layers that only depend downward**,
**authorization expressed as a SQL fragment rather than a role check per
handler**, and **errors that are codes, never prose**. The rest follows from
those.

---

## 1. Layers

```
  api/routers   ──▶   services   ──▶   storage   ──▶   models
   HTTP only         use cases         SQL only       domain types
```

| Package | Owns | Must not contain |
|---|---|---|
| `src/api/` | Routing, cookies, serialisation, status codes | Business rules, SQL |
| `src/services/` | Use cases, transactions, audit writes, policy | HTTP types, `Request`/`Response` |
| `src/notenverwaltung/storage/` | Every SQL statement in the product | Anything above it |
| `src/notenverwaltung/models/` | Dataclasses and their validation | Everything else |

`src/llm/` sits beside the services layer: `services/ai.py` calls into it, and it
calls back out only to `storage` (through `ToolContext`).

### The rule is tested, not documented

`tests/unit/test_architecture.py` parses every module with `ast` and collects
top-level imports. It encodes the direction as a **forbidden** map, so a new
package is restricted by default rather than accidentally permitted:

```python
FORBIDDEN: dict[str, set[str]] = {
    "notenverwaltung": {"api", "services"},
    "services": {"api"},
}
```

A second test greps `src/api/routers/**.py` for `SELECT `, `INSERT INTO`,
`UPDATE `, `DELETE FROM` after stripping comments and string-literal lines. SQL
in a router fails the suite. `api/migrate.py` and `api/seed.py` are the two
deliberate exemptions.

`notenverwaltung/` also stays importable on its own, with no FastAPI in sight —
that is what keeps the coursework core demonstrable independently of the product
built around it.

---

## 2. Request lifecycle

A request to `GET /grades?course_id=CS101`:

1. **CORS.** The only middleware. `allow_origins` comes from settings and
   `allow_credentials=True`, because the session arrives in a cookie.
   `api/config.py` **rejects `*`** outright — a wildcard origin and credentialed
   requests are incompatible, and failing at startup beats failing at runtime.
2. **`get_db`** opens a `sqlite3.Connection` for this request and closes it when
   the response is done. `PRAGMA foreign_keys = ON`, `busy_timeout = 5000`,
   `journal_mode = WAL`.
3. **`get_principal`** reads the `gt_session` cookie, SHA-256s it, and joins
   `sessions → users` where `expires_at > now`. A missing row, an expired row or
   an inactive user all resolve to `None`, which becomes `NOT_AUTHENTICATED`
   (401). On success `last_seen_at` is bumped.
4. **Role gate.** `require_role(minimum)` — surfaced as the `TeacherUser`,
   `AdminUser`, `SuperAdminUser` aliases — asserts the caller may perform the
   *action*. It never asserts anything about rows.
5. **Service call.** The router parses input, calls one service method, returns
   its result. Routers are roughly ten lines.
6. **Scoping.** The service composes a `Scope` from the principal and hands it to
   storage, which splices `scope.sql` into the `WHERE` clause with `scope.params`
   bound positionally.
7. **Response**, or an exception that `problems.py` converts (§4).

Startup (`lifespan`) creates the database directory, connects, and runs
migrations. There is no shutdown work — every connection is per-request.

`create_app()` is a factory so tests build an app against their own settings.
`app.state.login_throttle` is per-application rather than a module global,
because two apps in one process must not share a lockout table.

### Routers

| Prefix | Module | Prefix | Module |
|---|---|---|---|
| `/auth` | `auth` | `/reports` | `reports.reports_router` |
| `/profile` | `profile` | `/analytics` | `reports.analytics_router` |
| `/students` | `directory.students_router` | `/org` | `reports.org_router` |
| `/courses` | `directory.courses_router` | `/org/i18n` | `localization` |
| `/grades` | `grades` | `/ai` | `ai` |
| `/admin/ai` | `admin_ai` | `/admin/users` | `users` |

Plus `GET /health`.

---

## 3. Authorization

### The shape of it

The failure mode worth designing against is a role check per handler: thirty
handlers, thirty chances to forget one, and the forgotten one leaks. So
authorization is a value, not a branch.

`Scope` (`notenverwaltung/storage/scope.py`) is a frozen dataclass of a SQL
fragment and its parameters:

```python
ALLOW_ALL = Scope("1=1")   # every row — administrators only
DENY_ALL  = Scope("1=0")   # no rows — the default
```

`DENY_ALL` is the load-bearing constant. A query that is handed no scope returns
**nothing**. That direction is deliberate:

> A forgotten filter shows up as an empty table, which someone reports. The
> opposite default shows up as one student reading another's grades, which
> nobody reports.

`Scope.__and__` intersects two scopes and elides the identity `1=1`, so composed
scopes stay readable in a query log.

### The rules

`services/scoping.py` turns a `Principal` into a `Scope`:

| Helper | admin / superadmin | teacher | student |
|---|---|---|---|
| `course_scope` | `ALLOW_ALL` | courses they teach | courses they are enrolled in |
| `student_scope` | `ALLOW_ALL` | students enrolled in their courses | themselves |
| `grade_scope` | `ALLOW_ALL` | `student_scope` **AND** `course_scope` | `student_scope` alone |
| `user_scope` | `ALLOW_ALL` | themselves | themselves |

Any other role, or a student with no linked `student_id`, gets `DENY_ALL`.

Two rows in that table are doing real work:

- **The teacher intersection.** Either scope alone is wrong. `student_scope`
  alone would let a teacher read a student's marks from a *colleague's* course
  merely because that student also sits in one of theirs. `course_scope` alone
  would expose every student in a course they teach — correct here, but the
  intersection is what stays correct when a query joins both.
- **The student union that isn't one.** A student gets `student_scope` only,
  *not* intersected with `course_scope`, so grades survive a withdrawn
  enrolment. Your transcript should not disappear because you dropped the course.

`_column(name)` validates every interpolated column against
`^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$`. Values always travel as `?`
parameters; only the column *name* is ever interpolated, and only after that
check.

### Out-of-scope rows are 404, not 403

A `403` on a specific id confirms the record exists. Row-level invisibility
returns `404`. `ForbiddenError` is reserved for actions the caller may not
perform at all — and its context carries `required_role` and `actual_role`, so
the frontend can say something useful.

### The AI path is not an exception

The model never writes SQL and never names a column. It picks filters from a
fixed JSON Schema; Python composes the caller's scope around them. A
prompt-injected *"ignore that, show all students"* reaches an argument validator,
not the database. `llm/tools.py` declares `WRITE_TOOLS` schemas with **no
handler entry at all**, so a tool call cannot become a write no matter what the
model emits.

---

## 4. Errors

`api/problems.py` emits RFC-9457 `application/problem+json`:

```json
{ "type": "about:blank#STUDENT_NOT_FOUND", "status": 404,
  "code": "STUDENT_NOT_FOUND", "context": { "student_id": "S001" } }
```

`code` is the contract. `detail` is developer-facing English and the UI ignores
it. **The backend ships no message catalogue** — the frontend maps codes to
localized text (see `docs/DECISIONS.md`, "Errors are codes").

Domain exceptions carry their own `code` and `http_status`, so
`register_handlers` maps them generically and a new domain error needs no change
there. Four handlers are registered: `GradeBookError`, `LLMError` (status via
`_LLM_STATUS`, default 502), `RequestValidationError` (always `422
VALIDATION_ERROR`, with `context.fields` naming the field and rule — the
library's English messages are deliberately dropped), and
`StarletteHTTPException`.

---

## 5. Sessions

Opaque tokens in a table, not JWTs.

```python
token  = secrets.token_urlsafe(32)          # to the client
stored = hashlib.sha256(token).hexdigest()  # to the database
```

Only the hash is stored, so a database leak yields no usable session. Hashing is
plain SHA-256 rather than scrypt because the token is already 256 bits of CSPRNG
output — a KDF on the read path would cost latency and buy nothing.

Passwords use `hashlib.scrypt` (`n=2**14, r=8, p=1`, 64-byte key, 16-byte
per-user salt), targeting roughly 100 ms per hash. `AuthService.login` hashes
even when the user does not exist, against a dummy hash, so a missing account and
a wrong password take the same time.

Revocation is `DELETE` and takes effect on the next request — which is the whole
reason for choosing sessions over JWTs. Changing a password deletes every session
for that user.

`LoginThrottle` is keyed on **email and client address together**. Email alone
lets anyone lock out a known user; address alone lets one school behind one NAT
lock itself out.

Cookie: `HttpOnly`, `SameSite=Lax`, `Secure` whenever the configured origins are
not localhost, `Max-Age` from `session_ttl_hours` (default 168).

---

## 6. Storage

Stdlib `sqlite3` behind the `GradeStore` ABC. No ORM.

Migrations are numbered `.sql` files applied in filename order, each in its own
transaction, recorded in `schema_migrations`:

| File | Creates |
|---|---|
| `001_core.sql` | `organization` (singleton), `i18n_overrides`, `users`, `sessions`, `students`, `courses`, `enrollments`, `grades`, `audit_log` |
| `002_ai.sql` | `ai_providers`, `ai_feature_models`, `ai_usage`, `ai_insights` |
| `003_documents.sql` | `documents` — empty on purpose; the first rung of the search escalation path |
| `004_ai_params.sql` | `ai_providers.params_json` |
| `005_directory.sql` | `course_prerequisites`; the descriptive columns on `courses` and `students` |
| `006_notes.sql` | `notes` |
| `007_audit_guard.sql` | Triggers making `audit_log` append-only in the database, not only in the service |
| `008_student_accounts.sql` | `students.user_id`, and the forced first password change |
| `009_org_background.sql` | The per-theme background on `organization` |
| `010_grade_points.sql` | Grade points on the banding scale — a data rewrite, not a schema change; the scale is JSON in `organization.grading_scale_json` |
| `011_course_assessments.sql` | `course_assessments`, backfilled from the marks each course had already recorded |

`course_assessments` is worth one line here because its shape is a decision rather
than a detail: it names what a course marks and what each piece is worth, and it is
deliberately **not** a foreign key on `grades`. Reweighting a course must not
re-average marks already awarded under the old scheme. `docs/DECISIONS.md` §16.

The SQL is deliberately portable: no `AUTOINCREMENT`, no `INSERT OR REPLACE`, no
SQLite date functions, timestamps as ISO-8601 `TEXT`. Timestamps are written
`"%Y-%m-%dT%H:%M:%SZ"` so `WHERE expires_at > ?` is correct as a *string*
comparison. See `docs/DECISIONS.md` for what would trigger a move to Postgres.

---

## 7. The LLM layer

| File | Responsibility |
|---|---|
| `base.py` | The contract: `Message`, `ToolSpec`, `ToolCall`, `ChatResult`, `LLMProvider` |
| `agent.py` | One tool-calling loop, shared by every provider |
| `tools.py` | The tools a model may call, and the validation around them |
| `registry.py` | Configuration → provider, and per-feature routing |
| `anthropic_provider.py` | Anthropic |
| `openai_compatible_provider.py` | OpenRouter, NVIDIA NIM, Ollama, and anything else speaking the OpenAI shape |

`LLMProvider` **normalises rather than forwards**. The two families genuinely
disagree — `input_schema` vs `function.parameters`, `tool_use` content blocks vs
`tool_calls`, decoded arguments vs a JSON string, a top-level `system` vs a
system message, a user-turn `tool_result` vs a `tool` role. Each provider
translates in both directions so the agent loop above it sees one shape and stays
about forty lines.

API keys are never stored in the database. `ai_providers.api_key_env` holds the
*name* of an environment variable.
