"""The AI administration surface.

Two properties matter more than the CRUD and are asserted directly:

- **Only a superadmin may configure this.** These endpoints decide where student
  names, emails and grades are sent; that is a different class of decision from
  managing a course register, and an admin must not be able to make it.
- **No response ever carries an API key.** The design stores only the variable's
  name, and this is where that promise is checked rather than assumed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _create(client: TestClient, **overrides: object) -> dict[str, object]:
    """Create a provider and return the response body."""
    body: dict[str, object] = {
        "name": "openrouter",
        "kind": "openai_compatible",
        "default_model": "claude-opus-5",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    }
    body.update(overrides)
    response = client.post("/admin/ai/providers", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ── Authorization ────────────────────────────────────────────────────────────


def test_an_admin_cannot_configure_ai(as_admin: TestClient) -> None:
    """Configuring providers is superadmin-only, not admin.

    An administrator manages people and courses. Choosing which third party
    receives student records is a different decision.
    """
    assert as_admin.get("/admin/ai/providers").status_code == 403
    assert as_admin.post("/admin/ai/providers", json={}).status_code == 403
    assert as_admin.get("/admin/ai/usage").status_code == 403


def test_a_teacher_cannot_configure_ai(as_teacher: TestClient) -> None:
    """Nor can a teacher."""
    assert as_teacher.get("/admin/ai/providers").status_code == 403


def test_a_student_cannot_configure_ai(as_student: TestClient) -> None:
    """Nor a student."""
    assert as_student.get("/admin/ai/providers").status_code == 403


def test_anonymous_is_not_authenticated(client: TestClient) -> None:
    """No session is a 401, distinct from a session that lacks the role."""
    assert client.get("/admin/ai/providers").status_code == 401


# ── Providers ────────────────────────────────────────────────────────────────


def test_creating_and_listing_a_provider(as_superadmin: TestClient) -> None:
    """A created provider appears in the list with its configuration intact."""
    created = _create(as_superadmin)

    assert created["name"] == "openrouter"
    assert created["kind"] == "openai_compatible"
    assert created["api_key_env"] == "OPENROUTER_API_KEY"

    listed = as_superadmin.get("/admin/ai/providers").json()
    assert [item["name"] for item in listed] == ["openrouter"]


def test_no_response_ever_contains_an_api_key(
    as_superadmin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of storing a variable *name* is checked here, not assumed."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-super-secret-value")

    created = _create(as_superadmin)
    listed = as_superadmin.get("/admin/ai/providers")

    assert "sk-super-secret-value" not in listed.text
    assert "sk-super-secret-value" not in str(created)

    # It reports that a key exists without being able to show it.
    assert listed.json()[0]["key_present"] is True


def test_key_present_is_false_when_the_variable_is_unset(
    as_superadmin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider configured but unusable is visibly unusable."""
    monkeypatch.delenv("MISSING_KEY_VAR", raising=False)
    _create(as_superadmin, api_key_env="MISSING_KEY_VAR")

    assert as_superadmin.get("/admin/ai/providers").json()[0]["key_present"] is False


