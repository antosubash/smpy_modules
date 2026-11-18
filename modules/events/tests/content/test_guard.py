"""The compare-and-set on ``revision``."""

from __future__ import annotations

import asyncio

import pytest
from sm_events.content.guard import claim, claim_revision
from sm_events.core.errors import NotFound, Stale
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES
from tests.support.access import seed_calendars
from tests.support.calendars import bare_event


async def an_event(db, **fields):
    return await bare_event(db, (await seed_calendars(db))["I"], **fields)


async def test_cas_loses_once(db):
    event = await an_event(db)
    assert await claim_revision(db, event.id, 1, actor="u") == 2
    with pytest.raises(Stale) as lost:
        await claim_revision(db, event.id, 1, actor="u")
    assert lost.value.current_revision == 2
    assert lost.value.headers == {"X-Current-Revision": "2"}
    assert await claim_revision(db, event.id, 2, actor="u") == 3


async def test_cas_stamps_the_actor(db):
    event = await an_event(db)
    await claim_revision(db, event.id, 1, actor="someone")
    row = (
        await db.execute(select(Event.updated_by, Event.updated_at).where(Event.id == event.id))
    ).one()
    assert row.updated_by == "someone" and row.updated_at is not None


async def test_cas_missing_is_not_found(db):
    import uuid

    with pytest.raises(NotFound):
        await claim_revision(db, uuid.uuid4(), 1, actor=None)


@pytest.mark.unbound_tenant
async def test_cas_other_tenant_is_not_found(db):
    with tenant_scope("a"):
        event = await an_event(db)
    with tenant_scope("b"), pytest.raises(NotFound):
        await claim_revision(db, event.id, 1, actor=None)
    with tenant_scope("a"):
        assert await claim_revision(db, event.id, 1, actor=None) == 2


async def test_cas_trashed_needs_flag(db):
    event = await an_event(db)
    await db.delete(event)
    await db.flush()
    with pytest.raises(NotFound):
        await claim_revision(db, event.id, 1, actor=None)
    assert await claim_revision(db, event.id, 1, actor=None, trashed=True) == 2


async def test_live_event_with_trashed_flag_is_not_found(db):
    event = await an_event(db)
    with pytest.raises(NotFound):
        await claim_revision(db, event.id, 1, actor=None, trashed=True)


async def test_claim_updates_the_loaded_event(db):
    event = await an_event(db)
    await claim(db, event, 1, actor="u")
    assert event.revision == 2 and event.updated_by == "u"


async def test_a_rolled_back_claim_leaves_no_wrong_revision_in_memory(db):
    event = await an_event(db)
    with pytest.raises(RuntimeError):
        async with db.begin_nested():
            await claim(db, event, 1, actor="u")
            raise RuntimeError
    await db.refresh(event)
    assert event.revision == 1
    assert await claim_revision(db, event.id, 1, actor="u") == 2


@pytest.mark.skipif(not USING_POSTGRES, reason="row locks need Postgres")
async def test_concurrent_cas_serialises(db_state, db):
    event = await an_event(db)
    await db.commit()
    first_holds = asyncio.Event()
    release = asyncio.Event()
    results: dict[str, object] = {}

    async def writer(name: str, *, hold: bool) -> None:
        async with db_state.session_factory() as session:
            try:
                results[name] = await claim_revision(session, event.id, 1, actor=name)
            except Stale:
                results[name] = "stale"
            if hold:
                first_holds.set()
                await release.wait()
            await session.commit()

    one = asyncio.create_task(writer("one", hold=True))
    await first_holds.wait()
    two = asyncio.create_task(writer("two", hold=False))
    await asyncio.sleep(0.3)  # two is blocked on the row lock one holds
    assert "two" not in results
    release.set()
    await asyncio.gather(one, two)
    assert results == {"one": 2, "two": "stale"}
