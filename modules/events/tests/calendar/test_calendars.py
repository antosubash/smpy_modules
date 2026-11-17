"""The calendar service: create, edit, visibility, trash and restore."""

from __future__ import annotations

import pytest
from sm_events.calendar import calendars
from sm_events.core.errors import NotFound, OwnerRequired, SlugTaken
from sm_events.models import Visibility
from sm_events.web.schemas.calendars import CalendarCreate, CalendarPatch

from tests.support.access import principal

V, E, M = "events.view", "events.edit", "events.manage"


def _who(uid="o", *perms):
    return principal(uid, *(perms or (V, E)))


async def test_create_owner_and_defaults(db):
    cal = await calendars.create_calendar(
        db, _who(), CalendarCreate(name="Team"), default_tz="Europe/Vienna"
    )
    assert cal.owner_id == "o"
    assert cal.visibility == Visibility.PRIVATE
    assert cal.color == "#2563eb"
    assert cal.default_timezone == "Europe/Vienna"
    assert cal.slug == "team"


async def test_unknown_default_timezone_falls_back_to_utc(db):
    cal = await calendars.create_calendar(db, _who(), CalendarCreate(name="T"), default_tz="Mars/X")
    assert cal.default_timezone == "UTC"


async def test_slug_derived_and_deduplicated(db):
    first = await calendars.create_calendar(
        db, _who(), CalendarCreate(name="Team"), default_tz="UTC"
    )
    second = await calendars.create_calendar(
        db, _who(), CalendarCreate(name="Team"), default_tz="UTC"
    )
    assert (first.slug, second.slug) == ("team", "team-2")


async def test_slug_held_by_trashed_calendar_is_taken(db):
    cal = await calendars.create_calendar(db, _who(), CalendarCreate(name="Team"), default_tz="UTC")
    await calendars.trash_calendar(db, cal, _who())
    with pytest.raises(SlugTaken):
        await calendars.create_calendar(
            db, _who(), CalendarCreate(name="Other", slug="team"), default_tz="UTC"
        )


async def test_slug_race_is_conflict(db, monkeypatch):
    await calendars.create_calendar(db, _who(), CalendarCreate(name="Team"), default_tz="UTC")

    async def free(*_a, **_k):
        return False

    monkeypatch.setattr(calendars, "_slug_taken", free)
    with pytest.raises(SlugTaken):
        await calendars.create_calendar(
            db, _who(), CalendarCreate(name="Other", slug="team"), default_tz="UTC"
        )
    # The savepoint kept the session usable.
    assert [c.slug for c in await calendars.list_calendars(db, _who())] == ["team"]


async def test_update_changes_only_the_fields_set(db):
    cal = await calendars.create_calendar(
        db, _who(), CalendarCreate(name="Team", color="#112233"), default_tz="UTC"
    )
    await calendars.update_calendar(db, cal, CalendarPatch(name="Crew"))
    assert (cal.name, cal.color, cal.slug) == ("Crew", "#112233", "team")
    await calendars.update_calendar(db, cal, CalendarPatch(description=None, slug="crew"))
    assert (cal.description, cal.slug) == (None, "crew")


async def test_renaming_to_a_taken_slug_is_conflict(db):
    await calendars.create_calendar(db, _who(), CalendarCreate(name="A"), default_tz="UTC")
    b = await calendars.create_calendar(db, _who(), CalendarCreate(name="B"), default_tz="UTC")
    with pytest.raises(SlugTaken):
        await calendars.update_calendar(db, b, CalendarPatch(slug="a"))


async def test_set_visibility(db):
    cal = await calendars.create_calendar(db, _who(), CalendarCreate(name="T"), default_tz="UTC")
    await calendars.set_visibility(db, cal, Visibility.PUBLIC)
    assert cal.visibility == "public"


async def test_restore_round_trip(db):
    cal = await calendars.create_calendar(db, _who(), CalendarCreate(name="T"), default_tz="UTC")
    await calendars.trash_calendar(db, cal, _who())
    assert await calendars.list_calendars(db, _who()) == []
    (trashed,) = await calendars.list_calendars(db, _who(), trashed=True)
    assert trashed.id == cal.id and trashed.deleted_at is not None
    restored = await calendars.restore_calendar(db, _who(), cal.id)
    assert restored.is_deleted is False and restored.deleted_at is None
    assert [c.id for c in await calendars.list_calendars(db, _who())] == [cal.id]


async def test_restore_refusals(db):
    cal = await calendars.create_calendar(db, _who(), CalendarCreate(name="T"), default_tz="UTC")
    # Not deleted: nothing to restore.
    with pytest.raises(NotFound):
        await calendars.restore_calendar(db, _who(), cal.id)
    await calendars.trash_calendar(db, cal, _who())
    # A trashed private calendar does not exist for a stranger.
    with pytest.raises(NotFound):
        await calendars.restore_calendar(db, _who("x", V), cal.id)
    # A manager may.
    assert (await calendars.restore_calendar(db, _who("m", M), cal.id)).id == cal.id


async def test_list_trashed_only_own_or_manage(db):
    mine = await calendars.create_calendar(
        db, _who("o"), CalendarCreate(name="Mine"), default_tz="UTC"
    )
    other = await calendars.create_calendar(
        db, _who("x"), CalendarCreate(name="Other"), default_tz="UTC"
    )
    await calendars.trash_calendar(db, mine, _who("o"))
    await calendars.trash_calendar(db, other, _who("x"))
    assert [c.id for c in await calendars.list_calendars(db, _who("o"), trashed=True)] == [mine.id]
    both = await calendars.list_calendars(db, _who("m", M), trashed=True)
    assert {c.id for c in both} == {mine.id, other.id}
    assert await calendars.list_calendars(db, _who("v", V), trashed=True) == []


async def test_restore_of_a_visible_trashed_calendar_needs_the_owner(db):
    cal = await calendars.create_calendar(db, _who(), CalendarCreate(name="T"), default_tz="UTC")
    await calendars.set_visibility(db, cal, Visibility.PUBLIC)
    await calendars.trash_calendar(db, cal, _who())
    with pytest.raises(OwnerRequired):
        await calendars.restore_calendar(db, _who("x", V), cal.id)
