"""Seats: release exactly, a counter that is the seats' count, and the reads."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from simple_module_db.listeners import SESSION_HAS_WRITES_KEY
from sm_events.core import constants
from sm_events.models import RegistrationCount
from sm_events.registration.seats import (
    SeatRef,
    counts,
    release_target,
    seat_holders,
)
from sqlalchemy import select

from tests.registration.seat_helpers import PROVIDER, free, rows, take
from tests.registration.support import (
    NOW,
    SECOND_KEY,
    consistent,
    one_off,
    series,
)
from tests.support.providers import KNOWN_TARGET


async def test_release_is_exact(db, cal):
    event = await one_off(db, cal, registration_capacity=5)
    for holder in ("h1", "h2", "h3"):
        await take(db, event, holder)
    assert await free(db, "h2") == 1
    assert await free(db, "h2") == 0  # twice: nothing more is freed
    assert await free(db, "never-held") == 0
    assert await consistent(db) == {(event.id, str(event.id)): 2}
    assert [r.holder for r in await rows(db)] == ["h1", "h3"]
    assert await free(db, "h1", "h1", "h3", "nope") == 2
    assert await consistent(db) == {(event.id, str(event.id)): 0}


async def test_release_cannot_free_a_seat_of_another_provider(db, cal):
    event = await one_off(db, cal)
    await take(db, event, "h1")
    assert await free(db, "h1", provider="other:registration") == 0
    assert len(await rows(db)) == 1
    await consistent(db)


async def test_release_target(db, cal):
    one = await one_off(db, cal, registration_capacity=5)
    two = await one_off(db, cal, title="Two", registration_target="another-form")
    for holder in ("h1", "h2"):
        await take(db, one, holder)
    await take(db, two, "h3", target="another-form")
    got = await release_target(db, tenant_id="default", provider=PROVIDER, target=KNOWN_TARGET)
    assert got == 2
    assert [r.holder for r in await rows(db)] == ["h3"]
    assert await consistent(db) == {(one.id, str(one.id)): 0, (two.id, str(two.id)): 1}
    assert (
        await release_target(db, tenant_id="default", provider=PROVIDER, target=KNOWN_TARGET) == 0
    )


async def test_release_target_spans_occurrences(db, cal):
    event = await series(db, cal)
    first, second = SECOND_KEY.format(id=event.id), f"{event.id}:20260715T080000Z"
    await take(db, event, "h1", first)
    await take(db, event, "h2", second)
    assert (
        await release_target(db, tenant_id="default", provider=PROVIDER, target=KNOWN_TARGET) == 2
    )
    assert await consistent(db) == {(event.id, first): 0, (event.id, second): 0}


async def test_the_counter_heals_when_it_drifted(db, cal):
    event = await one_off(db, cal, registration_capacity=5)
    key = (event.id, str(event.id))
    await take(db, event, "h1")
    await take(db, event, "h2")
    counter = (await db.execute(select(RegistrationCount))).scalars().one()
    counter.taken = 99  # whatever put it out of step
    await db.flush()
    await free(db, "h1")
    assert await consistent(db) == {key: 1}


async def test_never_commits_and_flags_the_session(db, cal):
    event = await one_off(db, cal, registration_capacity=5)
    await db.commit()
    await take(db, event, "h1")
    assert db.in_transaction() and db.info.get(SESSION_HAS_WRITES_KEY) is True
    await db.rollback()
    assert await rows(db) == [] and await consistent(db) == {}


async def test_a_released_seat_is_gone_after_a_rollback_too(db, cal):
    event = await one_off(db, cal)
    key = (event.id, str(event.id))
    await take(db, event, "h1")
    await db.commit()
    assert await free(db, "h1") == 1
    await db.rollback()
    assert [r.holder for r in await rows(db)] == ["h1"]
    assert await consistent(db) == {key: 1}


async def test_seat_holders_pages(db, cal):
    event = await one_off(db, cal)
    for n in range(7):
        await take(db, event, f"h{n}")
    other = await take(db, event, "z", provider="other:registration")  # not that provider's
    assert other.code == "event_unavailable"
    seen, after = [], None
    for expected in (3, 3, 1):
        page = await seat_holders(db, tenant_id="default", provider=PROVIDER, after=after, limit=3)
        assert len(page) == expected and all(isinstance(p, SeatRef) for p in page)
        seen += [p.holder for p in page]
        after = page[-1].holder
    assert seen == [f"h{n}" for n in range(7)]
    assert (
        await seat_holders(db, tenant_id="default", provider=PROVIDER, after=after, limit=3) == []
    )
    first = (await seat_holders(db, tenant_id="default", provider=PROVIDER, after=None, limit=1))[0]
    assert first == SeatRef("h0", event.id, str(event.id))


async def test_counts(db, cal):
    event = await series(db, cal, registration_capacity=5)
    keys = [f"{event.id}:2026071{n}T080000Z" for n in (5,)] + [SECOND_KEY.format(id=event.id)]
    await take(db, event, "h1", keys[1])
    await take(db, event, "h2", keys[1])
    await take(db, event, "h3", keys[0])
    assert await counts(db, tenant_id="default", event_id=event.id) == [
        (keys[1], 2),
        (keys[0], 1),
    ]
    assert await counts(db, tenant_id="default", event_id=uuid.uuid4()) == []
    await free(db, "h3")
    assert await counts(db, tenant_id="default", event_id=event.id) == [
        (keys[1], 2)
    ]  # none: omitted


async def test_counts_are_bounded(db, cal):
    event = await series(db, cal, rule="FREQ=DAILY")
    base = datetime(2026, 7, 1, 8, tzinfo=UTC)
    for n in range(constants.REGISTRATION_COUNTS_MAX + 5):
        stamp = (base + timedelta(days=n)).strftime("%Y%m%dT%H%M%SZ")
        await take(db, event, f"h{n}", f"{event.id}:{stamp}", now=NOW - timedelta(days=1))
    got = await counts(db, tenant_id="default", event_id=event.id)
    assert len(got) == constants.REGISTRATION_COUNTS_MAX
