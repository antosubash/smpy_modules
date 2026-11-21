"""A pause made while a fetch is in flight outlives that fetch's result."""

from __future__ import annotations

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Subscription
from sqlalchemy import update

from tests.feeds.subscriptions.refresh_support import Fetcher, load, ok, seed, tick


@pytest.mark.unbound_tenant
async def test_a_pause_during_a_fetch_is_kept(db_state):
    (sid,) = await seed(db_state)

    class Pause(Fetcher):
        async def __call__(self, url, **kw):
            with tenant_scope("default"):
                async with db_state.session_factory() as db:
                    await db.execute(
                        update(Subscription).where(Subscription.id == sid).values(status="paused")
                    )
                    await db.commit()
            return await super().__call__(url, **kw)

    got = await tick(db_state, Pause(ok()))
    assert got["fetched"] == 1
    sub = await load(db_state, sid)
    assert sub.status == "paused" and sub.item_count > 0 and sub.lease_owner is None
