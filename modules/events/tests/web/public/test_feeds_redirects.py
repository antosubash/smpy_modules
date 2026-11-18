"""Renamed slugs, hidden targets and tenants on the ``.ics`` routes."""

from __future__ import annotations

from datetime import UTC, datetime

import icalendar
import pytest
from sm_events.calendar import calendars
from sm_events.content.texts import apply_texts
from sm_events.models import Calendar, Event, Redirect
from sm_events.web.endpoints.public import _urls
from sm_events.web.schemas.calendars import CalendarPatch
from sm_events.web.schemas.texts import TextIn

from tests.support.public import seed_public, tenant_header

NOW = datetime(2026, 4, 1, tzinfo=UTC)


def events_of(response) -> list[icalendar.Event]:
    return list(icalendar.Calendar.from_ical(response.content).walk("VEVENT"))


def uids(response) -> set[str]:
    return {str(e["UID"]) for e in events_of(response)}


async def mutate(client, fn):
    async with client.db_state.session_factory() as session:
        out = await fn(session)
        await session.commit()
        return out


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client)


async def test_redirects(public_locales_client, fx):
    async def rename(db):
        cal = await db.get(Calendar, fx.pub.id)
        await calendars.update_calendar(db, cal, CalendarPatch(slug="renamed"))

    await mutate(public_locales_client, rename)
    old = await public_locales_client.get(_urls.calendar_ics_path(fx.pub.slug, "en"))
    assert old.status_code == 301
    assert old.headers["location"] == "/events/c/renamed.ics"
    assert (await public_locales_client.get(old.headers["location"])).status_code == 200

    async def retitle(db):
        event = await db.get(Event, fx.one_off.id)
        await apply_texts(
            db,
            event,
            {"en": TextIn(title="Renamed", slug="brand-new")},
            locales=("en", "de"),
            creating=False,
        )

    await mutate(public_locales_client, retitle)
    moved = await public_locales_client.get(_urls.event_ics_path(fx.slug(fx.one_off), "en"))
    assert moved.status_code == 301 and moved.headers["location"] == "/events/brand-new.ics"
    assert (await public_locales_client.get(moved.headers["location"])).status_code == 200


async def test_redirect_to_hidden_is_404(public_locales_client, fx):
    async def hide(db):
        internal = await db.get(Calendar, fx.internal.id)
        await calendars.update_calendar(db, internal, CalendarPatch(slug="internal-renamed"))
        db.add(Redirect(event_id=fx.draft.id, locale="en", old_slug="was-public"))

    await mutate(public_locales_client, hide)
    for path in (
        _urls.calendar_ics_path(fx.internal.slug, "en"),
        _urls.calendar_ics_path("internal-renamed", "en"),
        _urls.event_ics_path("was-public", "en"),
    ):
        got = await public_locales_client.get(path)
        assert got.status_code == 404, path
        assert got.headers["cache-control"] == "no-store"


@pytest.mark.unbound_tenant
async def test_multi_tenant_feeds_are_private_and_tenant_scoped(public_multi_client):
    mine = await seed_public(public_multi_client, tag="-a", tenant="a")
    theirs = await seed_public(public_multi_client, tag="-b", tenant="b")
    path = _urls.calendar_ics_path(None, "en")
    got = await public_multi_client.get(path, headers=tenant_header("a"))
    assert got.status_code == 200
    assert uids(got) == {e.uid for e in mine.public_events}
    assert not uids(got) & {e.uid for e in theirs.public_events}
    assert got.headers["cache-control"].startswith("private")
    assert "Cookie" in got.headers["vary"]
    nobody = await public_multi_client.get(path)
    assert nobody.status_code == 404 and nobody.headers["cache-control"] == "no-store"
    cross = await public_multi_client.get(
        _urls.calendar_ics_path(theirs.pub.slug, "en"), headers=tenant_header("a")
    )
    assert cross.status_code == 404
