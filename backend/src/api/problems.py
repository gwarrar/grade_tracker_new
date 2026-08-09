"""RFC-9457 ``application/problem+json`` error responses.

Every error body carries a machine-readable ``code`` and structured ``context``.
**No user-facing prose is produced here** — the frontend maps the code to a message
in the reader's language. That is what keeps the backend free of a message catalogue
and makes adding a fourth language a frontend-only change.

The ``detail`` field carries the developer-facing message. It is useful in logs and
in the API docs; the UI is expected to ignore it.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from llm.base import LLMError
from notenverwaltung.exceptions import GradeBookError

logger = logging.getLogger(__name__)

CONTENT_TYPE = "application/problem+json"


def problem(
    status: int, code: str, detail: str, context: dict[str, Any] | None = None
) -> JSONResponse:
    """Build a problem response.

    Args:
        status: HTTP status code.
        code: Stable machine-readable identifier, e.g. ``STUDENT_NOT_FOUND``.
        detail: Developer-facing description. Never shown to end users.
        context: Structured values the frontend interpolates into its translation.

    Returns:
        The JSON response.
    """
    body: dict[str, Any] = {"type": f"about:blank#{code}", "status": status, "code": code}
    if detail:
        body["detail"] = detail
    if context:
        body["context"] = context
    return JSONResponse(status_code=status, content=body, media_type=CONTENT_TYPE)


# Provider failures, mapped to the status that describes *this* application's part
# in them. A misconfiguration is a 4xx here; a provider that is reachable but
# unhappy is a 502, because the fault is upstream and the caller cannot fix it.
_LLM_STATUS: dict[str, int] = {
    "AI_PROVIDER_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "AI_NOT_CONFIGURED": status.HTTP_404_NOT_FOUND,
    "AI_UNKNOWN_KIND": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "AI_KEY_MISSING": status.HTTP_409_CONFLICT,
    "AI_PROVIDER_DISABLED": status.HTTP_409_CONFLICT,
    "AI_RATE_LIMITED": status.HTTP_429_TOO_MANY_REQUESTS,
}


def register_handlers(app: FastAPI) -> None:
    """Attach the exception handlers to an application.

    Args:
        app: The FastAPI application.
    """

    @app.exception_handler(GradeBookError)
    async def _domain_error(  # pyright: ignore[reportUnusedFunction] - registered by the decorator
        _: Request, exc: GradeBookError
    ) -> JSONResponse:
        """Translate a domain exception into its problem response.

        Each exception class carries its own ``code`` and ``http_status``, so adding
        a new one needs no change here.
        """
        return problem(exc.http_status, exc.code, exc.message, exc.context)

    @app.exception_handler(LLMError)
    async def _llm_error(  # pyright: ignore[reportUnusedFunction] - registered by the decorator
        _: Request, exc: LLMError
    ) -> JSONResponse:
        """Translate a provider failure into a problem response.

        The status is derived from the code rather than carried on the exception,
        because the same code means different things at different layers: an
        unknown provider id is a 404 when an administrator asks for it, and the
        provider's *own* 404 (no such model) is a 502 — this application reached
        it, and it answered.
        """
        return problem(
            _LLM_STATUS.get(exc.code, status.HTTP_502_BAD_GATEWAY),
            exc.code,
            str(exc),
            {"provider": exc.provider} if exc.provider else {},
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(  # pyright: ignore[reportUnusedFunction] - registered by the decorator
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Translate a schema validation failure.

        Field locations are passed through so the frontend can attach messages to the
        right inputs; the library's English messages are not, since they would be the
        one untranslatable string in an otherwise localised form.
        """
        fields = [
            {"field": ".".join(str(p) for p in err["loc"][1:]), "rule": err["type"]}
            for err in exc.errors()
        ]
        return problem(
            422, "VALIDATION_ERROR", "Request body failed validation.", {"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(  # pyright: ignore[reportUnusedFunction] - registered by the decorator
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Translate the framework's own errors into the same envelope.

        Without this, a 404 from routing would return ``{"detail": "Not Found"}``
        while a 404 from the domain returned a problem document — and the client would
        need two error parsers.
        """
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        return problem(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(  # pyright: ignore[reportUnusedFunction] - registered by the decorator
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Return the same envelope for a crash as for everything else.

        Without this the framework answers `text/plain "Internal Server Error"`, and
        that is the one response shape the client cannot read: every error path in the
        frontend parses `application/problem+json`, so a real backend fault surfaced
        as a *parse* error and told nobody anything. ``INTERNAL_ERROR`` was already
        declared below and was unreachable.

        The detail is deliberately fixed prose. An exception's message is the one
        string in this file not written for a reader — it carries file paths, SQL
        fragments and occasionally the value that broke — and this envelope is
        rendered to whoever made the request. The traceback goes to the log, where
        the person who can act on it is looking.

        `raise_server_exceptions=False` is needed to see this from a TestClient;
        with the default the test client re-raises instead of returning a response.
        """
        logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return problem(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "The server failed to handle this request.",
        )


_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_ATTEMPTS",
    500: "INTERNAL_ERROR",
}
"""Framework status codes mapped to the same vocabulary the domain uses."""
