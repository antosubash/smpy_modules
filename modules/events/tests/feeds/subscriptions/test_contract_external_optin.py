"""Another module reading ``contracts.occurrences`` never gets another calendar's events by
accident: external (subscribed) items are an explicit opt-in."""

from __future__ import annotations

from datetime import UTC, datetime

from sm_events.contracts import occurrences as contract
from sm_events.core.tenancy import tenant_scope

from tests.support.occurrences import OWNER, utc
from tests.support.subscriptions import seed_calendar, seed_item, seed_subscription

START, END = utc(2027, 3, 1), utc(2027, 3, 31)


async def _seed(db):
    cal = await seed_calendar(db, "pub", visibility="public")
    sub = await seed_subscription(db, cal, public=True)
    await seed_item(db, sub, "x", datetime(2027, 3, 10, 9, tzinfo=UTC), title="Third party")
    await db.commit()


async def _titles(db, viewer, **kw):
    with tenant_scope("default"):
        page = await contract.occurrences(
            db, tenant_id="default", viewer=viewer, start=START, end=END, **kw
        )
    return [o.title for o in page.items if o.source == "subscriptions"]


async def test_external_items_are_not_returned_by_default(db):
    await _seed(db)
    assert await _titles(db, None) == []
    assert await _titles(db, OWNER) == []
    assert await _titles(db, None, sources=["subscriptions"]) == []  # naming it is not enough


async def test_external_items_come_with_the_explicit_opt_in(db):
    await _seed(db)
    assert await _titles(db, None, include_external=True) == ["Third party"]
    assert await _titles(db, OWNER, include_external=True) == ["Third party"]
