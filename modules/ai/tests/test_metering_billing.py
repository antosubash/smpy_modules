"""``ai.requests`` metered by a running billing, on a single-tenant host.

The real app (``simple_module_test``'s ``app`` fixture over ``create_app``)
with billing and ai enabled: ai's ``on_startup`` registers the meter, the
plan limits it, and a route guarded by ``RequiresAiRequest`` answers 402
``quota_exceeded`` past the limit and refunds a handler that raised.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from pydantic_ai.exceptions import ModelHTTPError
from simple_module_db.tenancy import DEFAULT_TENANT_ID
from simple_module_hosting.settings import Settings
from simple_module_test.database import database_url_for_tests
from sm_ai.contracts import RequiresAiRequest

# Billing is optional for ai: a checkout of ai alone has nothing to meter with.
pytest.importorskip("sm_billing.metering.deps")

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULES = ["Auth", "Users", "Permissions", "Settings", "Tenants", "Billing", "Ai"]
PREFIX = "/api/ai-metering-test"


@pytest.fixture(autouse=True)
def _project_root(monkeypatch):
    """The Inertia templates live under the repo root, not this suite's cwd."""
    from simple_module_hosting import app_builder

    monkeypatch.setattr(app_builder, "_PROJECT_ROOT", REPO_ROOT)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=database_url_for_tests(),
        environment="testing",
        secret_key="test-secret-key",
        multi_tenant=False,
        auth_provider="users",
        modules_enabled=MODULES,
    )


def _route(app, path: str, endpoint) -> None:
    """Add a test route ahead of the host's catch-alls."""
    app.add_api_route(f"{PREFIX}{path}", endpoint, methods=["POST"])
    app.router.routes.insert(0, app.router.routes.pop())


@pytest.fixture
async def metered(app):
    """The app with metered test routes, and a plan allowing one AI request."""
    from sm_billing.constants import PricingModel
    from sm_billing.models import Plan, Subscription

    async def chat(outcome=RequiresAiRequest()):
        return {"used": outcome.used}

    async def provider_down(_=RequiresAiRequest()):
        raise HTTPException(502, "provider unavailable")

    async def provider_error(_=RequiresAiRequest()):
        raise ModelHTTPError(status_code=500, model_name="test", body="boom")

    _route(app, "/chat", chat)
    _route(app, "/down", provider_down)
    _route(app, "/error", provider_error)
    async with app.state.sm.db.session_factory() as session:
        plan = Plan(
            key="ai-one",
            name="AI one",
            pricing_model=PricingModel.FLAT,
            currency="eur",
            limits={"ai.requests": 1},
        )
        session.add(plan)
        await session.flush()
        session.add(Subscription(tenant_id=DEFAULT_TENANT_ID, plan_id=plan.id))
        await session.commit()
    return app


@pytest.fixture
async def http(metered, authenticated_client):
    """The seeded admin's session, on a transport where a handler's non-HTTP
    exception becomes a 500, as it would on a server."""
    transport = httpx.ASGITransport(app=metered, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies=authenticated_client.cookies,
    ) as c:
        yield c


def test_on_startup_registers_the_meter(app):
    meter = app.state.billing_meters.get("ai.requests")
    assert meter is not None
    assert (meter.kind, meter.unit, meter.label_key) == ("counter", "count", "ai.meters.requests")


async def test_the_second_request_answers_402(http):
    first = await http.post(f"{PREFIX}/chat")
    assert first.status_code == 200, first.text
    assert first.json() == {"used": 1}
    refused = await http.post(f"{PREFIX}/chat")
    assert refused.status_code == 402
    body = refused.json()
    assert body["detail"] == "quota_exceeded"
    assert {k: body[k] for k in ("meter", "limit", "used", "requested")} == {
        "meter": "ai.requests",
        "limit": 1,
        "used": 1,
        "requested": 1,
    }
    assert body["resets_at"]


@pytest.mark.parametrize("path", ["/down", "/error"])
async def test_a_provider_failure_does_not_burn_quota(http, path):
    failed = await http.post(f"{PREFIX}{path}")
    assert failed.status_code in (500, 502)
    # Refunded: the one request the plan allows is still there.
    assert (await http.post(f"{PREFIX}/chat")).status_code == 200
    assert (await http.post(f"{PREFIX}/chat")).status_code == 402


async def test_usage_is_charged_to_the_default_tenant(metered, http):
    assert (await http.post(f"{PREFIX}/chat")).status_code == 200
    usage = metered.state.billing_usage
    outcome = await usage.check(DEFAULT_TENANT_ID, "ai.requests")
    assert (outcome.used, outcome.limit) == (1, 1)
