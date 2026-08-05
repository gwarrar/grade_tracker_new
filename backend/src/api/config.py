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


class Settings(BaseSettings):
    """Runtime configuration.

    Attributes:
        database_path: SQLite file, relative to the repository root.
        secret_key: Used to sign anything that needs it. Generated per-process if
            unset, which is fine for a first run and wrong for anything persistent —
            a regenerated key on restart invalidates every signature.
        session_ttl_hours: How long a session stays valid.
        cors_origins: Origins permitted to call the API with credentials.
        login_max_attempts: Failed sign-ins tolerated per email+IP before lockout.
        login_lockout_minutes: How long that lockout lasts.
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
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
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
