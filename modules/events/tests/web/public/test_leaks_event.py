"""Leak rules that need a row to change state: redirects and validators across an unpublish."""

from __future__ import annotations

import pytest
from sm_events.calendar import calendars
from sm_events.models import Calendar, Event, Redirect
from sm_events.web.schemas.calendars import CalendarPatch

from tests.support.public import INERTIA, seed_public


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client)


async def mutate(client, fn):
    async with client.db_state.session_factory() as session:
        out = await fn(session)
        await session.commit()
        return out


async def test_redirect_to_hidden_event_is_404(public_locales_client, fx):
    """An old slug whose event is a draft, internal or trashed answers like a slug that never
    existed: a 301 would publish the draft's current slug."""

    async def point(db):
        for event, old in (
            (fx.draft, "was-draft"),
            (fx.internal_event, "was-internal"),
            (fx.trashed, "was-trashed"),
            (fx.gone_event, "was-gone"),
        ):
            db.add(Redirect(event_id=event.id, locale="en", old_slug=old))

    await mutate(public_locales_client, point)
    missing = await public_locales_client.get("/events/never-was", headers=INERTIA)
    for old in ("was-draft", "was-internal", "was-trashed", "was-gone"):
        for headers in (INERTIA, {}):
            got = await public_locales_client.get(f"/events/{old}", headers=headers)
            assert got.status_code == 404, old
            assert got.headers["cache-control"] == "no-store" and "location" not in got.headers
        got = await public_locales_client.get(f"/events/{old}", headers=INERTIA)
        assert got.json()["props"] == missing.json()["props"]


async def test_redirect_to_hidden_calendar_is_404(public_locales_client, fx):
    async def rename(db):
        for cal in (fx.internal, fx.private):
            row = await db.get(Calendar, cal.id)
            await calendars.update_calendar(db, row, CalendarPatch(slug=f"{cal.slug}-renamed"))

    await mutate(public_locales_client, rename)
    for old in (fx.internal.slug, fx.private.slug):
        got = await public_locales_client.get(f"/events/c/{old}", headers=INERTIA)
        assert got.status_code == 404 and "location" not in got.headers


async def test_a_tag_from_while_public_is_a_404_after_unpublishing(public_locales_client, fx):
    path = f"/events/{fx.slug(fx.one_off)}"
    tag = (await public_locales_client.get(path, headers=INERTIA)).headers["etag"]
    assert (
        await public_locales_client.get(path, headers=INERTIA | {"If-None-Match": tag})
    ).status_code == 304

    async def unpublish(db):
        (await db.get(Event, fx.one_off.id)).status = "draft"

    await mutate(public_locales_client, unpublish)
    for sent in (tag, "*"):
        got = await public_locales_client.get(path, headers=INERTIA | {"If-None-Match": sent})
        assert got.status_code == 404, sent
        assert "etag" not in got.headers


async def test_a_trashed_event_tag_is_a_404(public_locales_client, fx):
    path = f"/events/{fx.slug(fx.one_off)}"
    tag = (await public_locales_client.get(path, headers=INERTIA)).headers["etag"]

    async def trash(db):
        await db.delete(await db.get(Event, fx.one_off.id))

    await mutate(public_locales_client, trash)
    got = await public_locales_client.get(path, headers=INERTIA | {"If-None-Match": tag})
    assert got.status_code == 404


async def test_a_calendar_made_internal_hides_its_events_and_validators(public_locales_client, fx):
    path = f"/events/{fx.slug(fx.conf)}"
    tag = (await public_locales_client.get(path, headers=INERTIA)).headers["etag"]

    async def hide(db):
        (await db.get(Calendar, fx.pub.id)).visibility = "internal"

    await mutate(public_locales_client, hide)
    for url in (path, f"/events/{fx.slug(fx.talk)}", f"/events/c/{fx.pub.slug}"):
        got = await public_locales_client.get(url, headers=INERTIA | {"If-None-Match": tag})
        assert got.status_code == 404, url
