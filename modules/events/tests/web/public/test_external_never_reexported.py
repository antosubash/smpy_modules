"""External items are never re-published, reminded or offered as cards: one test per consumer.

A public calendar with a published event of ours and a ``public`` subscription whose cached items
have unique titles. Every surface that lists our events must carry ours and neither external
title nor a ``subscriptions:`` key. The public grid's API is the one surface that shows them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.web.endpoints.public import _urls

from tests.support.public import seed_public
from tests.support.subscriptions import seed_item, seed_subscription

ONE = "ExtOneOff-9f3"
SERIES = "ExtSeries-9f3"
BANNED = (ONE, SERIES, "subscriptions:")
APRIL = datetime(2026, 4, 10, 9, tzinfo=UTC)


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client)


async def add_external(client, calendar_id, *, public=True, label="Elsewhere"):
    """A subscription on ``calendar_id`` with a one-off and a weekly series, committed."""
    with tenant_scope("default"):
        async with client.db_state.session_factory() as db:
            from sm_events.models import Calendar
            from sqlalchemy import select

            cal = (
                await db.execute(select(Calendar).where(Calendar.id == calendar_id))
            ).scalar_one()
            sub = await seed_subscription(db, cal, label=label, public=public)
            await seed_item(db, sub, "one", APRIL, title=ONE)
            await seed_item(
                db, sub, "series", APRIL, title=SERIES, rrule="FREQ=WEEKLY", span_end=None,
                recurrence_until=None, timezone="UTC",
            )  # fmt: skip
            await db.commit()
            return sub.id


def clean(text: str) -> None:
    for banned in BANNED:
        assert banned not in text, banned


@pytest.fixture
async def ext(public_locales_client, fx):
    await add_external(public_locales_client, fx.pub.id)
    return fx


@pytest.mark.parametrize(
    "surface", ["feed_all", "feed_calendar", "feed_event", "sitemap", "listing", "event_page"]
)
async def test_public_surfaces_carry_ours_and_never_theirs(public_locales_client, ext, surface):
    fx, client = ext, public_locales_client
    slug = fx.slug(fx.one_off)
    path = {
        "feed_all": _urls.calendar_ics_path(None, "en"),
        "feed_calendar": _urls.calendar_ics_path(fx.pub.slug, "en"),
        "feed_event": _urls.event_ics_path(slug, "en"),
        "sitemap": _urls.sitemap_path(),
        "listing": _urls.index_path("en"),
        "event_page": _urls.event_path(slug, "en"),
    }[surface]  # fmt: skip
    got = await client.get(path)
    assert got.status_code == 200, (surface, got.text[:200])
    clean(got.text)
    if surface != "event_page":
        assert slug.title() in got.text or slug in got.text or surface == "feed_event"


async def test_the_json_ld_of_an_event_page_carries_nothing_external(public_locales_client, ext):
    got = await public_locales_client.get(_urls.event_path(ext.slug(ext.series), "en"))
    clean(got.text)
    assert "application/ld+json" in got.text


async def test_the_private_token_feed_carries_nothing_external():
    from tests.support.private_feed import private_http, seed_world

    async with private_http() as http:
        world = await seed_world(http)
        await add_external(http, world.cals["P"].id, public=True)
        await add_external(http, world.cals["P"].id, public=False, label="Quiet")
        got = await http.get(world.path)
        assert got.status_code == 200
        clean(got.text)
        assert "Published" in got.text


async def test_the_card_search_never_returns_an_external_item(public_locales_client, ext):
    from sm_events.contracts.cards import search_events

    async with public_locales_client.db_state.session_factory() as session:
        cards = await search_events(session, tenant_id="default", pattern="%Ext%")
    assert cards == []
    async with public_locales_client.db_state.session_factory() as session:
        assert await search_events(session, tenant_id="default", pattern="%") != []


async def test_public_grid_does_show_public_items(public_locales_client, ext):
    got = await public_locales_client.get(
        f"{_urls.api_path()}?start=2026-04-01T00:00:00Z&end=2026-05-15T00:00:00Z"
    )
    items = got.json()["items"]
    external = [i for i in items if i["source"] == constants.SOURCE_SUBSCRIPTIONS]
    assert {i["title"] for i in external} == {ONE, SERIES}
    assert {i["origin_label"] for i in external} == {"Elsewhere"}
    assert all(i["key"].startswith("subscriptions:") and i["editable"] is False for i in external)
    assert all(i["event_id"] is None for i in external)


async def test_public_grid_hides_non_public_subscription(public_locales_client, fx):
    await add_external(public_locales_client, fx.pub.id, public=False)
    got = await public_locales_client.get(
        f"{_urls.api_path()}?start=2026-04-01T00:00:00Z&end=2026-05-15T00:00:00Z"
    )
    clean(got.text)


async def test_the_blocks_occurrences_route_leaves_them_out(public_locales_client, ext):
    got = await public_locales_client.get(
        f"{constants.PUBLIC_BLOCKS_API}/occurrences?start=2026-04-01T00:00:00Z&end=2026-05-15T00:00:00Z"
    )
    assert got.status_code == 200
    clean(got.text)
