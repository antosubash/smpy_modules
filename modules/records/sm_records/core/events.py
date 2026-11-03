"""Publishing this module's domain events.

:mod:`sm_records.contracts.events` declares what is published; this is where
and when. Three rules:

**From the service that wrote, so every write path publishes.** The HTTP
endpoints, ``python -m sm_records.cli import``, the seeder and anything else
that calls ``services.records.create_record`` reach the same :func:`emit`.
Publishing from the endpoints (as this module used to) meant a record written
from the command line told no subscriber (GH #128). The bus is not imported —
architecture rule 1 still holds — it rides on the session: the request's
session gets ``app.state.sm.event_bus`` from :func:`sm_records.web.deps.request_db`,
and a caller outside a request hands one to :func:`attach`. A session with no
bus attached publishes nothing, which is what a standalone CLI process gets
unless ``--app`` names the host whose bus to use (:mod:`sm_records.records.cli.cli_host`,
GH #157) — and it says so on stderr when it writes without one.

**After the commit, never inside it.** :func:`emit` queues on the framework's
``on_commit`` (``simple_module_db.callbacks``), which runs only once
``finalize_session`` has committed, and is discarded on rollback. That is why
nothing in this module may finish a write with a bare ``session.commit()``:
it neither runs nor clears the queue — :func:`commit` and :func:`rollback` are
the two ways out. Published inline, a subscriber could act on a write the
caller then rolled back, and would read the record through a different session
that cannot see it yet.

**Only for work that survived its savepoint.** The framework's queue is
session-wide and knows nothing of ``begin_nested``: a row an import skipped
inside a savepoint would still be announced. :func:`held` buffers what is
emitted inside it and lets it through only if the block exits cleanly, which is
also the point at which an import has re-stamped the uuid the file chose — so
an event is *built* there, from a zero-argument builder, rather than when
``create_record`` returns. :func:`muted` drops what is emitted inside it, for a
caller that announces the operation its own way (a bulk action attributes a
cascade differently from the single delete it is made of).

**In the tenant it describes.** The tenant bound when an event is queued is
bound again around the publish, so a subscriber finds ``current_tenant_id``
equal to the event's ``tenant_id`` however late the callback runs.

A host with no subscribers pays one ``await`` that returns immediately:
:meth:`EventBus.publish` returns before gathering anything when nothing is
listening. That is what makes one event per record of a bulk path affordable.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from functools import partial
from typing import Any, Final

from simple_module_db import finalize_session
from simple_module_db.callbacks import discard_on_commit_callbacks, register_on_commit
from simple_module_db.listeners import current_tenant_id

from sm_records.core.event_payloads import (
    created,
    purged,
    restored,
    trashed,
    type_changed,
    type_deleted,
    updated,
)
from sm_records.core.tenancy import tenant_scope
from sm_records.records.services._common import mark_written

__all__ = [
    "attach",
    "commit",
    "created",
    "emit",
    "held",
    "muted",
    "purged",
    "restored",
    "rollback",
    "trashed",
    "type_changed",
    "type_deleted",
    "updated",
]

BUS_KEY: Final = "sm_records.event_bus"
"""``session.info`` key holding the bus this session's events go to."""

_HELD_KEY: Final = "sm_records.held_events"
"""``session.info`` key holding the stack of open :func:`held`/:func:`muted` buffers."""

_DROP: Final = object()
"""Marks a :func:`muted` buffer on the stack."""


def attach(session: Any, bus: Any) -> None:
    """Send ``session``'s events to ``bus``. ``None`` leaves it bus-less."""
    if bus is not None:
        session.info[BUS_KEY] = bus


async def _publish_all(bus: Any, events: Sequence[Any], tenant: str | None) -> None:
    with tenant_scope(tenant) if tenant is not None else nullcontext():
        for event in events:
            await bus.publish(event)


def _build(item: Any) -> Any:
    """An event, or a zero-argument builder of one (see the module docstring)."""
    return item() if callable(item) else item


def emit(session: Any, *events: Any) -> None:
    """Publish ``events`` once ``session`` commits; never if it rolls back.

    Each item is an event or a zero-argument builder of one, ``None`` skipped.
    All of them go in one callback, in order: the events of one operation
    describe it together, and a subscriber that sees a cascade's trash events
    out of order cannot tell which record the operator actually asked about.
    """
    items = [item for item in events if item is not None]
    if not items:
        return
    stack = session.info.get(_HELD_KEY)
    if stack:
        if stack[-1] is not _DROP:
            stack[-1].extend(items)
        return
    bus = session.info.get(BUS_KEY)
    if bus is None:
        return
    built = [event for event in map(_build, items) if event is not None]
    register_on_commit(session, partial(_publish_all, bus, built, current_tenant_id.get()))


@contextmanager
def _pushed(session: Any, entry: Any) -> Iterator[None]:
    stack = session.info.setdefault(_HELD_KEY, [])
    stack.append(entry)
    try:
        yield
    finally:
        stack.pop()


@contextmanager
def held(session: Any) -> Iterator[None]:
    """Buffer what is emitted inside; release it only if the block succeeds."""
    bucket: list[Any] = []
    with _pushed(session, bucket):
        yield
    if not session.info.get(_HELD_KEY) and session.info.get(BUS_KEY) is None:
        return  # nobody to tell: skip building one event per imported row
    # Built here, not in ``emit``: an outer ``held`` must see finished events
    # of this block, not builders reading attributes a later block may change.
    emit(session, *[_build(item) for item in bucket])


@contextmanager
def muted(session: Any) -> Iterator[None]:
    """Drop whatever is emitted inside — the caller announces the work itself."""
    with _pushed(session, _DROP):
        yield


async def commit(session: Any) -> None:
    """Commit outside a request, and publish what the transaction queued.

    ``finalize_session``, flagged as written first: it commits only a session
    its ``after_flush`` listener marked, and core DML (a purge, a guarded bump)
    or a session built without the framework's listeners never sets the mark,
    so an unflagged finalize would roll the work back instead.
    """
    mark_written(session)
    await finalize_session(session)


async def rollback(session: Any) -> None:
    """Roll back, and forget every event the transaction queued."""
    discard_on_commit_callbacks(session)
    await session.rollback()
