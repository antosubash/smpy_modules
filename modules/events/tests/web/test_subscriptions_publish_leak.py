"""Making a subscription public never shows items fetched from an internal address, and a fetch
that started under another policy stores nothing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.core.access.public import ANONYMOUS
from sm_events.core.tenancy import tenant_scope
from sm_events.models import ExternalItem, Subscription
from sqlalchemy import select, update

from tests.feeds.subscriptions.refresh_support import Fetcher, load, ok, seed, tick
from tests.support.calendars import OWNER_P, as_user
from tests.support.occurrences import read
from tests.support.subscriptions import seed_item
from tests.support.subscriptions_http import SUBS, add, app_client, calendar, row, stub_launch

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
MANAGER_PUB = as_user("m", V, M, P)
DAY = (datetime(2027, 3, 1, tzinfo=UTC), datetime(2027, 3, 30, tzinfo=UTC))


async def _items(client):
    async with client.db_state.session_factory() as db:
        return (await db.execute(select(ExternalItem))).scalars().all()


async def test_publishing_an_internal_subscription_drops_what_it_fetched(monkeypatch):
    async with app_client(allow_private_subscription_urls=True) as client:
        stub_launch(monkeypatch)
        cid = await calendar(client, OWNER_P, visibility="public")
        made = (
            await add(client, cid, MANAGER_PUB, url="https://intranet.example.test/a.ics")
        ).json()
        assert made["uses_internal_addresses"] is True
        sub = await row(client, made["id"])
        async with client.db_state.session_factory() as db:
            await seed_item(
                db, sub, "secret", datetime(2027, 3, 10, 9, tzinfo=UTC), title="Intranet meeting"
            )
            await update_sub(db, etag='"v1"', last_modified="x", item_count=1)
            await db.commit()
        got = await client.patch(f"{SUBS}/{made['id']}", json={"public": True}, headers=MANAGER_PUB)
        assert got.status_code == 200 and got.json()["uses_internal_addresses"] is False
        assert await _items(client) == []  # gone in the same transaction
        after = await row(client, made["id"])
        assert (after.etag, after.last_modified, after.item_count, after.status) == (
            None,
            None,
            0,
            "pending",
        )
        async with client.db_state.session_factory() as db:
            page = await read(db, ANONYMOUS, *DAY)
        assert [i for i in page.items if i.source == "subscriptions"] == []


async def update_sub(db, **values):
    await db.execute(update(Subscription).values(**values))


async def test_the_generation_moves_when_the_policy_or_the_address_does(monkeypatch):
    async with app_client() as client:
        stub_launch(monkeypatch)
        cid = await calendar(client, OWNER_P, visibility="public")
        made = (await add(client, cid, MANAGER_PUB, url="https://a.example.test/a.ics")).json()
        first = (await row(client, made["id"])).policy_generation
        await client.patch(f"{SUBS}/{made['id']}", json={"label": "Renamed"}, headers=MANAGER_PUB)
        assert (await row(client, made["id"])).policy_generation == first  # not a policy change
        await client.patch(
            f"{SUBS}/{made['id']}",
            json={"url": "https://b.example.test/a.ics"},
            headers=MANAGER_PUB,
        )
        second = (await row(client, made["id"])).policy_generation
        assert second > first
        await client.patch(f"{SUBS}/{made['id']}", json={"public": True}, headers=MANAGER_PUB)
        assert (await row(client, made["id"])).policy_generation > second


@pytest.mark.unbound_tenant
async def test_a_fetch_that_started_under_another_policy_stores_nothing(db_state):
    """Public, the internal flag or the address changed while the fetch was in flight: each
    bumps ``policy_generation``, and the store step discards a result of another generation."""
    (sid,) = await seed(db_state)

    class Switch(Fetcher):
        async def __call__(self, url, **kw):
            with tenant_scope("default"):  # an edit lands while this fetch is in flight
                async with db_state.session_factory() as db:
                    await db.execute(
                        update(Subscription)
                        .where(Subscription.id == sid)
                        .values(policy_generation=Subscription.policy_generation + 1)
                    )
                    await db.commit()
            return await super().__call__(url, **kw)

    got = await tick(db_state, Switch(ok()))
    assert got["lease_lost"] == 1 and got["fetched"] == 0
    sub = await load(db_state, sid)
    assert (sub.generation, sub.item_count, sub.lease_owner) == (0, 0, None)  # lease freed
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            assert (await db.execute(select(ExternalItem))).scalars().all() == []


async def test_a_public_read_never_returns_a_subscription_that_is_not_public_now(monkeypatch):
    async with app_client() as client:
        stub_launch(monkeypatch)
        cid = await calendar(client, OWNER_P, visibility="public")
        made = (
            await add(client, cid, MANAGER_PUB, url="https://a.example.test/a.ics", public=True)
        ).json()
        sub = await row(client, made["id"])
        async with client.db_state.session_factory() as db:
            await seed_item(db, sub, "x", datetime(2027, 3, 10, 9, tzinfo=UTC), title="Shown")
            await db.commit()
            page = await read(db, ANONYMOUS, *DAY)
        assert [i.title for i in page.items if i.source == "subscriptions"] == ["Shown"]
        async with client.db_state.session_factory() as db:
            await db.execute(update(Subscription).values(public=False))
            await db.commit()
            page = await read(db, ANONYMOUS, *DAY)
        assert [i for i in page.items if i.source == "subscriptions"] == []
