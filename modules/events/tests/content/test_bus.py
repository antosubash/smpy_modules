"""Events go out after the commit and never for a rolled-back write."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest
from simple_module_core.events import Event, EventBus
from simple_module_db import current_tenant_id
from sm_events.content import bus
from sm_events.contracts import events as contract
from sm_events.core.tenancy import tenant_scope

from tests.support.access import seed_calendars
from tests.support.calendars import bare_event

WHEN = datetime(2026, 7, 1, tzinfo=UTC)


def deleted(tenant="default") -> contract.EventDeleted:
    return contract.EventDeleted(
        tenant_id=tenant,
        event_id=uuid.uuid4(),
        calendar_id=uuid.uuid4(),
        uid="u@simple-module-events",
        was_published=True,
    )


class Recorder:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.seen: list[tuple[Event, str | None]] = []
        self.bus.subscribe(contract.EventDeleted, self._on)

    async def _on(self, event):
        self.seen.append((event, current_tenant_id.get()))


async def dirty_write(db):
    """Something to commit: an event row."""
    await bare_event(db, (await seed_calendars(db))["I"])


async def test_emitted_after_commit_only(db):
    rec = Recorder()
    bus.attach(db, rec.bus)
    await dirty_write(db)
    bus.emit(db, deleted())
    assert rec.seen == []  # queued, not sent
    await bus.rollback(db)
    assert rec.seen == []
    await dirty_write(db)
    bus.emit(db, deleted())
    await bus.commit(db)
    assert len(rec.seen) == 1


async def test_rollback_discards_even_when_commit_follows(db):
    rec = Recorder()
    bus.attach(db, rec.bus)
    await dirty_write(db)
    bus.emit(db, deleted())
    await bus.rollback(db)
    await dirty_write(db)
    await bus.commit(db)
    assert rec.seen == []


async def test_a_savepoint_rollback_drops_its_events(db):
    rec = Recorder()
    bus.attach(db, rec.bus)
    await dirty_write(db)
    with pytest.raises(RuntimeError):
        async with db.begin_nested():
            bus.emit(db, deleted())
            raise RuntimeError
    bus.emit(db, deleted())
    await bus.commit(db)
    assert len(rec.seen) == 1


async def test_no_bus_no_publish(db):
    await dirty_write(db)
    bus.emit(db, deleted())  # nothing attached: nothing queued, nothing raised
    await bus.commit(db)


async def test_none_items_skipped(db):
    rec = Recorder()
    bus.attach(db, rec.bus)
    await dirty_write(db)
    bus.emit(db, None, None)
    await bus.commit(db)
    assert rec.seen == []


@pytest.mark.unbound_tenant
async def test_tenant_rebound_on_publish(db):
    rec = Recorder()
    bus.attach(db, rec.bus)
    with tenant_scope("b"):
        await dirty_write(db)
        await db.flush()
        bus.emit(db, deleted("b"))
    assert current_tenant_id.get() is None
    await bus.commit(db)  # the scope is gone; the handler still runs in "b"
    assert [t for _e, t in rec.seen] == ["b"]
    assert current_tenant_id.get() is None


async def test_handler_failure_does_not_fail_the_commit(db):
    class Boom:
        async def publish(self, _event):
            raise RuntimeError

    bus.attach(db, Boom())
    await dirty_write(db)
    bus.emit(db, deleted())
    await bus.commit(db)  # logged by the framework, never raised


def names(cls) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


def test_dataclass_shapes():
    head = ["tenant_id", "event_id", "calendar_id", "uid"]
    assert names(contract.EventPublished) == [*head, "published_at"]
    assert names(contract.EventRescheduled) == [
        *head, "original_start", "old_start", "old_end", "new_start", "new_end", "rule_changed",
    ]  # fmt: skip
    assert names(contract.EventCancelled) == [*head, "original_start"]
    assert names(contract.EventDeleted) == [*head, "was_published"]
    for cls in (
        contract.EventPublished,
        contract.EventRescheduled,
        contract.EventCancelled,
        contract.EventDeleted,
    ):
        assert issubclass(cls, Event)
    assert contract.EventPublished(
        tenant_id="t", event_id=uuid.uuid4(), calendar_id=uuid.uuid4(), uid="u", published_at=WHEN
    )


NEW = (
    contract.EventUnpublished,
    contract.EventReinstated,
    contract.OccurrenceSkipped,
    contract.EventRestored,
    contract.EventUpdated,
)


def test_all_events_serialisable():
    from simple_module_core.durable_events import check_serializable

    for cls in (
        contract.EventPublished,
        contract.EventRescheduled,
        contract.EventCancelled,
        contract.EventDeleted,
        *NEW,
    ):
        check_serializable(cls)


def test_new_dataclass_shapes():
    head = ["tenant_id", "event_id", "calendar_id", "uid"]
    assert names(contract.EventUnpublished) == [*head, "was_scheduled"]
    assert names(contract.EventReinstated) == [*head, "original_start"]
    assert names(contract.OccurrenceSkipped) == [*head, "original_start"]
    assert names(contract.EventRestored) == head
    assert names(contract.EventUpdated) == [*head, "changed"]
    assert all(issubclass(cls, Event) for cls in NEW)


def test_no_payload_carries_content():
    """Identifiers, instants, flags and field names only: never a title, text or ``extra``."""
    for cls in (*NEW, contract.EventPublished, contract.EventDeleted):
        for field in dataclasses.fields(cls):
            assert field.name not in {"title", "description", "texts", "extra", "summary", "email"}


class Transport:
    """A durable transport that writes into the session's transaction, as the outbox does."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[object, list[str], str | None, bool]] = []
        self.fail = fail

    async def enqueue(self, event, handler_names, db):
        if self.fail:
            raise RuntimeError("outbox down")
        in_txn = db.sync_session.get_transaction() is not None
        self.calls.append((event, list(handler_names), current_tenant_id.get(), in_txn))