def test_a_duplicate_name_is_rejected(as_superadmin: TestClient) -> None:
    """Names identify providers in the routing table, so they must stay unique."""
    _create(as_superadmin)
    response = as_superadmin.post(
        "/admin/ai/providers",
        json={"name": "openrouter", "kind": "anthropic", "default_model": "claude-opus-5"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_ENTRY"


def test_an_unimplemented_kind_is_rejected(as_superadmin: TestClient) -> None:
    """A kind with no implementation fails at configuration time, not at first use."""
    response = as_superadmin.post(
        "/admin/ai/providers",
        json={"name": "telepathy", "kind": "telepathy", "default_model": "m"},
    )

    assert response.status_code == 422


def test_updating_a_provider(as_superadmin: TestClient) -> None:
    """Omitted fields are left alone; supplied ones are applied."""
    created = _create(as_superadmin)

    response = as_superadmin.patch(
        f"/admin/ai/providers/{created['id']}",
        json={"is_enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["is_enabled"] is False
    # Untouched.
    assert response.json()["default_model"] == "claude-opus-5"


def test_deleting_a_provider_removes_its_routing(as_superadmin: TestClient) -> None:
    """The cascade is the honest outcome.

    A route pointing at a deleted provider would fail at request time instead of
    at configuration time.
    """
    created = _create(as_superadmin)
    as_superadmin.put(
        "/admin/ai/routing/ask", json={"provider_id": created["id"], "model": "claude-opus-5"}
    )
    assert len(as_superadmin.get("/admin/ai/routing").json()) == 1

    assert as_superadmin.delete(f"/admin/ai/providers/{created['id']}").status_code == 204
    assert as_superadmin.get("/admin/ai/routing").json() == []


def test_deleting_an_unknown_provider_is_a_404(as_superadmin: TestClient) -> None:
    """A dangling id reports rather than silently succeeding."""
    assert as_superadmin.delete("/admin/ai/providers/999").status_code == 404


# ── Routing ──────────────────────────────────────────────────────────────────


def test_each_feature_routes_independently(as_superadmin: TestClient) -> None:
    """The reason routing is a separate table.

    The palette is latency-critical and the insight narrative is quality-critical;
    one default cannot be right for both.
    """
    provider = _create(as_superadmin)

    as_superadmin.put(
        "/admin/ai/routing/command",
        json={"provider_id": provider["id"], "model": "claude-haiku-4-5", "effort": "low"},
    )
    as_superadmin.put(
        "/admin/ai/routing/insight",
        json={"provider_id": provider["id"], "model": "claude-opus-5", "effort": "high"},
    )

    routing = {row["feature"]: row for row in as_superadmin.get("/admin/ai/routing").json()}

    assert routing["command"]["model"] == "claude-haiku-4-5"
    assert routing["command"]["effort"] == "low"
    assert routing["insight"]["model"] == "claude-opus-5"
    assert routing["insight"]["effort"] == "high"


def test_routing_a_feature_twice_replaces_rather_than_duplicates(
    as_superadmin: TestClient,
) -> None:
    """A feature has exactly one route; setting it again is an update."""
    first = _create(as_superadmin)
    second = _create(as_superadmin, name="ollama", api_key_env="")

    as_superadmin.put("/admin/ai/routing/ask", json={"provider_id": first["id"]})
    as_superadmin.put("/admin/ai/routing/ask", json={"provider_id": second["id"]})

    routing = as_superadmin.get("/admin/ai/routing").json()
    assert len(routing) == 1
    assert routing[0]["provider_name"] == "ollama"


def test_routing_to_an_unknown_provider_is_a_404(as_superadmin: TestClient) -> None:
    """Checked explicitly, so the failure names the provider.

    Left to the foreign key it would surface as an opaque integrity error.
    """
    response = as_superadmin.put("/admin/ai/routing/ask", json={"provider_id": 999})
    assert response.status_code == 404


def test_an_unknown_feature_is_rejected(as_superadmin: TestClient) -> None:
    """Features are an enum; an unrecognised one is not silently created."""
    provider = _create(as_superadmin)
    response = as_superadmin.put(
        "/admin/ai/routing/telepathy", json={"provider_id": provider["id"]}
    )
    assert response.status_code == 422


def test_an_unknown_effort_is_rejected(as_superadmin: TestClient) -> None:
    """Effort is constrained at the schema, before it reaches the database CHECK."""
    provider = _create(as_superadmin)
    response = as_superadmin.put(
        "/admin/ai/routing/ask", json={"provider_id": provider["id"], "effort": "maximum"}
    )
    assert response.status_code == 422


# ── Test connection ──────────────────────────────────────────────────────────


def test_a_failed_connection_check_is_still_a_200(
    as_superadmin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed *check* is a successful *test*.

    Returning 502 would make a working diagnostic look like a broken endpoint, and
    the interface could not distinguish "the test ran and the provider is down"
    from "the test endpoint is down".
    """
    monkeypatch.delenv("NOWHERE_KEY", raising=False)
    provider = _create(
        as_superadmin,
        name="nowhere",
        api_key_env="NOWHERE_KEY",
        base_url="http://127.0.0.1:9/v1",
    )

    response = as_superadmin.post(f"/admin/ai/providers/{provider['id']}/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["code"] == "AI_UNAVAILABLE"


def test_testing_an_anthropic_provider_without_a_key_reports_the_variable(
    as_superadmin: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check names what is missing rather than reporting a generic failure."""
    monkeypatch.delenv("ABSENT_ANTHROPIC_KEY", raising=False)
    provider = _create(
        as_superadmin,
        name="claude",
        kind="anthropic",
        api_key_env="ABSENT_ANTHROPIC_KEY",
        base_url=None,
    )

    body = as_superadmin.post(f"/admin/ai/providers/{provider['id']}/test").json()

    assert body["ok"] is False
    assert body["code"] == "AI_KEY_MISSING"
    assert "ABSENT_ANTHROPIC_KEY" in body["detail"]


# ── Usage ────────────────────────────────────────────────────────────────────


def test_usage_starts_empty(as_superadmin: TestClient) -> None:
    """No calls means no rows, not a zero-filled calendar."""
    assert as_superadmin.get("/admin/ai/usage").json() == []


def test_usage_rejects_a_nonsense_window(as_superadmin: TestClient) -> None:
    """Bounded at the schema, so the query is never handed a negative window."""
    assert as_superadmin.get("/admin/ai/usage?days=0").status_code == 422
    assert as_superadmin.get("/admin/ai/usage?days=99999").status_code == 422
