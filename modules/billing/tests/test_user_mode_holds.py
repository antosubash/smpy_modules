"""Two users' gauge holds stay apart, even under the same idempotency key (#274)."""

from __future__ import annotations

import uuid

from helpers import make_plan
from sm_billing.contracts.metering import Exceeded, Hold
from sm_billing.models import Subscription
from sm_billing.subjects import subject_for_user
from usage_helpers import GAUGE, gauge_service, hold_statuses, in_use


async def _on_gauge_plan(factory, subject: str) -> None:
    async with factory() as session:
        plan = await make_plan(session, f"g-{subject[-8:]}", limits={GAUGE: 1})
        session.add(Subscription(tenant_id=subject, plan_id=plan.id))
        await session.commit()


async def test_two_users_same_key_hold_separately(user_mode_app):
    factory = user_mode_app.state.sm.db.session_factory
    usage = gauge_service(factory)
    a, b = subject_for_user(uuid.uuid4()), subject_for_user(uuid.uuid4())
    for subject in (a, b):
        await _on_gauge_plan(factory, subject)

    held_a = await usage.reserve(a, GAUGE, 1, "same-key", source="t")
    held_b = await usage.reserve(b, GAUGE, 1, "same-key", source="t")
    assert isinstance(held_a, Hold) and isinstance(held_b, Hold)
    assert held_a.id != held_b.id
    assert (await in_use(factory, a), await in_use(factory, b)) == (1, 1)
    assert await hold_statuses(factory, a) == await hold_statuses(factory, b) == ["held"]

    # a's gauge is full; b's release does not free it.
    await usage.release(held_b.id)
    assert isinstance(await usage.reserve(a, GAUGE, 1, "next", source="t"), Exceeded)
    assert (await in_use(factory, a), await in_use(factory, b)) == (1, 0)
