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


async def test_an_anonymous_status_list_names_only_public_sources(db, spies):
    """What the occurrences read reports to an anonymous caller: a hidden source has no entry."""
    from sm_events.calendar.occurrence import OccurrenceFilters
    from sm_events.calendar.occurrences import occurrences
    from sm_events.core.access.public import ANONYMOUS

    from tests.support.access import seed_calendars

    cals = await seed_calendars(db)
    cals["U"].sources = [{"id": s, "settings": {}} for s in ("acme:priv", "acme:pub", "gone:x")]
    cals["I"].sources = [{"id": "acme:pub", "settings": {}}]
    await db.flush()
    page = await occurrences(
        db,
        tenant_id="default",
        viewer=ANONYMOUS,
        start=WHEN["start"].replace(day=1),
        end=WHEN["end"].replace(day=28),
        filters=OccurrenceFilters(),
        default_locale="en",
    )
    assert [(s.id, s.calendar_id) for s in page.sources] == [("acme:pub", cals["U"].id)]


async def test_keys_and_urls_are_namespaced_and_http_only(public_locales_client, spies):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub"])
    native = (await public_locales_client.get(surfaces(fx)["api"])).json()["items"]
    native_keys = {i["key"] for i in native if i["source"] == "events"}
    assert native_keys
    clash = sorted(native_keys)[0]
    _, public = spies
    public._behave = ok(item(clash, "Clash", url="https://ok.example/x", **WHEN))
    body = (await public_locales_client.get(surfaces(fx)["api"])).json()["items"]
    mine = [i for i in body if i["source"] == "acme:pub"]
    assert [i["key"] for i in mine] == [f"acme:pub:{clash}"]
    assert len({i["key"] for i in body}) == len(body)  # unique across sources
    ics = await public_locales_client.get(surfaces(fx)["cal_ics"])
    uids = [str(e["UID"]) for e in icalendar.Calendar.from_ical(ics.content).walk("VEVENT")]
    assert uids.count(f"acme:pub:{clash}") == 1  # native series repeat a UID by design
    assert not any(u.endswith("@simple-module-events") and u.startswith("acme") for u in uids)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "ftp://a/x", "//evil"])
async def test_a_non_http_url_drops_the_whole_answer(public_locales_client, spies, url):
    fx = await seed_public(public_locales_client)
    await enable(public_locales_client, fx, pub=["acme:pub"])
    _, public = spies
    public._behave = ok(item("a", "Fine", **WHEN), item("b", "Bad", url=url, **WHEN))
    got = await public_locales_client.get(surfaces(fx)["api"])
    assert got.status_code == 200
    assert not [i for i in got.json()["items"] if i["source"] == "acme:pub"]
    assert "Fine" not in got.text and url not in got.text


async def test_an_item_for_another_calendar_is_refused(db):
    """A source gets one calendar per call and cannot name another: a native occurrence (which
    carries a calendar id) is not a ``SourceOccurrence`` and refuses the answer."""
    import uuid
    from datetime import UTC

    from sm_events.calendar import source_entries
    from sm_events.calendar.occurrence import Occurrence
    from sm_events.calendar.plugin_runner import Call, run_sources

    from tests.support.access import seed_calendars

    cal = source_entries.source_calendar((await seed_calendars(db))["U"])
    other = Occurrence(
        source="events",
        key="k",
        calendar_id=uuid.uuid4(),
        start=WHEN["start"],
        end=WHEN["end"],
        all_day=False,
        timezone="UTC",
        title="Elsewhere",
        lang="en",
        color="#2563eb",
        type="event",
    )
    src = FakeSource("acme:pub", ok(other), public=True)
    result = await run_sources(
        db,
        [Call(cal, source_entries.SourceEntry("acme:pub", {}), src)],
        tenant_id="default",
        viewer=None,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 12, 1, tzinfo=UTC),
        locale="en",
        default_locale="en",
    )
    assert result.items == [] and result.statuses[0].code == "invalid_item"
