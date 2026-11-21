"""Bus events, published only after the commit succeeds.

A reduced copy of ``sm_records.core.events``: the session learns the app's bus
(:func:`attach`, done by the request dependency), a service queues events with
:func:`emit`, and they go out through the framework's ``register_on_commit`` once
the transaction commits, under the tenant they describe. A rollback, a refused
write and a lost ``expected_revision`` race discard the queue, so no subscriber
sees an event for work that is not there.

**Durable delivery.** When the session's bus has a durable transport (the ``background_tasks``
outbox) and the event's type has durable handlers, :func:`emit` also queues it for the outbox, and
:func:`commit` writes those rows through ``bus.publish_durable`` **in the same transaction**
before finishing it: they exist exactly when the change does. Delivery, retries, backoff and the
dead-letter state are the framework's. A rolled-back write discards the queue too.

Services never commit. The request ends in :func:`commit`, which flags the
session as written first: the guard's ``UPDATE`` is Core DML, which the framework's
flush listener never sees, and an unflagged session is rolled back, not committed.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Final

from simple_module_db import finalize_session, mark_written
from simple_module_db.callbacks import discard_on_commit_callbacks, register_on_commit
from simple_module_db.listeners import current_tenant_id

from sm_events.core.tenancy import tenant_scope

__all__ = ["BUS_KEY", "DURABLE_KEY", "attach", "commit", "emit", "rollback"]

BUS_KEY: Final = "sm_events.event_bus"
"""``session.info`` key holding the bus this session's events go to."""
DURABLE_KEY: Final = "sm_events.durable_queue"
"""``session.info`` key holding the events to write to the outbox at commit."""


def attach(session: Any, bus: Any) -> None:
    """Send ``session``'s events to ``bus``; ``None`` leaves it bus-less."""
    if bus is not None:
        session.info[BUS_KEY] = bus


async def _publish_all(bus: Any, events: list[Any], tenant: str | None) -> None:
    if tenant is None:
        for event in events:
            await bus.publish(event)
        return
    with tenant_scope(tenant):
        for event in events:
            await bus.publish(event)


def _durable(bus: Any, event: Any) -> bool:
    return getattr(bus, "durable_transport", None) is not None and bool(
        bus.durable.handler_names(type(event))
    )


def emit(session: Any, *events: Any) -> None:
    """Publish ``events`` once ``session`` commits; never if it rolls back.
    ``None`` items are skipped, and a session with no bus publishes nothing."""
    items = [event for event in events if event is not None]
    bus = session.info.get(BUS_KEY)
    if not items or bus is None:
        return
    register_on_commit(session, partial(_publish_all, bus, items, current_tenant_id.get()))
    queue = session.info.setdefault(DURABLE_KEY, [])
    queue.extend(event for event in items if _durable(bus, event))


async def _enqueue_durable(session: Any) -> None:
    """Write the queued events to the outbox, in this transaction, under the tenant they
    describe. A failure propagates: the caller rolls back, so no change without its event."""
    queue = session.info.pop(DURABLE_KEY, None)
    bus = session.info.get(BUS_KEY)
    if not queue or bus is None:
        return
    for event in queue:
        with tenant_scope(event.tenant_id):
            await bus.publish_durable(event, session)


async def commit(session: Any) -> None:
    """Commit, and publish what the transaction queued."""
    await _enqueue_durable(session)
    mark_written(session)
    await finalize_session(session)


async def rollback(session: Any) -> None:
    """Roll back, and forget every event the transaction queued."""
    discard_on_commit_callbacks(session)
    session.info.pop(DURABLE_KEY, None)
    await session.rollback()
