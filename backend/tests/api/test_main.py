"""Application startup behavior."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import main
from api.config import Settings


def test_startup_warns_when_ai_is_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A fresh installation names the page that makes AI usable."""
    settings = Settings(database_path=str(tmp_path / "startup.db"))
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    application = main.create_app()

    with caplog.at_level(logging.WARNING, logger="api.main"), TestClient(application):
        pass

    assert "configure a provider at /admin/ai" in caplog.text
