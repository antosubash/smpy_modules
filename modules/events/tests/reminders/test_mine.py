"""\"My reminders\": the caller's own follows on what they can see now; the rest only counted."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.models import EventFollow, EventText
from sm_events.reminders import limits, mine
from sqlalchemy import update

from tests.reminders.support import (
    NOW,
    OTHER,
    SETTINGS,
    VIEW_SHARE,
    U,
    drop_share,
    follow_row,
    published,
    world,
)


async def _page(db, who=U, *, page=1, size=50, locale="en"):
    return await mine.my_reminders(
        db, who, locale=locale, page=page, page_size=size, settings=SETTINGS, now=NOW
    )


async def test_lists_visible_only_and_counts_hidden(db):
    cals = await world(db)
    open_event = await published(db, cals["U"], title="Open day")
    secret = await published(db, cals["P"], title="Secret board")
    for event in (open_event, secret):
        db.add(follow_row(event, user="sv", lead=60))
        db.add(follow_row(event, user="sv", lead=15))
    db.add(follow_row(open_event, user="u", lead=1440))
    await db.flush()
    got = await _page(db, VIEW_SHARE)
    assert got.hidden == 0 and got.total == 2
    assert {i.title for i in got.items} == {"Open day", "Secret board"}
    # The share goes: the follow stays, but the event is counted, never named.
    await drop_share(db, cals["P"], "sv")
    got = await _page(db, VIEW_SHARE)
    assert got.hidden == 1 and got.total == 2  # the hidden one still counts: it is the user's
    assert [i.title for i in got.items] == ["Open day", None]  # visible first, then the opaque row
    opaque = got.items[1]
    assert opaque.hidden is True
    assert (opaque.event_id, opaque.calendar, opaque.lang, opaque.next_start) == (
        None,
        None,
        None,
        None,
    )
    assert opaque.leads == () and opaque.follow_id is not None
    assert "Secret board" not in repr(got)
    assert str(secret.id) not in repr(got)
    item = got.items[0]
    assert item.hidden is False and item.follow_id is not None
    assert item.event_id == open_event.id and item.leads == (15, 60)
    assert (item.calendar.name, item.calendar.color) == (cals["U"].name, cals["U"].color)


async def test_only_the_callers_own_follows(db):
    cals = await world(db)
    event = await published(db, cals["U"])
    db.add(follow_row(event, user="u"))
    await db.flush()
    assert (await _page(db, U)).total == 1
    other = await _page(db, OTHER)
    assert (other.total, other.hidden, other.items) == (0, 0, [])


async def test_unpublished_trashed_and_trashed_calendar_are_hidden(db):
    cals = await world(db)
    draft = await published(db, cals["U"], status="draft")
    gone = await published(db, cals["U"], title="Gone")
    kept = await published(db, cals["U"], title="Kept")
    for event in (draft, gone, kept):
        db.add(follow_row(event))
    await db.flush()
    await db.delete(gone)
    await db.flush()
    got = await _page(db)
    assert [i.title for i in got.items] == ["Kept", None, None] and got.hidden == 2
    assert [i.hidden for i in got.items] == [False, True, True]


async def test_paging_bounds(db):
    cals = await world(db)
    for i in range(5):
        event = await published(db, cals["U"], title=f"E{i}")
        db.add(follow_row(event))
    await db.flush()
    sizes = [len((await _page(db, page=n, size=2)).items) for n in (1, 2, 3, 4)]
    assert sizes == [2, 2, 1, 0]
    got = await _page(db, page=2, size=2)
    assert (got.total, got.page, got.page_size) == (5, 2, 2)
    ids = [i.event_id for n in (1, 2, 3) for i in (await _page(db, page=n, size=2)).items]
    assert len(ids) == len(set(ids)) == 5  # no event twice, none skipped
    # Out-of-range values are clamped, never an unbounded read.
    assert (await _page(db, page=0, size=10_000)).page_size == limits.MINE_PAGE_MAX
    assert (await _page(db, page=-3, size=0)).page == 1
    assert (await _page(db, page=1, size=0)).page_size == 1


async def test_title_fallback(db):
    cals = await world(db)
    both = await published(db, cals["U"], title="English title")
    db.add(EventText(event_id=both.id, locale="de", slug="titel", title="Deutscher Titel"))
    only_fr = await published(db, cals["U"], title="Titre", locale="fr")
    only_en = await published(db, cals["U"], title="Only English")
    for event in (both, only_fr, only_en):
        db.add(follow_row(event))
    await db.flush()

    def titles(got):
        return {i.event_id: (i.title, i.lang) for i in got.items}

    de = titles(await _page(db, locale="de"))
    assert de[both.id] == ("Deutscher Titel", "de")
    assert de[only_en.id] == ("Only English", "en")  # no German: the default content locale
    assert de[only_fr.id] == ("Titre", "fr")  # neither: the first text there is
    en = titles(await _page(db, locale="en"))
    assert en[both.id] == ("English title", "en")


async def test_next_start_for_a_one_off(db):
    cals = await world(db)
    soon = await published(db, cals["U"], starts_at=NOW + timedelta(days=2))
    past = await published(db, cals["U"], title="Over", starts_at=NOW - timedelta(days=2))
    for event in (soon, past):
        db.add(follow_row(event))
    await db.flush()
    got = {i.event_id: i.next_start for i in (await _page(db)).items}
    assert got[soon.id] == soon.starts_at
    assert got[past.id] is None


async def test_follow_rows_are_not_loaded_across_users(db):
    cals = await world(db)
    event = await published(db, cals["U"])
    db.add(follow_row(event, user="u", lead=60))
    db.add(follow_row(event, user="w", lead=15))
    await db.flush()
    await db.execute(update(EventFollow).values(locale="de"))
    got = await _page(db, U)
    assert got.items[0].leads == (60,)


async def test_next_start_for_a_series_and_a_yearly_one(db):
    from tests.support.calendars import seed_series

    cals = await world(db)
    weekly = await seed_series(
        db, cals["U"], "FREQ=WEEKLY", "2026-06-24T10:00", "2026-06-24T11:00", tz="UTC",
        status="published", title="Weekly",
    )  # fmt: skip
    yearly = await seed_series(
        db, cals["U"], "FREQ=YEARLY", "2025-12-24T10:00", "2025-12-24T11:00", tz="UTC",
        status="published", title="Xmas",
    )  # fmt: skip
    for event in (weekly, yearly):
        db.add(follow_row(event))
    await db.flush()
    got = {i.title: i.next_start for i in (await _page(db)).items}
    assert got["Weekly"] == datetime(2026, 7, 1, 10, tzinfo=UTC)
    assert got["Xmas"] == datetime(2026, 12, 24, 10, tzinfo=UTC)


async def test_hidden_rows_page_after_the_visible_ones(db):
    cals = await world(db)
    hidden = [await published(db, cals["P"], title=f"H{i}") for i in range(3)]
    shown = [await published(db, cals["U"], title=f"S{i}") for i in range(3)]
    for event in hidden + shown:
        db.add(follow_row(event, user="w"))
    await db.flush()
    pages = [await _page(db, OTHER, page=n, size=2) for n in (1, 2, 3)]
    assert [[i.hidden for i in p.items] for p in pages] == [
        [False, False],
        [False, True],
        [True, True],
    ]
    assert all(p.total == 6 and p.hidden == 3 for p in pages)
    handles = [i.follow_id for p in pages for i in p.items]
    assert len(set(handles)) == 6


async def test_delete_by_follow_id_removes_the_whole_event_for_the_owner_only(db):
    from sm_events.core.errors import NotFound
    from sm_events.reminders import follows

    cals = await world(db)
    event = await published(db, cals["U"], title="Open")
    for lead in (15, 60):
        db.add(follow_row(event, user="u", lead=lead))
    db.add(follow_row(event, user="w", lead=60))
    await db.flush()
    page = await _page(db)
    handle = page.items[0].follow_id
    with pytest.raises(NotFound) as other:  # someone else's follow id: the missing-id answer
        await follows.delete_follow_by_id(db, OTHER, handle)
    with pytest.raises(NotFound) as missing:
        await follows.delete_follow_by_id(db, OTHER, uuid.uuid4())
    assert (other.value.code, other.value.detail) == (missing.value.code, missing.value.detail)
    assert (await _page(db)).total == 1 and (await _page(db, OTHER)).total == 1
    await follows.delete_follow_by_id(db, U, handle)
    assert (await _page(db)).total == 0  # both leads went
    assert (await _page(db, OTHER)).total == 1  # the other user's follow did not
    with pytest.raises(NotFound):
        await follows.delete_follow_by_id(db, U, handle)


async def test_a_hidden_follow_can_be_removed_and_frees_the_cap(db):
    from sm_events.reminders import follows

    cals = await world(db)
    secret = await published(db, cals["P"], title="Secret")
    db.add(follow_row(secret, user="w"))
    await db.flush()
    (row,) = (await _page(db, OTHER)).items
    assert row.hidden
    await follows.delete_follow_by_id(db, OTHER, row.follow_id)
    assert (await _page(db, OTHER)).total == 0
