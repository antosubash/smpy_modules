"""``RequiresQuota``: 402 body, refund only on a raised handler, key replays."""

from __future__ import annotations

import pytest
from api_helpers import create_tenant
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from helpers import make_plan
from sm_billing.constants import METERS_STATE_ATTR
from sm_billing.metering.deps import RequiresQuota
from sm_billing.models import Subscription
from usage_helpers import METER, events

PREFIX = "/api/quota-test"


def _route(app, path: str, endpoint) -> None:
    """Add a test route ahead of the host's catch-alls."""
    app.add_api_route(f"{PREFIX}{path}", endpoint, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())


@pytest.fixture
def quota_app(app):
    getattr(app.state, METERS_STATE_ATTR).define(key=METER, kind="counter")

    async def ok(outcome=RequiresQuota(METER)):
        return {"used": outcome.used, "replayed": outcome.replayed}

    async def boom(_=RequiresQuota(METER)):
        raise HTTPException(418, "teapot")

    async def soft_fail(_=RequiresQuota(METER)):
        return JSONResponse({"detail": "nope"}, status_code=422)

    _route(app, "/ok", ok)
    _route(app, "/boom", boom)
    _route(app, "/soft", soft_fail)
    return app


async def _limit(app, tenant_id: str, limit: int) -> None:
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "metered", limits={METER: limit})
        session.add(Subscription(tenant_id=tenant_id, plan_id=plan.id))
        await session.commit()


@pytest.fixture
async def owner(quota_app, user_client):
    async with user_client("owner@x.io") as (client, _):
        tenant = await create_tenant(client)
        await _limit(quota_app, tenant["id"], 2)
        client.tenant_id = tenant["id"]
        yield client


async def test_counts_then_answers_402(quota_app, owner):
    factory = quota_app.state.sm.db.session_factory
    assert (await owner.get(f"{PREFIX}/ok")).json() == {"used": 1, "replayed": False}
    assert (await owner.get(f"{PREFIX}/ok")).json()["used"] == 2
    refused = await owner.get(f"{PREFIX}/ok")
    assert refused.status_code == 402
    body = refused.json()
    assert body["detail"] == "quota_exceeded"
    assert {k: body[k] for k in ("meter", "limit", "used", "requested")} == {
        "meter": METER,
        "limit": 2,
        "used": 2,
        "requested": 1,
    }
    assert body["resets_at"].endswith("+00:00")
    assert await events(factory, owner.tenant_id) == 2


async def test_a_raised_handler_is_refunded(quota_app, owner):
    factory = quota_app.state.sm.db.session_factory
    assert (await owner.get(f"{PREFIX}/boom")).status_code == 418
    assert await events(factory, owner.tenant_id, kind="refund") == 1
    assert (await owner.get(f"{PREFIX}/ok")).json()["used"] == 1


async def test_a_returned_error_keeps_the_charge(quota_app, owner):
    assert (await owner.get(f"{PREFIX}/soft")).status_code == 422
    assert (await owner.get(f"{PREFIX}/ok")).json()["used"] == 2


async def test_an_idempotency_key_makes_a_retry_free(quota_app, owner):
    headers = {"Idempotency-Key": "client-1"}
    first = (await owner.get(f"{PREFIX}/ok", headers=headers)).json()
    again = (await owner.get(f"{PREFIX}/ok", headers=headers)).json()
    assert first == {"used": 1, "replayed": False}
    assert again["replayed"] is True
    # The same key on another route is another call: 409, never a free pass.
    other = await owner.get(f"{PREFIX}/soft", headers=headers)
    assert other.status_code == 409 and other.json()["detail"] == "idempotency_conflict"


async def test_a_refunded_key_is_spent(quota_app, owner):
    headers = {"Idempotency-Key": "client-2"}
    assert (await owner.get(f"{PREFIX}/boom", headers=headers)).status_code == 418
    retry = await owner.get(f"{PREFIX}/boom", headers=headers)
    assert retry.status_code == 409 and retry.json()["detail"] == "idempotency_key_spent"


@pytest.mark.parametrize("key", ["x" * 122, "a:refund", "adjust:1", " "])
async def test_bad_keys_are_400(quota_app, owner, key):
    response = await owner.get(f"{PREFIX}/ok", headers={"Idempotency-Key": key})
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_idempotency_key"


async def test_no_tenant_is_403(quota_app, user_client):
    async with user_client("lonely@x.io") as (client, _):
        response = await client.get(f"{PREFIX}/ok")
    assert response.status_code == 403
    assert response.json()["detail"] == "tenant_required"


async def test_without_billing_started_nothing_is_limited(quota_app, owner, monkeypatch):
    monkeypatch.delattr(quota_app.state, "billing_usage")

    async def free(outcome=RequiresQuota(METER)):
        return {"outcome": outcome}

    _route(quota_app, "/free", free)
    assert (await owner.get(f"{PREFIX}/free")).json() == {"outcome": None}
    assert await events(quota_app.state.sm.db.session_factory, owner.tenant_id) == 0


def test_bad_arguments_fail_at_definition():
    with pytest.raises(ValueError):
        RequiresQuota(METER, 0)
    with pytest.raises(ValueError):
        RequiresQuota("")
