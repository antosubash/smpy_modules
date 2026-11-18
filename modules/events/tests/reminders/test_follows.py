"""Following an event: who may, how many, and that it is only ever one user's own."""

from __future__ import annotations

import pytest
from sm_events.core.errors import NotFound
from sm_events.core.errors_reminders import NotPublished
from sm_events.core.tenancy import tenant_scope
from sm_events.models import EventFollow
from sm_events.reminders import follows
from sqlalchemy import delete, func, select

from tests.reminders.support import (
    ANON,
    EDIT_SHARE,
    NO_VIEW,
    NOW,
    OTHER,
    SETTINGS,
    STRANGER,
    VIEW_SHARE,
    U,
    drop_share,
    published,
    world,
)
from tests.support.calendars import seed_event


async def _set(db, who, event, leads, locale="en"):
    return await follows.set_follow(
        db, who, event.id, leads, locale=locale, settings=SETTINGS, now=NOW
    )


async def _rows(db, user="u"):
    got = await db.execute(select(EventFollow).where(EventFollow.user_id == user))
    return sorted((r.event_id.hex, r.lead_minutes) for r in got.scalars())


async def test_follow_and_replace_leads(db):
    cals = await world(db)
    event = await published(db, cals["I"])
    state = await _set(db, U, event, [60, 15])
    assert state.leads == (15, 60)
    assert await _rows(db) == sorted([(event.id.hex, 15), (event.id.hex, 60)])
    state = await _set(db, U, event, [1440, 60])
    assert state.leads == (60, 1440)
    assert await _rows(db) == sorted([(event.id.hex, 60), (event.id.hex, 1440)])
    again = await follows.get_follow(db, U, event.id, settings=SETTINGS, now=NOW)
    assert again.leads == (60, 1440)


async def test_empty_set_unfollows(db):
    cals = await world(db)
    event = await published(db, cals["I"])
    await _set(db, U, event, [60])
    state = await _set(db, U, event, [])
    assert state.leads == ()
    assert await _rows(db) == []


async def test_get_when_not_following_is_empty_with_defaults(db):
    cals = await world(db)
    event = await published(db, cals["I"])
    state = await follows.get_follow(db, U, event.id, settings=SETTINGS, now=NOW)
    assert state.leads == () and state.defaults == (60,) and state.next_due == {}


@pytest.mark.parametrize("who", [STRANGER, ANON, NO_VIEW])
async def test_invisible_is_404_and_writes_nothing(db, who):
    cals = await world(db)
    event = await published(db, cals["P"])  # private: only the owner, shares and managers
    for call in (
        lambda: _set(db, who, event, [60]),
        lambda: follows.get_follow(db, who, event.id, settings=SETTINGS, now=NOW),
        lambda: follows.delete_follow(db, who, event.id),
    ):
        with pytest.raises(NotFound):
            await call()
    assert (await db.execute(select(func.count()).select_from(EventFollow))).scalar_one() == 0


@pytest.mark.unbound_tenant
async def test_another_tenants_event_is_404(db):
    with tenant_scope("a"):
        cals = await world(db)
        event = await published(db, cals["U"])
        await db.flush()
    with tenant_scope("b"):
        with pytest.raises(NotFound):
            await _set(db, U, event, [60])
        with pytest.raises(NotFound):
            await follows.delete_follow(db, U, event.id)
    with tenant_scope("a"):
        assert await _rows(db) == []


async def test_missing_event_is_the_same_404(db):
    import uuid

    with pytest.raises(NotFound) as missing:
        await follows.set_follow(db, U, uuid.uuid4(), [60], locale="en", settings=SETTINGS, now=NOW)
    cals = await world(db)
    event = await published(db, cals["P"])
    with pytest.raises(NotFound) as hidden:
        await _set(db, STRANGER, event, [60])
    assert (missing.value.code, missing.value.detail) == (hidden.value.code, hidden.value.detail)


async def test_draft_for_writer_is_not_published(db):
    cals = await world(db)
    draft = await seed_event(db, cals["P"], status="draft")
    with pytest.raises(NotPublished):
        await _set(db, EDIT_SHARE, draft, [60])


