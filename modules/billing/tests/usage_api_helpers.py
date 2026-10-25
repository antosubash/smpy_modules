"""Builders for the usage-screen tests: registered meters and a metered plan."""

from __future__ import annotations

import uuid

from helpers import make_plan
from sm_billing.constants import METERS_STATE_ATTR, USAGE_STATE_ATTR
from sm_billing.models import Subscription

COUNTER = "exports.monthly"
GAUGE = "jobs.concurrent"
BYTES = "storage.bytes"
ADMIN = "/api/billing/admin/usage"


def define_meters(app) -> None:
    reg = getattr(app.state, METERS_STATE_ATTR)
    reg.define(key=COUNTER, kind="counter", label_key="demo.meters.exports")
    reg.define(key=GAUGE, kind="gauge")
    reg.define(key=BYTES, kind="gauge", unit="bytes")


def usage(app):
    return getattr(app.state, USAGE_STATE_ATTR)


async def put_on_plan(app, tenant_id: str, limits: dict[str, int]) -> None:
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, f"m-{uuid.uuid4().hex[:8]}", limits=limits)
        session.add(Subscription(tenant_id=tenant_id, plan_id=plan.id))
        await session.commit()


async def consume(app, tenant_id: str, qty: int, meter: str = COUNTER) -> None:
    outcome = await usage(app).consume(tenant_id, meter, qty, uuid.uuid4().hex, source="test")
    assert outcome.ok, outcome


async def reserve(app, tenant_id: str, qty: int = 1, meter: str = GAUGE):
    hold = await usage(app).reserve(tenant_id, meter, qty, uuid.uuid4().hex, source="test")
    assert hold.ok, hold
    return hold
