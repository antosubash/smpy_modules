"""Scheduled publishing under strict tenant isolation, and with a failing event."""

from __future__ import annotations

import pytest
from simple_module_db.query_filter import EngineTenancy, bind_engine_policy
from sm_events.content import publish_due

from tests.content.test_publish_due import PAST, events_of, revisions_of, run, seed


def strict(state):
    """What a multi-tenant host runs: no tenant bound means an error, not every tenant."""
    bind_engine_policy(state.engine.sync_engine, EngineTenancy(tenant_strict=True))


@pytest.mark.unbound_tenant
async def test_strict_isolation_publishes_each_tenant_and_leaks_none(db_state):
    strict(db_state)
    (a,) = await seed(db_state, "a")
    (b,) = await seed(db_state, "b")
    assert await run(db_state) == {"tenants": 2, "published": 2, "failed": 0}
    for tenant, own in (("a", a), ("b", b)):
        (event,) = await events_of(db_state, tenant)
        assert (event.id, event.status, event.tenant_id) == (own, "published", tenant)
        (rev,) = await revisions_of(db_state, tenant)
        assert (rev.event_id, rev.tenant_id) == (own, tenant)


@pytest.mark.unbound_tenant
async def test_a_failing_event_is_counted_and_the_rest_still_publish(db_state, monkeypatch, caplog):
    ids = await seed(db_state, "a", count=3)
    (other,) = await seed(db_state, "b")
    poison = sorted(ids)[1]
    real = publish_due.publish_scheduled

    async def flaky(db, event, *, now):
        if event.id == poison:
            async with db.begin_nested():
                event.status = "published"  # half done, then it blows up
                await db.flush()
                raise RuntimeError("poison")
        await real(db, event, now=now)

    monkeypatch.setattr(publish_due, "publish_scheduled", flaky)
    with caplog.at_level("WARNING"):
        assert await run(db_state) == {"tenants": 2, "published": 3, "failed": 1}
    assert str(poison) in caplog.text
    by_id = {e.id: e for e in await events_of(db_state, "a")}
    assert {i: by_id[i].status for i in ids} == {
        i: ("draft" if i == poison else "published") for i in ids
    }
    assert by_id[poison].revision == 1 and by_id[poison].publish_at == PAST
    assert [e.status for e in await events_of(db_state, "b")] == ["published"]
    assert len(await revisions_of(db_state, "a")) == 2
    assert other  # tenant b was reached after a's failure

    monkeypatch.setattr(publish_due, "publish_scheduled", real)  # the next tick retries it
    assert await run(db_state) == {"tenants": 1, "published": 1, "failed": 0}
    assert {e.status for e in await events_of(db_state, "a")} == {"published"}