async def test_draft_for_viewer_is_404(db):
    cals = await world(db)
    draft = await seed_event(db, cals["P"], status="draft")
    with pytest.raises(NotFound):
        await _set(db, VIEW_SHARE, draft, [60])
    with pytest.raises(NotFound):
        await _set(db, U, await seed_event(db, cals["I"], status="draft"), [60])


async def test_trashed_event_is_404(db):
    cals = await world(db)
    event = await published(db, cals["U"])
    await db.delete(event)
    await db.flush()
    with pytest.raises(NotFound):
        await _set(db, U, event, [60])


async def test_trashed_calendar_is_404(db):
    cals = await world(db)
    event = await published(db, cals["U"])
    await db.delete(cals["U"])
    await db.flush()
    with pytest.raises(NotFound):
        await _set(db, U, event, [60])


async def test_needs_events_view(db):
    """The owner of a private calendar, without ``events.view``, is an anonymous reader."""
    cals = await world(db)
    event = await published(db, cals["P"])
    with pytest.raises(NotFound):
        await _set(db, NO_VIEW, event, [60])
    # A public calendar's published event is readable without it, but still not followable.
    public = await published(db, cals["U"])
    with pytest.raises(NotFound):
        await _set(db, NO_VIEW, public, [60])


async def test_locale_recorded_and_refreshed(db):
    cals = await world(db)
    event = await published(db, cals["U"])
    await _set(db, U, event, [60, 15], locale="de")
    rows = (await db.execute(select(EventFollow))).scalars().all()
    assert {r.locale for r in rows} == {"de"}
    await _set(db, U, event, [60, 15], locale="en")
    db.expire_all()
    rows = (await db.execute(select(EventFollow))).scalars().all()
    assert {r.locale for r in rows} == {"en"}


async def test_defaults_from_calendar(db):
    cals = await world(db)
    cals["U"].default_reminder_minutes = [15, 1440]
    event = await published(db, cals["U"])
    other = await published(db, cals["I"])
    await db.flush()
    assert (await _set(db, U, event, [60])).defaults == (15, 1440)
    assert (await _set(db, U, other, [60])).defaults == (60,)


async def test_follows_are_personal(db):
    """One user's follow is invisible to, unchanged by and undeletable by another."""
    cals = await world(db)
    event = await published(db, cals["U"])
    await _set(db, U, event, [60])
    assert (await follows.get_follow(db, OTHER, event.id, settings=SETTINGS, now=NOW)).leads == ()
    await follows.delete_follow(db, OTHER, event.id)
    await _set(db, OTHER, event, [15])
    await _set(db, OTHER, event, [])
    assert await _rows(db, "u") == [(event.id.hex, 60)]
    assert await _rows(db, "w") == []
    # A manager has no special view of someone else's follows either.
    from tests.reminders.support import MANAGER

    assert (await follows.get_follow(db, MANAGER, event.id, settings=SETTINGS, now=NOW)).leads == ()


async def test_delete_is_idempotent_and_survives_lost_access(db):
    cals = await world(db)
    event = await published(db, cals["P"])
    await _set(db, VIEW_SHARE, event, [60])
    # Losing the share keeps the follow (a re-grant resumes) but the user can still remove it.
    await drop_share(db, cals["P"], "sv")
    assert await _rows(db, "sv") == [(event.id.hex, 60)]
    await follows.delete_follow(db, VIEW_SHARE, event.id)
    assert await _rows(db, "sv") == []
    # Nothing left: now it is the plain "cannot see it" 404.
    with pytest.raises(NotFound):
        await follows.delete_follow(db, VIEW_SHARE, event.id)
    # Idempotent on something visible and not followed.
    public = await published(db, cals["U"])
    await follows.delete_follow(db, U, public.id)
    await follows.delete_follow(db, U, public.id)


async def test_no_next_due_until_the_due_maths_lands(db):
    cals = await world(db)
    event = await published(db, cals["U"])
    state = await _set(db, U, event, [60, 15])
    assert state.next_due == {15: None, 60: None}


async def test_hard_delete_of_the_event_removes_follows(db):
    cals = await world(db)
    event = await published(db, cals["U"])
    await _set(db, U, event, [60])
    event_id = event.id
    await db.execute(
        delete(type(event).__table__).where(  # type: ignore[arg-type]
            type(event).__table__.c.id == event_id, type(event).__table__.c.tenant_id == "default"
        )
    )
    assert await _rows(db) == []
