"""Storing a fetched feed: the one bounded scanner, one transaction, pruning only after success."""

from __future__ import annotations

import time

import pytest
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions import items as items_module
from sm_events.feeds.subscriptions import store
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.models import ExternalItem, Subscription
from sqlalchemy import select

from tests.feeds.importing import corpus
from tests.feeds.importing.test_scan import HOSTILE
from tests.support.subscriptions import ics, seed_calendar, seed_subscription, vevent

TZ = "Europe/Vienna"


async def _store(db, sub, body, **kw):
    return await store.store_feed(db, sub, calendar_tz=TZ, body=body, **kw)


async def _state(db, sub_id):
    """``(generation, item_count)`` as the database holds them."""
    row = (
        await db.execute(
            select(Subscription.generation, Subscription.item_count).where(
                Subscription.id == sub_id
            )
        )
    ).one()
    return tuple(row)


async def _rows(db, sub=None):
    stmt = select(ExternalItem).order_by(ExternalItem.uid)
    if sub is not None:
        stmt = stmt.where(ExternalItem.subscription_id == sub.id)
    return list((await db.execute(stmt)).scalars())


@pytest.fixture
async def sub(db):
    return await seed_subscription(db, await seed_calendar(db))


def _three() -> bytes:
    return ics(*(vevent(UID=f"u{n}@x", SUMMARY=f"Item {n}") for n in range(3)))


async def test_first_fetch_stores_and_counts(db, sub):
    body = ics(
        vevent(UID="ok@x"),
        vevent(
            UID="tz@x",
            **{"DTSTART;TZID=My Zone": "20260701T100000", "DTEND;TZID=My Zone": "20260701T110000"},
        ),
        vevent(UID="rule@x", RRULE="FREQ=SECONDLY"),
    )
    counts = await _store(db, sub, body)
    assert (counts.stored, counts.skipped) == (1, 2)
    assert counts.reasons == {"unknown_timezone": 1, "unsupported_rule": 1}
    assert (sub.generation, sub.item_count) == (1, 1)
    assert sub.last_counts == {"stored": 1, "skipped": 2, "reasons": counts.reasons}
    (row,) = await _rows(db, sub)
    assert (row.uid, row.seen_generation, row.tenant_id) == ("ok@x", 1, "default")


async def test_unchanged_rewrites_nothing(db, sub):
    await _store(db, sub, _three())
    await db.flush()
    before = {r.uid: r.updated_at for r in await _rows(db)}
    await _store(db, sub, _three())
    await db.flush()
    sid = sub.id
    db.expire_all()
    assert {r.uid: r.updated_at for r in await _rows(db)} == before
    assert await _state(db, sid) == (2, 3)
    assert {r.seen_generation for r in await _rows(db)} == {2}


async def test_changed_item_updated(db, sub):
    await _store(db, sub, _three())
    body = ics(
        *(vevent(UID=f"u{n}@x", SUMMARY="Changed" if n == 1 else f"Item {n}") for n in range(3))
    )
    await _store(db, sub, body)
    db.expire_all()
    assert {r.uid: r.title for r in await _rows(db)}["u1@x"] == "Changed"
    assert len(await _rows(db)) == 3


async def test_vanished_item_deleted_after_success(db, sub):
    await _store(db, sub, _three())
    await _store(db, sub, ics(vevent(UID="u0@x", SUMMARY="Item 0")))
    sid = sub.id
    db.expire_all()
    assert [r.uid for r in await _rows(db)] == ["u0@x"]
    assert (await _state(db, sid))[1] == 1


async def test_empty_feed_clears(db, sub):
    await _store(db, sub, _three())
    counts = await _store(db, sub, ics())
    sid = sub.id
    db.expire_all()
    assert counts.stored == 0 and await _rows(db) == []
    assert await _state(db, sid) == (2, 0)


async def _snapshot(db, sub):
    await db.refresh(sub)
    return (
        [(r.uid, r.title, r.seen_generation) for r in await _rows(db)],
        sub.generation,
        sub.item_count,
    )


@pytest.mark.parametrize("failure", ["nul", "from_ical", "too_many_events", "to_values"])
async def test_prune_only_after_full_success(db, sub, monkeypatch, failure):
    await _store(db, sub, _three())
    await db.commit()
    before = await _snapshot(db, sub)
    body = _three()
    if failure == "nul":
        body = body.replace(b"Item 1", b"Ite\x00m")
    elif failure == "too_many_events":
        body = corpus.events(constants.IMPORT_MAX_EVENTS + 1)
    elif failure == "from_ical":
        monkeypatch.setattr(
            store, "map_calendar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
    else:
        real = items_module.to_values
        calls = {"n": 0}

        def second_raises(mapped):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real(mapped)

        monkeypatch.setattr(store.items, "to_values", second_raises)
        body = ics(*(vevent(UID=f"u{n}@x", SUMMARY=f"New {n}") for n in range(3)))
    with pytest.raises((FetchFailure, RuntimeError)):
        await _store(db, sub, body)
    await db.rollback()
    assert await _snapshot(db, sub) == before


@pytest.mark.parametrize(("name", "build", "code"), HOSTILE, ids=[h[0] for h in HOSTILE])
async def test_hostile_corpus_through_store(db, sub, name, build, code):
    started = time.monotonic()
    with pytest.raises(FetchFailure) as caught:
        await _store(db, sub, build())
    assert time.monotonic() - started < 2
    assert caught.value.code == code
    assert code in constants.SUBSCRIPTION_FAILURE_CODES
    assert await _rows(db) == [] and sub.generation == 0


async def test_recurrence_children_fold_into_master(db, sub):
    body = ics(
        vevent(UID="s@x", RRULE="FREQ=WEEKLY;COUNT=3"),
        vevent(
            **{
                "UID": "s@x",
                "RECURRENCE-ID": "20260708T100000Z",
                "DTSTART": "20260709T100000Z",
                "DTEND": "20260709T110000Z",
            }
        ),
    )
    await _store(db, sub, body)
    (row,) = await _rows(db)
    assert [o["kind"] for o in row.overrides] == ["moved"]


async def test_other_subscription_untouched(db, sub):
    other = await seed_subscription(db, await seed_calendar(db, "other"), label="Other")
    await _store(db, other, _three())
    await _store(db, sub, _three())
    await _store(db, sub, ics())
    assert len(await _rows(db, other)) == 3 and await _rows(db, sub) == []
    assert (other.generation, other.item_count) == (1, 3)


@pytest.mark.unbound_tenant
async def test_other_tenant_untouched(db):
    with tenant_scope("acme"):
        theirs = await seed_subscription(db, await seed_calendar(db, "acme-cal"))
        await _store(db, theirs, _three())
        await db.commit()
    with tenant_scope("default"):
        mine = await seed_subscription(db, await seed_calendar(db))
        await _store(db, mine, ics(vevent(UID="mine@x")))
        await _store(db, mine, ics())
        await db.commit()
    with tenant_scope("acme"):
        assert len(await _rows(db, theirs)) == 3


async def test_the_per_subscription_and_per_tenant_caps(db, sub, monkeypatch):
    monkeypatch.setattr(constants, "SUBSCRIPTION_TENANT_ITEMS_MAX", 4)
    monkeypatch.setattr(store.constants, "SUBSCRIPTION_TENANT_ITEMS_MAX", 4)
    other = await seed_subscription(db, await seed_calendar(db, "other"))
    await _store(db, other, _three())
    with pytest.raises(FetchFailure) as caught:
        await _store(db, sub, _three())  # 3 + 3 > 4 in this tenant
    assert caught.value.code == "too_many_events"
    assert await _rows(db, sub) == []
