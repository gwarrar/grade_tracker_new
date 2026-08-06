"""Superadmin configuration of AI providers, routing and usage.

Superadmin rather than admin throughout. These endpoints decide where student
names, emails and grades are sent — that is a different class of decision from
managing a course register, and it deserves the narrower role.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from pydantic import BaseModel, Field

from api.deps import DbConn, SuperAdminUser
from llm.registry import Feature
from notenverwaltung.storage import transaction
from services.ai_admin import AiAdminService

router = APIRouter(prefix="/admin/ai", tags=["AI administration"])


class ProviderRequest(BaseModel):
    """A new provider."""

    name: str = Field(min_length=1, max_length=60, examples=["openrouter"])
    kind: str = Field(
        description="Which implementation drives it.",
        examples=["openai_compatible"],
        pattern="^(anthropic|openai_compatible)$",
    )
    default_model: str = Field(min_length=1, max_length=120, examples=["claude-opus-5"])
    base_url: str | None = Field(
        default=None,
        description="Endpoint root without `/chat/completions`. Null for the vendor default.",
        examples=["https://openrouter.ai/api/v1"],
    )
    api_key_env: str = Field(
        default="",
        max_length=80,
        # Enforced, not merely documented. The field invites a paste, and a pasted
        # key is silently useless -- os.environ has no such name, so the request goes
        # out unauthenticated -- while also putting a live credential in a table the
        # design promises never holds one. An identifier cannot express a key.
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$|^$",
        description=(
            "The **name** of the environment variable holding the key — never the key. "
            "A leak of this table therefore exposes no credentials. Leave empty for a "
            "local endpoint that authenticates nothing."
        ),
        examples=["OPENROUTER_API_KEY"],
    )
    is_enabled: bool = True
    is_third_party_pool: bool = Field(
        default=False,
        description=(
            "Set for providers that route through third-party free pools whose data "
            "retention terms are unknown. This application holds student records, so "
            "the interface shows a privacy warning wherever this is set."
        ),
    )
    params_json: str = Field(
        default="{}",
        max_length=20_000,
        description=(
            "Extra request-body keys as a JSON object. Use this for generation "
            "settings such as temperature or vendor-specific thinking controls."
        ),
        examples=[
            (
                '{"temperature":0.6,"top_p":0.95,"max_tokens":4096,'
                '"chat_template_kwargs":{"thinking":true,"reasoning_effort":"high"}}'
            )
        ],
    )


class ProviderPatch(BaseModel):
    """Changes to a provider. `kind` is immutable — delete and recreate instead."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    default_model: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = None
    # Same guard as on create: a pasted key is both useless and a stored credential.
    api_key_env: str | None = Field(
        default=None, max_length=80, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$|^$"
    )
    is_enabled: bool | None = None
    is_third_party_pool: bool | None = None
    params_json: str | None = Field(default=None, max_length=20_000)


class ProviderResponse(BaseModel):
    """A configured provider."""

    id: int
    name: str
    kind: str
    base_url: str | None
    api_key_env: str = Field(description="Variable name. Never the key itself.")
    default_model: str
    is_enabled: bool
    is_third_party_pool: bool
    params_json: str
    key_present: bool = Field(
        description=(
            "Whether the named environment variable is set. A boolean, never a value — "
            "the interface can tell that a key exists without ever being able to show it."
        )
    )


class TestResponse(BaseModel):
    """The outcome of a live check against a provider."""

    ok: bool
    code: str = Field(
        description="Stable identifier the interface translates.",
        examples=["AI_OK", "AI_UNAUTHORIZED"],
    )
    detail: str = Field(description="English detail for the administrator. Not translated.")


class RoutingRequest(BaseModel):
    """Which provider serves a feature."""

    provider_id: int
    model: str = Field(default="", max_length=120, description="Empty for the provider default.")
    effort: str = Field(default="medium", pattern="^(low|medium|high|xhigh|max)$")


class RoutingResponse(BaseModel):
    """A feature's routing."""

    feature: str
    provider_id: int
    provider_name: str
    model: str
    effort: str


class UsageResponse(BaseModel):
    """One day's usage of one feature."""

    day: str
    feature: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_estimate: float = Field(
        description=(
            "Approximate USD, from a static price table. An order of magnitude beside a "
            "token count, not an invoice — providers change prices and free pools have none."
        )
    )
    errors: int


def service(conn: DbConn) -> AiAdminService:
    """Build the AI administration service for this request.

    Args:
        conn: The request's connection.

    Returns:
        The service.
    """
    return AiAdminService(conn)


Admin = Annotated[AiAdminService, Depends(service)]
FeaturePath = Annotated[Feature, Path(description="Which capability.", examples=["ask"])]


@router.get("/providers", response_model=list[ProviderResponse], summary="List providers")
def list_providers(_: SuperAdminUser, admin: Admin) -> list[ProviderResponse]:
    """List every configured provider and whether its key is available.

    Args:
        _: Enforces the superadmin role.
        admin: The service.

    Returns:
        Every provider, ordered by name.
    """
    return [
        ProviderResponse(**asdict(status_.config), key_present=status_.key_present)
        for status_ in admin.list_providers()
    ]


