"""A plugin source on the public surface: only a public one, only on a public calendar, only in
the grid and the feeds, and never with a viewer."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import icalendar
import pytest
from sm_events.calendar import registry
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar
from sm_events.web.endpoints.public import _urls
from sqlalchemy import select

from tests.support.app import as_user
from tests.support.public import INERTIA, seed_public
from tests.support.sources import FakeSource, install, item, ok, raises

API = "{api}?start=2026-03-01T00:00:00Z&end=2026-06-01T00:00:00Z&locale=en"
WHEN = {
    "start": datetime(2026, 4, 10, 10, tzinfo=UTC),
    "end": datetime(2026, 4, 10, 11, tzinfo=UTC),
}


@pytest.fixture
def spies(monkeypatch):
    private = FakeSource("acme:priv", ok(item("p1", "SPY-PRIVATE", **WHEN)), public=False)
    public = FakeSource("acme:pub", ok(item("q1", "SPY-PUBLIC", **WHEN)), public=True)
    install(monkeypatch, private, public)
    yield private, public
    registry.reset_registry()


async def enable(client, fx, **by_calendar):
    cals = {"pub": fx.pub, "internal": fx.internal, "private": fx.private}

    async def go():
        with tenant_scope("default"):
            async with client.db_state.session_factory() as db:
                for name, ids in by_calendar.items():
                    row = (
                        await db.execute(select(Calendar).where(Calendar.id == cals[name].id))
                    ).scalar_one()
                    row.sources = [{"id": i, "settings": {}} for i in ids]
                await db.commit()

    await go()


def surfaces(fx):
    return {
        "api": API.format(api=_urls.api_path()),
        "calendar_ics": _urls.calendar_ics_path(None, "en"),
        "cal_ics": _urls.calendar_ics_path(fx.pub.slug, "en"),
        "index_list": _urls.index_path("en"),
        "calendar_page": _urls.calendar_path(fx.pub.slug, "en"),
        "sitemap": _urls.sitemap_path(),
    }


@pytest.mark.parametrize("name", ["api", "calendar_ics", "cal_ics", "index_list", "sitemap"])
async def test_private_source_never_public(public_locales_client, spies, name):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:priv"])
    private, _ = spies
    got = await public_locales_client.get(surfaces(fx)[name], headers=INERTIA)
    assert got.status_code == 200
    assert "SPY-PRIVATE" not in got.text and "acme:priv" not in got.text
    assert private.calls == []  # not even called


async def test_public_source_on_internal_calendar_absent(public_locales_client, spies):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, internal=["acme:pub"], private=["acme:pub"])
    _, public = spies
    for name in ("api", "calendar_ics", "cal_ics", "index_list"):
        got = await public_locales_client.get(surfaces(fx)[name], headers=INERTIA)
        assert "SPY-PUBLIC" not in got.text, name
    assert public.calls == []


async def test_public_source_called_with_no_viewer(public_locales_client, spies):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub", "acme:priv"])
    private, public = spies
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    for headers in ({}, manager):  # a signed-in visitor is still the public
        public.calls.clear()
        got = await public_locales_client.get(surfaces(fx)["api"], headers=headers)
        assert got.status_code == 200
        assert [c[0].viewer for c in public.calls] == [None]
    assert private.calls == []


async def test_public_source_items_reach_the_grid_and_the_feeds(public_locales_client, spies):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub"])
    api = (await public_locales_client.get(surfaces(fx)["api"])).json()
    mine = [i for i in api["items"] if i["source"] == "acme:pub"]
    assert [(i["title"], i["key"], i["editable"], i["event_id"]) for i in mine] == [
        ("SPY-PUBLIC", "acme:pub:q1", False, None)
    ]
    for name in ("calendar_ics", "cal_ics"):
        got = await public_locales_client.get(surfaces(fx)[name])
        uids = {str(e["UID"]) for e in icalendar.Calendar.from_ical(got.content).walk("VEVENT")}
        assert "acme:pub:q1" in uids, name


async def test_public_api_has_no_sources_field(public_locales_client, spies, caplog):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub"])
    _, public = spies
    public._behave = raises
    with caplog.at_level(logging.INFO, logger="sm_events.public"):
        got = await public_locales_client.get(surfaces(fx)["api"])
    assert got.status_code == 200
    assert "sources" not in got.json() and set(got.json()) == {"items", "truncated"}
    assert "acme:pub" in caplog.text and "failed" in caplog.text  # logged instead
    assert "acme:pub" not in got.text


async def test_plugin_items_not_in_listing_or_sitemap(public_locales_client, spies):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub"])
    _, public = spies
    for name in ("index_list", "calendar_page", "sitemap"):
        got = await public_locales_client.get(surfaces(fx)[name], headers=INERTIA)
        assert "SPY-PUBLIC" not in got.text, name
    page = await public_locales_client.get(
        _urls.event_path(fx.slug(fx.one_off, "en"), "en"), headers=INERTIA
    )
    assert "SPY-PUBLIC" not in page.text
    assert public.calls == []  # none of those reads called it


async def test_a_failing_public_source_leaves_the_grid_at_200(public_locales_client, spies):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub"])
    spies[1]._behave = raises
    got = await public_locales_client.get(surfaces(fx)["api"])
    assert got.status_code == 200
    assert any(i["source"] == "events" for i in got.json()["items"])
