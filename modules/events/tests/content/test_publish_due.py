"""Scheduled publishing: ``events.publish_due``."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.content import guard
from sm_events.content.publish_due import publish_due_async
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Event, Revision
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES, make_db_state
from tests.support.calendars import seed_event

NOW = datetime(2026, 7, 1, 12, tzinfo=UTC)
PAST = NOW - timedelta(hours=1)
FUTURE = NOW + timedelta(hours=1)


async def seed(state, tenant="default", count=1, **fields):
    """``count`` events with a text in a new calendar of ``tenant``, committed."""
    fields.setdefault("status", "draft")
    fields.setdefault("publish_at", PAST)
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            cal = Calendar(slug=f"c-{uuid.uuid4().hex[:8]}", name="c", owner_id="o")
            s.add(cal)
            await s.flush()
            events = [await seed_event(s, cal, title=f"e{i}", **fields) for i in range(count)]
            await s.commit()
            return [e.id for e in events]


async def events_of(state, tenant="default") -> list[Event]:
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            stmt = select(Event).execution_options(include_deleted=True)
            return list((await s.execute(stmt)).scalars())


async def revisions_of(state, tenant="default") -> list[Revision]:
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            return list((await s.execute(select(Revision))).scalars())


async def run(state):
    return await publish_due_async(state.session_factory, now=NOW)


@pytest.mark.unbound_tenant
async def test_publishes_only_due(db_state):
    (due,) = await seed(db_state)
    (later,) = await seed(db_state, publish_at=FUTURE)
    assert await run(db_state) == {"tenants": 1, "published": 1, "failed": 0}
    by_id = {e.id: e for e in await events_of(db_state)}
    event = by_id[due]
    assert (event.status, event.publish_at, event.published_at) == ("published", None, NOW)
    assert event.revision == 2
    assert (by_id[later].status, by_id[later].revision) == ("draft", 1)
    (rev,) = await revisions_of(db_state)
    assert (rev.event_id, rev.action, rev.actor, rev.number) == (
        due,
        "published_scheduled",
        None,
        2,
    )
    assert rev.snapshot["status"] == "published"


@pytest.mark.unbound_tenant
async def test_future_is_untouched(db_state):
    await seed(db_state, publish_at=FUTURE)
    await seed(db_state, publish_at=None, status="draft")
    assert await run(db_state) == {"tenants": 0, "published": 0, "failed": 0}
    assert {e.status for e in await events_of(db_state)} == {"draft"}
    assert await revisions_of(db_state) == []


@pytest.mark.unbound_tenant
async def test_in_review_is_published_too(db_state):
    await seed(db_state, status="in_review")
    assert (await run(db_state))["published"] == 1


@pytest.mark.unbound_tenant
async def test_per_tenant(db_state):
    await seed(db_state, "a", count=2)
    await seed(db_state, "b", count=1)
    assert await run(db_state) == {"tenants": 2, "published": 3, "failed": 0}
    for tenant, n in (("a", 2), ("b", 1)):
        events = await events_of(db_state, tenant)
        assert len(events) == n
        assert {e.status for e in events} == {"published"}
        revs = await revisions_of(db_state, tenant)
        assert {r.event_id for r in revs} == {e.id for e in events}
        assert {r.tenant_id for r in revs} == {tenant}


@pytest.mark.unbound_tenant
async def test_batch_cap(db_state):
    await seed(db_state, count=constants.PUBLISH_DUE_BATCH + 1)
    assert (await run(db_state))["published"] == constants.PUBLISH_DUE_BATCH
    assert (await run(db_state))["published"] == 1  # the next pass takes the rest


@pytest.mark.unbound_tenant
async def test_trashed_not_published(db_state):
    await seed(db_state, is_deleted=True)
    assert await run(db_state) == {"tenants": 0, "published": 0, "failed": 0}
    assert {e.status for e in await events_of(db_state)} == {"draft"}


@pytest.mark.unbound_tenant
async def test_already_published_skipped(db_state):
    await seed(db_state, status="published", publish_at=PAST)
    assert await run(db_state) == {"tenants": 0, "published": 0, "failed": 0}
    assert await revisions_of(db_state) == []


@pytest.mark.unbound_tenant
async def test_redelivered_message_publishes_once(db_state):
    await seed(db_state)
    assert (await run(db_state))["published"] == 1
    assert (await run(db_state))["published"] == 0
    (event,) = await events_of(db_state)
    assert event.revision == 2
    assert len(await revisions_of(db_state)) == 1


@pytest.mark.unbound_tenant
async def test_failing_tenant_does_not_stop_others(db_state, monkeypatch, caplog):
    await seed(db_state, "a")
    await seed(db_state, "b")
    real = guard.claim_revision

    async def boom(db, event_id, expected, **kw):
        if guard.bound_tenant() == "a":
            raise RuntimeError("boom")
        return await real(db, event_id, expected, **kw)

    monkeypatch.setattr(guard, "claim_revision", boom)
    assert await run(db_state) == {"tenants": 2, "published": 1, "failed": 1}
    assert {e.status for e in await events_of(db_state, "a")} == {"draft"}
    assert {e.status for e in await events_of(db_state, "b")} == {"published"}
    assert await revisions_of(db_state, "a") == []
    assert "tenant a" in caplog.text


@pytest.mark.unbound_tenant
async def test_an_edit_between_read_and_claim_wins(db_state, monkeypatch):
    """Somebody edits the event after the beat read it: the stale guard skips it."""
    (event_id,) = await seed(db_state)
    real = guard.claim_revision

    async def edited_first(db, ev_id, expected, **kw):
        async with db_state.session_factory() as other:
            await real(other, ev_id, expected, actor="editor")
            await other.commit()
        return await real(db, ev_id, expected, **kw)

    monkeypatch.setattr(guard, "claim_revision", edited_first)
    if USING_POSTGRES:
        pytest.skip("the editor would wait on the row the beat holds")
    assert await run(db_state) == {"tenants": 1, "published": 0, "failed": 0}
    (event,) = await events_of(db_state)
    assert event.id == event_id and event.status == "draft"
    assert await revisions_of(db_state) == []


@pytest.mark.unbound_tenant
async def test_two_workers_publish_once(tmp_path, monkeypatch):
    """Worker B has read the due row when worker A runs a whole pass. Whichever
    way the database serialises them (A skips B's locked row on Postgres, B loses
    the compare-and-set on SQLite), the event is published exactly once and
    carries exactly one ``published_scheduled`` revision."""
    state = await make_db_state(file=tmp_path / "two.db")
    try:
        await seed(state)
        real = guard.claim_revision
        inner: dict[str, int] = {}
        started: list[bool] = []

        async def worker_a_runs_first(db, event_id, expected, **kw):
            if not started:  # B's first claim; A's own claims go straight through
                started.append(True)
                inner.update(await publish_due_async(state.session_factory, now=NOW))
            return await real(db, event_id, expected, **kw)

        monkeypatch.setattr(guard, "claim_revision", worker_a_runs_first)
        if USING_POSTGRES:
            # A cannot take B's locked row (SKIP LOCKED); it publishes nothing and B wins.
            outcome = await asyncio.wait_for(run(state), 30)
            assert (inner["published"], outcome["published"]) == (0, 1)
        else:
            outcome = await run(state)
            assert (inner["published"], outcome["published"]) == (1, 0)
        (event,) = await events_of(state)
        assert event.status == "published"
        revs = await revisions_of(state)
        assert [r.action for r in revs] == ["published_scheduled"]
        assert revs[0].number == event.revision
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_eager_task_runs(db_state, tmp_path, monkeypatch):
    if USING_POSTGRES:
        pytest.skip("the task reaches its own database through sync_db")
    from background_tasks.core import sync_db
    from sm_events import tasks
    from sm_events.core import worker

    state = await make_db_state(file=tmp_path / "eager.db")
    await seed(state)
    sync_db.set_database_url(f"sqlite:///{tmp_path / 'eager.db'}")
    worker.reset_worker_runtime()
    try:
        # ``apply`` runs the task body in this thread; a running loop is refused,
        # so hand it to a worker thread as a prefork child would have it.
        result = await asyncio.to_thread(tasks.publish_due.apply)
        assert result.get() == {"tenants": 1, "published": 1, "failed": 0}
    finally:
        worker.reset_worker_runtime()
        sync_db.set_database_url(None)
        sync_db.dispose_sync_engine()
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_publish_due_keeps_unknown_extra(db_state):
    """A worker image without the plugin: the event of its type is published and its ``extra``
    is exactly what was stored."""
    from sm_events.calendar import registry

    registry.reset_registry()  # the registry holds the built-ins only: no ``gone:thing``
    raw = {"b": 1, "a": [1, 2], "n": {"z": None}}
    (due,) = await seed(db_state, type="gone:thing", extra=raw)
    assert await run(db_state) == {"tenants": 1, "published": 1, "failed": 0}
    (event,) = await events_of(db_state)
    assert event.id == due and event.status == "published"
    assert (event.type, json.dumps(event.extra)) == ("gone:thing", json.dumps(raw))
    registry.reset_registry()


@pytest.mark.unbound_tenant
async def test_publish_due_publishes_durably(db_state, monkeypatch):
    """The beat's session gets the worker's bus: one durable ``EventPublished`` per publish,
    written in the transaction that publishes."""
    from simple_module_core.events import EventBus
    from sm_events.contracts import events as contract

    calls = []

    class Transport:
        async def enqueue(self, event, names, db):
            calls.append((event, list(names)))

    worker_bus = EventBus()
    worker_bus.durable_transport = Transport()  # type: ignore[assignment]

    async def handler(event, ctx):
        return None

    worker_bus.subscribe_durable(contract.EventPublished, handler, name="test.published")
    from background_tasks.outbox import worker

    monkeypatch.setattr(worker, "worker_bus", lambda: worker_bus)
    (due,) = await seed(db_state)
    assert await run(db_state) == {"tenants": 1, "published": 1, "failed": 0}
    ((event, names),) = calls
    assert isinstance(event, contract.EventPublished) and event.event_id == due
    assert event.published_at == NOW and event.tenant_id == "default"
    assert names == ["test.published"]
    assert await run(db_state) == {"tenants": 0, "published": 0, "failed": 0}
    assert len(calls) == 1  # nothing more to announce