@router.post(
    "/providers",
    response_model=ProviderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a provider",
)
def create_provider(
    body: ProviderRequest, user: SuperAdminUser, admin: Admin, conn: DbConn
) -> ProviderResponse:
    """Add a provider.

    Args:
        body: The new provider.
        user: The acting superadmin.
        admin: The service.
        conn: The request's connection, for the transaction.

    Returns:
        The stored provider.
    """
    with transaction(conn):
        config = admin.create_provider(actor_id=user.user_id, **body.model_dump())
    return _with_key_status(admin, config.id)


@router.patch(
    "/providers/{provider_id}", response_model=ProviderResponse, summary="Update a provider"
)
def update_provider(
    provider_id: int, body: ProviderPatch, user: SuperAdminUser, admin: Admin, conn: DbConn
) -> ProviderResponse:
    """Change a provider's configuration.

    Args:
        provider_id: Which provider.
        body: The changes. Omitted fields are left alone.
        user: The acting superadmin.
        admin: The service.
        conn: The request's connection.

    Returns:
        The updated provider.
    """
    with transaction(conn):
        admin.update_provider(
            provider_id, actor_id=user.user_id, **body.model_dump(exclude_unset=True)
        )
    return _with_key_status(admin, provider_id)


@router.delete(
    "/providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a provider",
    description=(
        "Any feature routed to this provider loses its routing. That is deliberate: "
        "a route pointing at a deleted provider would fail at request time rather "
        "than at configuration time."
    ),
)
def delete_provider(provider_id: int, user: SuperAdminUser, admin: Admin, conn: DbConn) -> None:
    """Remove a provider.

    Args:
        provider_id: Which provider.
        user: The acting superadmin.
        admin: The service.
        conn: The request's connection.
    """
    with transaction(conn):
        admin.delete_provider(provider_id, actor_id=user.user_id)


@router.post(
    "/providers/{provider_id}/test",
    response_model=TestResponse,
    summary="Test a provider's connection",
    description=(
        "Makes the smallest possible real call. A configuration that only fails when "
        "someone asks a real question is one nobody notices is broken until it matters.\n\n"
        "Always 200 — a failed *check* is a successful *test*, and returning 502 would "
        "make a working diagnostic look like a broken endpoint."
    ),
)
def test_provider(provider_id: int, _: SuperAdminUser, admin: Admin) -> TestResponse:
    """Verify a provider's credential and endpoint.

    Args:
        provider_id: Which provider.
        _: Enforces the superadmin role.
        admin: The service.

    Returns:
        Whether it worked, a stable code, and English detail.
    """
    ok, code, detail = admin.test_connection(provider_id)
    return TestResponse(ok=ok, code=code, detail=detail)


@router.get(
    "/providers/{provider_id}/models",
    response_model=list[str],
    summary="Models this provider offers",
    description=(
        "Asks the endpoint what it serves, so a model does not have to be typed from "
        "memory. A local Ollama offers whatever that machine has pulled, which no "
        "default could know.\n\n"
        "An empty list means the endpoint could not be reached or does not enumerate "
        "its models — the field stays typeable, so this is never blocking."
    ),
)
def provider_models(provider_id: int, _: SuperAdminUser, admin: Admin) -> list[str]:
    """List a provider's available models.

    Args:
        provider_id: Which provider.
        _: Enforces the superadmin role.
        admin: The service.

    Returns:
        Model identifiers, empty when the endpoint cannot list them.
    """
    return admin.available_models(provider_id)


@router.get("/routing", response_model=list[RoutingResponse], summary="Per-feature routing")
def get_routing(_: SuperAdminUser, admin: Admin) -> list[RoutingResponse]:
    """List which provider serves each feature.

    Args:
        _: Enforces the superadmin role.
        admin: The service.

    Returns:
        One entry per configured feature.
    """
    return [RoutingResponse(**asdict(route)) for route in admin.routing()]


@router.put("/routing/{feature}", response_model=RoutingResponse, summary="Route a feature")
def set_routing(
    feature: FeaturePath, body: RoutingRequest, user: SuperAdminUser, admin: Admin, conn: DbConn
) -> RoutingResponse:
    """Point a feature at a provider and model.

    Args:
        feature: Which capability.
        body: Provider, model and effort.
        user: The acting superadmin.
        admin: The service.
        conn: The request's connection.

    Returns:
        The stored routing.
    """
    with transaction(conn):
        route = admin.set_routing(feature, actor_id=user.user_id, **body.model_dump())
    return RoutingResponse(**asdict(route))


@router.get("/usage", response_model=list[UsageResponse], summary="Usage and estimated cost")
def get_usage(
    _: SuperAdminUser,
    admin: Admin,
    days: Annotated[int, Query(ge=1, le=365, description="How far back to look.")] = 30,
) -> list[UsageResponse]:
    """Summarise usage by day, feature and model.

    Args:
        _: Enforces the superadmin role.
        admin: The service.
        days: How far back to look.

    Returns:
        One row per day, feature and model, most recent first.
    """
    return [UsageResponse(**asdict(row)) for row in admin.usage(days=days)]


def _with_key_status(admin: AiAdminService, provider_id: int) -> ProviderResponse:
    """Return one provider's response, including whether its key is set.

    Args:
        admin: The service.
        provider_id: Which provider.

    Returns:
        The provider.

    Raises:
        StopIteration: Never in practice — the caller has just written the row.
    """
    status_ = next(item for item in admin.list_providers() if item.config.id == provider_id)
    return ProviderResponse(**asdict(status_.config), key_present=status_.key_present)
