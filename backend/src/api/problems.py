"""RFC-9457 ``application/problem+json`` error responses.

Every error body carries a machine-readable ``code`` and structured ``context``.
**No user-facing prose is produced here** — the frontend maps the code to a message
in the reader's language. That is what keeps the backend free of a message catalogue
and makes adding a fourth language a frontend-only change.

The ``detail`` field carries the developer-facing message. It is useful in logs and
in the API docs; the UI is expected to ignore it.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from notenverwaltung.exceptions import GradeBookError

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