def durable_bus(transport, *, handlers=True):
    ev_bus = EventBus()
    ev_bus.durable_transport = transport  # type: ignore[assignment]
    if handlers:

        async def handle(event, ctx):
            return None

        ev_bus.subscribe_durable(contract.EventDeleted, handle, name="test.handler")
    return ev_bus


async def test_durable_published_in_transaction(db):
    transport = Transport()
    bus.attach(db, durable_bus(transport))
    await dirty_write(db)
    bus.emit(db, deleted())
    assert transport.calls == []  # not before the request ends
    await bus.commit(db)
    ((event, handlers, tenant, in_txn),) = transport.calls
    assert isinstance(event, contract.EventDeleted) and handlers == ["test.handler"]
    assert tenant == "default" and in_txn  # inside the writer's transaction, under its tenant


async def test_durable_nothing_after_rollback(db):
    transport = Transport()
    bus.attach(db, durable_bus(transport))
    await dirty_write(db)
    bus.emit(db, deleted())
    await bus.rollback(db)
    await dirty_write(db)
    await bus.commit(db)
    assert transport.calls == []


async def test_no_durable_without_handlers_or_transport(db):
    transport = Transport()
    bus.attach(db, durable_bus(transport, handlers=False))
    await dirty_write(db)
    bus.emit(db, deleted())
    await bus.commit(db)
    assert transport.calls == []
    rec = Recorder()
    bus.attach(db, rec.bus)  # in-process only: no transport at all
    bus.emit(db, deleted())
    await bus.commit(db)
    assert len(rec.seen) == 1


async def test_a_failing_outbox_fails_the_commit_so_the_change_is_not_kept(db):
    """No change without its event: the writer sees the failure and rolls back."""
    bus.attach(db, durable_bus(Transport(fail=True)))
    await dirty_write(db)
    bus.emit(db, deleted())
    with pytest.raises(RuntimeError, match="outbox down"):
        await bus.commit(db)
    await bus.rollback(db)
    from sm_events.models import Event as Row
    from sqlalchemy import select

    assert (await db.execute(select(Row))).scalars().all() == []


async def test_in_process_and_durable_both_deliver(db):
    transport = Transport()
    ev_bus = durable_bus(transport)
    seen = []

    async def local(event):
        seen.append(event)

    ev_bus.subscribe(contract.EventDeleted, local)
    bus.attach(db, ev_bus)
    await dirty_write(db)
    bus.emit(db, deleted())
    await bus.commit(db)
    assert len(seen) == 1 and len(transport.calls) == 1
