"""A block selection that resolves to nothing shows nothing, on all three anonymous routes."""

from __future__ import annotations

import uuid

import pytest

from tests.support.public import seed_public
from tests.web.public.test_public_blocks_api import CALENDARS, OCCURRENCES, UPCOMING, YEAR, qs


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client, german=False)


async def _all(client, query: str):
    """The three routes for one selection: (calendars, upcoming items, occurrence items)."""
    cal = (await client.get(f"{CALENDARS}?{query}")).json()["calendars"]
    up = (await client.get(f"{UPCOMING}?count=20&{query}")).json()["items"]
    return cal, up


async def test_a_selection_that_resolves_to_nothing_shows_nothing_on_every_route(
    public_locales_client, fx
):
    """The rule, in effect: unknown slugs, only non-public calendars, a malformed slug or an empty
    one is *nothing*, never every public calendar; one valid slug beside an unknown one is just the
    valid one."""
    for query in (
        qs(calendar=["nope"]),
        qs(calendar=["nope", "also-not-there"]),
        qs(calendar=[fx.internal.slug]),
        qs(calendar=[fx.private.slug, fx.gone.slug]),
        qs(calendar=["Not A Slug!"]),
        "calendar=",
    ):
        cal, up = await _all(public_locales_client, query)
        assert cal == [] and up == [], query
    cal, up = await _all(public_locales_client, qs(calendar=[fx.pub.slug, "nope"]))
    assert [c["slug"] for c in cal] == [fx.pub.slug]
    assert up and {i["calendar"]["slug"] for i in up} == {fx.pub.slug}
    everything = await _all(public_locales_client, "")
    assert len(everything[0]) == 1 and everything[1]  # no selection: every public calendar

    for ids in (
        [uuid.uuid4()],
        [fx.internal.id],
        [fx.private.id, fx.gone.id],
    ):
        got = await public_locales_client.get(f"{OCCURRENCES}?{YEAR}&{qs(calendar=ids)}")
        assert got.status_code == 200 and got.json()["items"] == [], ids
    mixed = await public_locales_client.get(
        f"{OCCURRENCES}?{YEAR}&{qs(calendar=[fx.pub.id, uuid.uuid4()])}"
    )
    assert mixed.json()["items"], "the valid calendar's events"
    assert {i["calendar_id"] for i in mixed.json()["items"]} == {str(fx.pub.id)}


async def test_the_read_is_never_asked_for_every_calendar_when_a_selection_was_given(
    public_locales_client, fx, monkeypatch
):
    """A refactor to ``calendar_ids=None`` would turn "nothing" into "everything": the downstream
    reads are spied on, and none gets ``None`` (or is called at all) for a selection."""
    from sm_events.web.endpoints.public import _api, _blocks_api

    seen: list[tuple[str, object]] = []
    real_upcoming, real_page = _blocks_api.upcoming, _api.public_page

    async def upcoming(db, **kw):
        seen.append(("upcoming", kw["calendar_ids"]))
        return await real_upcoming(db, **kw)

    async def page(db, **kw):
        seen.append(("occurrences", kw["calendar_ids"]))
        return await real_page(db, **kw)

    monkeypatch.setattr(_blocks_api, "upcoming", upcoming)
    monkeypatch.setattr(_api, "public_page", page)

    for slugs in (["nope"], [fx.internal.slug], ["nope", fx.pub.slug], ["Not A Slug!"], [""]):
        seen.clear()
        await public_locales_client.get(f"{UPCOMING}?{qs(calendar=slugs)}")
        assert all(ids is not None for _, ids in seen), slugs  # not called, or given a list
    seen.clear()
    await public_locales_client.get(f"{UPCOMING}")
    assert seen == [("upcoming", None)]  # no selection: every public calendar, and only then
    seen.clear()
    await public_locales_client.get(f"{OCCURRENCES}?{YEAR}&{qs(calendar=[uuid.uuid4()])}")
    assert [ids is not None for _, ids in seen] == [True]
