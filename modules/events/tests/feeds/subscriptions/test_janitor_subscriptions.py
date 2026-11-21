"""The janitor purges subscriptions that were deleted long ago, with their items."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.importing.janitor import janitor_async
from sm_events.models import ExternalItem, Subscription
from sqlalchemy import select

from tests.support.subscriptions import seed_calendar, seed_item, seed_subscription

pytestmark = pytest.mark.unbound_tenant
NOW = utcnow()
DAY = timedelta(days=1)


async def _seed(db_state, tenant):
    """A live subscription, one deleted 31 days ago and one deleted 29 days ago, each with an
    item. Returns their labels' ids."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            cal = await seed_calendar(db, "c")
            ids = {}
            for label, fields in (
                ("live", {}),
                ("old", {"is_deleted": True, "deleted_at": NOW - 31 * DAY, "url_enc": ""}),
                ("recent", {"is_deleted": True, "deleted_at": NOW - 29 * DAY, "url_enc": ""}),
            ):
                sub = await seed_subscription(db, cal, label=label, **fields)
                await seed_item(db, sub, label, NOW)
                ids[label] = sub.id
            await db.commit()
    return ids


async def _left(db_state, tenant):
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            from sm_events.core.tenancy import all_tenants

            subs = (
                await db.execute(
                    all_tenants(select(Subscription.label)).execution_options(include_deleted=True)
                )
            ).scalars()
            items = (await db.execute(all_tenants(select(ExternalItem.uid)))).scalars()
            return sorted(subs), sorted(items)


async def test_purges_old_deleted_subscriptions_per_tenant(db_state):
    await _seed(db_state, "a")
    await _seed(db_state, "b")
    summary = await janitor_async(db_state.session_factory, now=NOW, relaunch=lambda *a: None)
    assert summary["subscriptions"] == 2
    for tenant in ("a", "b"):
        subs, items = await _left(db_state, tenant)
        assert "old" not in subs and {"live", "recent"} <= set(subs)
        assert "old" not in items and {"live", "recent"} <= set(items)
    again = await janitor_async(db_state.session_factory, now=NOW, relaunch=lambda *a: None)
    assert again["subscriptions"] == 0


async def test_one_tenants_pass_purges_only_its_own_rows(db_state):
    from sm_events.feeds.importing.janitor import _purge_subscriptions

    await _seed(db_state, "a")
    await _seed(db_state, "b")
    with tenant_scope("a"):
        async with db_state.session_factory() as db:
            assert await _purge_subscriptions(db, NOW) == 1
            await db.commit()
    subs_a, items_a = await _left(db_state, "a")
    assert "old" not in subs_a and "old" not in items_a
    subs_b, items_b = await _left(db_state, "b")
    assert "old" in subs_b and "old" in items_b  # tenant b's pass has not run


async def test_the_purge_statements_name_their_tenant(db_state):
    """Core DML carries its own tenant predicate, whatever the framework adds."""
    from sm_events.feeds.importing.janitor import _purge_subscriptions
    from sqlalchemy import event

    await _seed(db_state, "a")
    seen: list[str] = []
    engine = db_state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", lambda c, cur, stmt, *a: seen.append(stmt))
    with tenant_scope("a"):
        async with db_state.session_factory() as db:
            await _purge_subscriptions(db, NOW)
            await db.commit()
    mine = [s for s in seen if s.startswith(("DELETE", "SELECT")) and "events_subscription" in s]
    assert mine and all("tenant_id" in s for s in mine)
