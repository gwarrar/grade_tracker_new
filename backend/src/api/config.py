"""Application settings, read from the environment.

Every declared knob lives here, so the full set is one file and one ``.env.example``
away from any reader.

Two modules read ``os.environ`` directly and cannot use this class:
:mod:`llm.registry` and :mod:`services.ai_admin` resolve provider API keys *by name*
(``ai_providers.api_key_env`` holds the name of a variable, never a key). Those names
are configured at runtime, so they cannot be declared fields here -- which is exactly
why :func:`load_dotenv` is called below.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]

# pydantic-settings parses `.env` into the Settings instance; it does not populate
# os.environ, and `extra="ignore"` then discards anything undeclared -- so a provider
# key written only to `.env` was invisible to the two modules above, and every
# provider reported AI_KEY_MISSING while the admin page showed a key-present badge
# that was a false negative.
#
# `load_dotenv` never overrides a variable that is already set, so a real exported
# shell variable still wins. Keys stay out of the database either way.
load_dotenv(_REPO_ROOT / ".env")


#: Hosts that mean "this machine", and the only ones an HTTP origin may use before
#: the session cookie is allowed to travel without ``Secure``.
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _is_loopback(origin: str) -> bool:
    """Whether an origin points at this machine.

    Args:
        origin: An origin such as ``http://localhost:3000``.

    Returns:
        True when its host is a loopback name. A malformed origin is not loopback —
        anything unparseable is treated as remote, so the doubt costs a ``Secure``
        flag rather than a session token.
    """
    host = urlparse(origin).hostname
    return host is not None and host.lower() in _LOOPBACK


class Settings(BaseSettings):
    """Runtime configuration.

    Attributes:
        database_path: SQLite file, relative to the repository root.
        secret_key: Used to sign anything that needs it. Generated per-process if
            unset, which is fine for a first run and wrong for anything persistent —
            a regenerated key on restart invalidates every signature.
        session_ttl_hours: How long a session stays valid.
        cors_origins: Origins permitted to call the API with credentials.
        cookie_secure: Whether the session cookie carries ``Secure``. Left unset it
            is inferred from ``cors_origins`` — see :attr:`session_cookie_secure`.
        trusted_proxies: Hosts whose ``X-Forwarded-For`` may be believed, comma
            separated, or ``*`` for any. **Empty by default, which trusts none.**
            There is no safe way to guess this: believe the header unconditionally
            and any caller can claim an address and walk around the sign-in
            lockout; ignore it behind a real proxy and every caller shares the
            proxy's address, which collapses that same lockout onto the email alone.
            Set it when deploying behind a reverse proxy, and only then.
        login_max_attempts: Failed sign-ins tolerated per email+IP before lockout.
        login_lockout_minutes: How long that lockout lasts.
        ai_max_calls_per_hour: Provider calls one account may make in an hour. Every
            AI request costs money, and until this existed any signed-in student
            could spend without limit.
        upload_dir: Where logos and avatars are written.
        max_upload_bytes: Ceiling on an uploaded file.
        max_import_rows: Hard cap on rows in one import. SQLite is a single writer;
            a bulk import that long would starve every other request. The path to
            lifting it is a background job with a staging table, not a bigger number.
    """

    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_path: str = "grades.db"
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    session_ttl_hours: int = 168  # one week
    cors_origins: str = "http://localhost:3000"
    cookie_secure: bool | None = None
    trusted_proxies: str = ""
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    ai_max_calls_per_hour: int = 60
    upload_dir: str = "uploads"
    max_upload_bytes: int = 2 * 1024 * 1024
    max_import_rows: int = 5000

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard(cls, value: str) -> str:
        """Reject ``*`` as an allowed origin.

        The API authenticates with a cookie, and a wildcard origin combined with
        credentialed requests is precisely the configuration that makes every
        authenticated endpoint reachable from any site the user happens to visit.
        Browsers refuse the combination anyway; failing here explains why.

        Args:
            value: The comma-separated origin list.

        Returns:
            The value unchanged.

        Raises:
            ValueError: If the list contains ``*``.
        """
        if "*" in value:
            raise ValueError(
                "CORS_ORIGINS cannot contain '*': this API authenticates with cookies, "
                "and credentialed requests require explicit origins."
            )
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        """The allowed origins, split and trimmed."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_proxy_list(self) -> list[str] | str:
        """Hosts whose forwarded-for header may be believed.

        Returns:
            ``"*"`` for any, otherwise the configured hosts. Empty when none are
            configured, which is the default and means the header is ignored.
        """
        value = self.trusted_proxies.strip()
        if value == "*":
            return "*"
        return [host.strip() for host in value.split(",") if host.strip()]

    @property
    def session_cookie_secure(self) -> bool:
        """Whether the session cookie should carry ``Secure``.

        Inferred rather than guessed. This used to ask whether *any* configured
        origin mentioned localhost, which failed in the two ways that matter and
        both times toward insecure:

        * ``any`` rather than ``all`` — a production deployment that left the dev
          entry in ``CORS_ORIGINS``, far and away the most common misconfiguration,
          shipped its real session cookie without ``Secure``, silently.
        * a substring test rather than a host parse — ``https://mylocalhost.io``
          matched ``"localhost" in origin`` and turned it off outright.

        Now every origin must be loopback for the cookie to go without ``Secure``,
        the host is parsed rather than searched, and ``COOKIE_SECURE`` overrides the
        inference for a deployment this cannot reason about.

        Returns:
            True unless every configured origin is loopback.
        """
        if self.cookie_secure is not None:
            return self.cookie_secure

        origins = self.cors_origin_list
        # No origins at all is not "local", it is unknown -- and unknown is Secure.
        return not origins or not all(_is_loopback(origin) for origin in origins)

    @property
    def database_file(self) -> Path:
        """Absolute path to the SQLite file."""
        path = Path(self.database_path)
        return path if path.is_absolute() else _REPO_ROOT / path

    @property
    def upload_path(self) -> Path:
        """Absolute path to the upload directory."""
        path = Path(self.upload_dir)
        return path if path.is_absolute() else _REPO_ROOT / "backend" / path


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings.

    Cached so the ``.env`` file is read once rather than per request, and so every
    caller observes the same generated ``secret_key``.

    Returns:
        The settings singleton.
    """
    return Settings()
