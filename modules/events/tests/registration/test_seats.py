"""Seats: admit under the capacity, release exactly, and a counter that is the seats' count."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db.listeners import SESSION_HAS_WRITES_KEY, TenantIsolationError
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, RegistrationCount, RegistrationSeat
from sm_events.models.enums import Visibility
from sm_events.registration.seats import (
    Admission,
    SeatRef,
    admit,
    counts,
    release,
    release_target,
    seat_holders,
)
from sqlalchemy import select

from tests.registration.support import (
    NOW,
    SECOND_KEY,
    START,
    consistent,
    moved,
    one_off,
    override,
    public_calendar,
    series,
)
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

PROVIDER = PROVIDER_ID


async def take(db, event, holder, key=None, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("provider", PROVIDER)
    kw.setdefault("target", KNOWN_TARGET)
    return await admit(
        db,
        tenant_id="default",
        event_id=event.id,
        occurrence_key=key or str(event.id),
        holder=holder,
        **kw,
    )


async def free(db, *holders, provider=PROVIDER):
    return await release(db, tenant_id="default", provider=provider, holders=list(holders))


async def rows(db):
    return (
        (await db.execute(select(RegistrationSeat).order_by(RegistrationSeat.holder)))
        .scalars()
        .all()
    )


@pytest.fixture
async def cal(db):
    return await public_calendar(db)


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


@pytest.mark.parametrize(
    "kw",
    [
        {"holder": ""}, {"holder": 5}, {"holder": None}, {"holder": "x" * 65}, {"holder": "a\nb"},
        {"admin": 1}, {"admin": None}, {"occurrence_key": "x"}, {"event_id": "nope"},
        {"provider": ""}, {"target": "x" * 101},
    ],
)  # fmt: skip
async def test_admit_arguments_are_checked(db, cal, kw):
    event = await one_off(db, cal)
    args = {
        "tenant_id": "default",
        "event_id": event.id,
        "occurrence_key": str(event.id),
        "provider": PROVIDER,
        "target": KNOWN_TARGET,
        "holder": "h1",
        **kw,
    }
    with pytest.raises(ValueError):
        await admit(db, **args)
    assert await rows(db) == []


async def test_holder_length_edge(db, cal):
    event = await one_off(db, cal)
    assert (await take(db, event, "h" * constants.REGISTRATION_HOLDER_MAX)).admitted


async def test_release_and_page_arguments_are_checked(db):
    base = {"tenant_id": "default", "provider": PROVIDER}
    for bad in ([], [""], ["a"] * 0, "abc", [1], ["x" * 65]):
        with pytest.raises(ValueError):
            await release(db, holders=bad, **base)
    with pytest.raises(ValueError):
        await release(db, holders=[f"h{n}" for n in range(constants.SEAT_RELEASE_MAX + 1)], **base)
    await release(db, holders=[f"h{n}" for n in range(constants.SEAT_RELEASE_MAX)], **base)
    for limit in (0, -1, True, constants.SEAT_HOLDERS_MAX + 1, "5", None):
        with pytest.raises(ValueError):
            await seat_holders(db, after=None, limit=limit, **base)
    await seat_holders(db, after=None, limit=constants.SEAT_HOLDERS_MAX, **base)
    await seat_holders(db, after=None, limit=1, **base)
    for after in ("", 5, "x" * 65):
        with pytest.raises(ValueError):
            await seat_holders(db, after=after, limit=1, **base)
    with pytest.raises(ValueError):
        await release_target(db, target="", **base)


async def test_tenant_pinned(db, cal):
    event = await one_off(db, cal)
    with pytest.raises(TenantIsolationError):
        await admit(
            db,
            tenant_id="b",
            event_id=event.id,
            occurrence_key=str(event.id),
            provider=PROVIDER,
            target=KNOWN_TARGET,
            holder="h1",
        )
    for call in (
        release(db, tenant_id="b", provider=PROVIDER, holders=["h1"]),
        release_target(db, tenant_id="b", provider=PROVIDER, target=KNOWN_TARGET),
        seat_holders(db, tenant_id="b", provider=PROVIDER, after=None, limit=1),
        counts(db, tenant_id="b", event_id=event.id),
    ):
        with pytest.raises(TenantIsolationError):
            await call


@pytest.mark.unbound_tenant
async def test_tenants_keep_their_seats_apart(db_state):
    ids = {}
    for tenant in ("a", "b"):
        with tenant_scope(tenant):
            async with db_state.session_factory() as db:
                cal = Calendar(slug="pub", name="Pub", owner_id="o", visibility=Visibility.PUBLIC)
                db.add(cal)
                await db.flush()
                event = await one_off(db, cal, registration_capacity=1)
                ids[tenant] = event.id
                await db.commit()
    for tenant in ("a", "b"):  # the same holder id, one seat each
        with tenant_scope(tenant):
            async with db_state.session_factory() as db:
                got = await admit(
                    db,
                    tenant_id=tenant,
                    event_id=ids[tenant],
                    occurrence_key=str(ids[tenant]),
                    provider=PROVIDER,
                    target=KNOWN_TARGET,
                    holder="same-holder",
                    now=NOW,
                )
                assert got.admitted
                await db.commit()
    with tenant_scope("a"):  # another tenant's event is not there to admit to
        async with db_state.session_factory() as db:
            got = await admit(
                db,
                tenant_id="a",
                event_id=ids["b"],
                occurrence_key=str(ids["b"]),
                provider=PROVIDER,
                target=KNOWN_TARGET,
                holder="h9",
                now=NOW,
            )
            assert (got.admitted, got.code) == (False, "event_unavailable")
            assert await release(db, tenant_id="a", provider=PROVIDER, holders=["same-holder"]) == 1
            await db.commit()
    with tenant_scope("b"):
        async with db_state.session_factory() as db:
            assert [r.holder for r in await rows(db)] == ["same-holder"]
            await consistent(db)


async def test_locale_fills_the_event_for_the_caller(db, cal):
    event = await one_off(db, cal)
    got = await take(db, event, "h1", locale="de")
    assert got.admitted and got.event is not None and got.event.lang == "en"
    assert "Mittwoch" in got.event.when_text
    refused = await take(db, event, "h1", locale="de", target="nope")
    assert refused.event is None
