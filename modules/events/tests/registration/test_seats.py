"""Seats: admit under the capacity, and what an occurrence does to its seats."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.models.enums import Visibility
from sm_events.registration.seats import (
    Admission,
    admit,
)

from tests.registration.seat_helpers import PROVIDER, free, rows, take
from tests.registration.support import (
    NOW,
    SECOND_KEY,
    START,
    consistent,
    moved,
    one_off,
    override,
    series,
)
from tests.support.providers import KNOWN_TARGET


async def test_admit_until_full(db, cal):
    event = await one_off(db, cal, registration_capacity=2)
    assert await take(db, event, "h1") == Admission(True, None, None)
    assert (await take(db, event, "h2")).admitted
    third = await take(db, event, "h3")
    assert (third.admitted, third.code, third.event) == (False, "registration_full", None)
    assert [r.holder for r in await rows(db)] == ["h1", "h2"]  # no seat left behind
    assert await consistent(db) == {(event.id, str(event.id)): 2}


async def test_unlimited_counts_but_never_refuses(db, cal):
    event = await one_off(db, cal)
    for n in range(5):
        assert (await take(db, event, f"h{n}")).admitted
    assert await consistent(db) == {(event.id, str(event.id)): 5}


async def test_admit_idempotent(db, cal):
    event = await one_off(db, cal, registration_capacity=1)
    assert (await take(db, event, "h1")).admitted
    again = await take(db, event, "h1")
    assert again.admitted and again.code is None
    assert len(await rows(db)) == 1 and await consistent(db) == {(event.id, str(event.id)): 1}
    assert not (await take(db, event, "h2")).admitted  # the one seat is still taken


async def test_a_holder_has_one_seat_anywhere(db, cal):
    """The seat is keyed by ``(tenant, provider, holder)``: a holder already seated elsewhere is
    not admitted a second time, and nothing moves."""
    first = await one_off(db, cal)
    other = await one_off(db, cal, title="Other")
    assert (await take(db, first, "h1")).admitted
    got = await take(db, other, "h1")
    assert (got.admitted, got.code) == (False, "event_unavailable")
    assert [r.event_id for r in await rows(db)] == [first.id]
    await consistent(db)


async def test_holder_spellings_are_one_holder(db, cal):
    event = await one_off(db, cal, registration_capacity=5)
    holder = str(uuid.uuid4())
    assert (await take(db, event, holder.upper())).admitted
    assert (await take(db, event, holder)).admitted
    assert len(await rows(db)) == 1
    assert await free(db, holder.upper()) == 1
    assert await rows(db) == []


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"status": "draft"}, "event_unavailable"),
        ({"is_deleted": True}, "event_unavailable"),
        (
            {"registration_mode": "external", "registration_url": "https://x.example/"},
            "event_unavailable",
        ),
        ({"cancelled": True}, "registration_closed"),
        ({"registration_opens_at": NOW + timedelta(hours=1)}, "registration_closed"),
        ({"registration_closes_at": NOW - timedelta(hours=1)}, "registration_closed"),
    ],
)  # fmt: skip
async def test_admit_refusals(db, cal, fields, code):
    event = await one_off(db, cal, **fields)
    got = await take(db, event, "h1")
    assert (got.admitted, got.code) == (False, code)
    assert await rows(db) == [] and await consistent(db) == {}


async def test_closed_once_the_occurrence_has_started(db, cal):
    event = await one_off(db, cal)
    assert (await take(db, event, "h1", now=START - timedelta(seconds=1))).admitted
    got = await take(db, event, "h2", now=START)
    assert (got.admitted, got.code) == (False, "registration_closed")


async def test_wrong_provider_or_target_is_unavailable(db, cal):
    event = await one_off(db, cal)
    for kw in ({"provider": "other:registration"}, {"target": "another-form"}):
        got = await take(db, event, "h1", **kw)
        assert (got.admitted, got.code) == (False, "event_unavailable")
    unknown = await admit(
        db,
        tenant_id="default",
        event_id=uuid.uuid4(),
        occurrence_key=str(uuid.uuid4()),
        provider=PROVIDER,
        target=KNOWN_TARGET,
        holder="h1",
    )
    assert (unknown.admitted, unknown.code) == (False, "event_unavailable")


async def test_admin_skips_the_window_but_not_capacity_or_availability(db, cal):
    event = await one_off(
        db, cal, registration_capacity=1, registration_closes_at=NOW - timedelta(hours=1)
    )
    assert (await take(db, event, "h1")).code == "registration_closed"
    assert (await take(db, event, "h1", admin=True)).admitted
    full = await take(db, event, "h2", admin=True)
    assert (full.admitted, full.code) == (False, "registration_full")
    started = await take(db, event, "h3", admin=True, now=START + timedelta(hours=1))
    assert started.code == "registration_full"
    event.cancelled = True  # a cancelled occurrence is not available to anyone
    await db.flush()
    cancelled = await take(db, event, "h4", admin=True)
    assert (cancelled.admitted, cancelled.code) == (False, "registration_closed")
    event.status = "draft"
    await db.flush()
    assert (await take(db, event, "h5", admin=True)).code == "event_unavailable"
    await consistent(db)


async def test_capacity_lowered_never_evicts(db, cal):
    event = await one_off(db, cal, registration_capacity=3)
    for holder in ("h1", "h2", "h3"):
        assert (await take(db, event, holder)).admitted
    event.registration_capacity = 1
    await db.flush()
    assert (await take(db, event, "h4")).code == "registration_full"
    assert len(await rows(db)) == 3  # nobody was removed
    key = (event.id, str(event.id))
    assert await free(db, "h1") == 1
    assert (await take(db, event, "h4")).code == "registration_full"  # 2 taken, capacity 1
    assert await free(db, "h2") == 1
    assert (await take(db, event, "h4")).code == "registration_full"  # 1 taken, capacity 1
    assert await free(db, "h3") == 1
    assert (await take(db, event, "h4")).admitted
    assert await consistent(db) == {key: 1}


async def test_capacity_raised_frees_room(db, cal):
    event = await one_off(db, cal, registration_capacity=1)
    await take(db, event, "h1")
    assert (await take(db, event, "h2")).code == "registration_full"
    event.registration_capacity = 2
    await db.flush()
    assert (await take(db, event, "h2")).admitted


async def test_each_occurrence_of_a_series_has_its_own_seats(db, cal):
    event = await series(db, cal, registration_capacity=1)
    first, second = SECOND_KEY.format(id=event.id), f"{event.id}:20260715T080000Z"
    assert (await take(db, event, "h1", first)).admitted
    assert (await take(db, event, "h2", first)).code == "registration_full"
    assert (await take(db, event, "h3", second)).admitted
    assert await consistent(db) == {(event.id, first): 1, (event.id, second): 1}


async def test_a_moved_occurrence_keeps_its_seats(db, cal):
    event = await series(db, cal, registration_capacity=1)
    key = SECOND_KEY.format(id=event.id)
    assert (await take(db, event, "h1", key)).admitted
    await moved(db, event, datetime(2026, 7, 9, 12, tzinfo=UTC))
    assert (await take(db, event, "h2", key)).code == "registration_full"  # same key, same seats
    assert [r.occurrence_key for r in await rows(db)] == [key]


async def test_a_cancelled_occurrence_freezes_its_seats(db, cal):
    event = await series(db, cal, registration_capacity=2)
    key = SECOND_KEY.format(id=event.id)
    assert (await take(db, event, "h1", key)).admitted
    row = await override(db, event, "cancelled")
    got = await take(db, event, "h2", key)
    assert (got.admitted, got.code) == (False, "registration_closed")
    assert len(await rows(db)) == 1  # kept
    assert await free(db, "h1") == 1  # and a registrant can still leave
    await db.delete(row)
    await db.flush()
    assert (await take(db, event, "h2", key)).admitted  # reinstating resumes


async def test_a_skipped_occurrence_is_unavailable_and_keeps_its_seats(db, cal):
    event = await series(db, cal)
    key = SECOND_KEY.format(id=event.id)
    await take(db, event, "h1", key)
    await override(db, event, "skipped")
    assert (await take(db, event, "h2", key)).code == "event_unavailable"
    assert len(await rows(db)) == 1


async def test_unpublish_trash_and_restore_keep_the_seats(db, cal):
    event = await one_off(db, cal, registration_capacity=2)
    await take(db, event, "h1")
    for attr, off, on in (("status", "draft", "published"), ("is_deleted", True, False)):
        setattr(event, attr, off)
        await db.flush()
        assert (await take(db, event, "h2")).code == "event_unavailable"
        assert len(await rows(db)) == 1
        setattr(event, attr, on)
        await db.flush()
    cal.visibility = Visibility.INTERNAL  # the calendar stops being public
    await db.flush()
    assert (await take(db, event, "h2")).code == "event_unavailable"
    cal.visibility = Visibility.PUBLIC
    await db.flush()
    assert (await take(db, event, "h2")).admitted
    await consistent(db)
