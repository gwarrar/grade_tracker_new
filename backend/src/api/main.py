"""The FastAPI application.

Assembly only: settings, middleware, exception handlers, routers. No business logic
lives here.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.config import get_settings
from api.problems import register_handlers
from api.routers import (
    admin_ai,
    ai,
    auth,
    directory,
    grades,
    localization,
    organization,
    profile,
    reports,
    users,
)
from notenverwaltung import __version__
from notenverwaltung.storage import apply_migrations, connect
from services.ai_admin import AiAdminService
from services.auth import LoginThrottle

logger = logging.getLogger(__name__)

DESCRIPTION = """
Student grade management: students, courses, enrolments, grades, reports and an
AI assistant.

### Errors

Every failure returns `application/problem+json` (RFC 9457) carrying a stable
machine-readable `code` and a structured `context`:

```json
{ "type": "about:blank#STUDENT_NOT_FOUND", "status": 404,
  "code": "STUDENT_NOT_FOUND", "detail": "No student with id 'S999'.",
  "context": { "student_id": "S999" } }
```

**Clients should render the `code`, not the `detail`.** `detail` is a
developer-facing string and is only ever English; the interface translates the code
into the reader's language. This is why the API ships no message catalogue.

### Authorization

Authentication is a session cookie (`HttpOnly`, `SameSite=Lax`). Access is filtered
in the query rather than checked in the handler, so what you can see depends on your
role:

| Role | Students | Courses | Grades |
|---|---|---|---|
| `student` | only themselves | those they are enrolled on | only their own |
| `teacher` | those enrolled on a course they own | those they own | within their own courses |
| `admin` | all | all | all |
| `superadmin` | all, plus AI provider configuration | all | all |

A list endpoint returns what you may see, never a `403`. Only *actions* beyond your
role return `403`.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Run pending migrations at start-up.

    Applying them here means a fresh checkout works after one command rather than
    two, and a forgotten migration cannot present as a confusing runtime error.
    """
    settings = get_settings()
    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.database_file)
    try:
        apply_migrations(conn)
        if not AiAdminService(conn).is_configured():
            logger.warning("AI is unconfigured; configure a provider at /admin/ai")
    finally:
        conn.close()
    yield


def create_app() -> FastAPI:
    """Build the application.

    A factory rather than a module-level singleton, so tests can construct an
    instance against their own settings without the import order mattering.

    Returns:
        The configured application.
    """
    settings = get_settings()

    app = FastAPI(
        title="Grade Tracker API",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "Authentication", "description": "Sign in, sign out, identify the caller."},
            {"name": "Profile", "description": "The signed-in user's own account and devices."},
            {"name": "Students", "description": "Student records and their enrolments."},
            {
                "name": "Courses",
                "description": (
                    "Courses and their registers. Enrolment is separate from grading: "
                    "a student can be enrolled without having been assessed yet."
                ),
            },
            {"name": "Grades", "description": "Recording, amending and retiring marks."},
            {
                "name": "Reports",
                "description": (
                    "Structured report payloads. The client renders the wording, which "
                    "is why the API ships no message catalogue."
                ),
            },
            {
                "name": "Analytics",
                "description": "Dashboard figures and rankings, scoped to the caller.",
            },
            {"name": "Organisation", "description": "Branding, locales, theme and grading scale."},
            {
                "name": "Localization",
                "description": (
                    "Per-organisation string overrides. The frontend owns every "
                    "translation; this covers only the renames it cannot know at build time."
                ),
            },
        ],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,  # the session cookie must be sent cross-origin in dev
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount(
        "/uploads",
        StaticFiles(directory=settings.upload_path, check_dir=False),
        name="uploads",
    )

    # Scoped to this application, not the process -- see api.deps.get_throttle.
    app.state.login_throttle = LoginThrottle(
        settings.login_max_attempts, settings.login_lockout_minutes
    )

    register_handlers(app)
    app.include_router(auth.router)
    app.include_router(profile.router)
    app.include_router(directory.students_router)
    app.include_router(directory.courses_router)
    app.include_router(grades.router)
    app.include_router(reports.reports_router)
    app.include_router(reports.analytics_router)
    app.include_router(reports.org_router)
    app.include_router(organization.router)
    app.include_router(localization.router)
    app.include_router(ai.router)
    app.include_router(admin_ai.router)
    app.include_router(users.router)

    @app.get("/health", tags=["System"], summary="Liveness check")
    def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction] - route-registered
        """Report that the process is up.

        Returns:
            The service version.
        """
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
