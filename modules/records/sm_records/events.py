"""Publishing this module's domain events.

:mod:`sm_records.contracts.events` declares what is published; this is where
and when. Three rules:

**From the service that wrote, so every write path publishes.** The HTTP
endpoints, ``python -m sm_records.cli import``, the seeder and anything else
that calls ``services.records.create_record`` reach the same :func:`emit`.
Publishing from the endpoints (as this module used to) meant a record written
from the command line told no subscriber (GH #128). The bus is not imported —
architecture rule 1 still holds — it rides on the session: the request's
session gets ``app.state.sm.event_bus`` from :func:`sm_records.deps.request_db`,
and a caller outside a request hands one to :func:`attach`. A session with no
bus attached publishes nothing, which is what a standalone CLI process with no
host (and therefore no subscriber) gets.

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

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from functools import partial
from typing import Any, Final

from simple_module_db import finalize_session
from simple_module_db.callbacks import discard_on_commit_callbacks, register_on_commit
from simple_module_db.listeners import current_tenant_id

from sm_records.contracts.events import (
    RecordCreated,
    RecordPurged,
    RecordRestored,
    RecordTrashed,
    RecordTypeChanged,
    RecordTypeDeleted,
    RecordUpdated,
)
from sm_records.schema.diff import diff_fields
from sm_records.schema.fields import validate_fields
from sm_records.schema.types import ChangeClass
from sm_records.services._common import mark_written
from sm_records.tenancy import bound_tenant, tenant_scope

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


def _tenant(rtype: Any) -> str:
    """The tenant an event names: the type row's own. :func:`bound_tenant` is
    the fallback for a caller that hands over something without the column."""
    return getattr(rtype, "tenant_id", None) or bound_tenant()


def created(rtype: Any, record: Any) -> RecordCreated:
    return RecordCreated(
        type_key=rtype.key,
        tenant_id=_tenant(rtype),
        uuid=record.uuid,
        locale=record.locale,
        translation_group=record.translation_group,
        status=record.status.value,
    )


def updated(rtype: Any, record: Any, *, status_before: str) -> RecordUpdated:
    """``status_before`` is read by the caller *before* the write, because the
    service mutates the instance in place — by the time this is called there
    is only one status left to read."""
    return RecordUpdated(
        type_key=rtype.key,
        tenant_id=_tenant(rtype),
        uuid=record.uuid,
        version=record.version,
        status_before=status_before,
        status_after=record.status.value,
    )


def trashed(rtype: Any, record: Any, cascade: Iterable[tuple[Any, Any]]) -> list[RecordTrashed]:
    """One event per record the delete actually trashed.

    ``cascade`` is what ``soft_delete_record`` returns: every ``(record,
    type)`` pair it trashed, the one the caller named included. That record's
    event carries ``cascaded_from=None`` and every other one carries its uuid,
    which is the distinction design §9's ``cascade`` makes and that no
    subscriber could reconstruct — the cascaded records belong to types the
    request never mentioned.
    """
    return [
        RecordTrashed(
            type_key=doomed_type.key,
            tenant_id=_tenant(doomed_type),
            uuid=doomed.uuid,
            cascaded_from=None if doomed.uuid == record.uuid else record.uuid,
        )
        for doomed, doomed_type in cascade
    ]


def restored(rtype: Any, record: Any) -> RecordRestored:
    return RecordRestored(type_key=rtype.key, tenant_id=_tenant(rtype), uuid=record.uuid)


def purged(rtype: Any, record: Any) -> RecordPurged:
    return _purged(rtype.key, _tenant(rtype), record)


def _purged(type_key: str, tenant: str, record: Any) -> RecordPurged:
    return RecordPurged(
        type_key=type_key,
        tenant_id=tenant,
        uuid=record.uuid,
        locale=record.locale,
        translation_group=record.translation_group,
    )


def type_changed(rtype: Any, before: Sequence[dict[str, Any]]) -> RecordTypeChanged:
    """The event for one accepted write to a type row.

    ``before`` is the type's stored ``fields`` as they were *before* the call,
    which the endpoint reads off the row it loaded. The diff is recomputed
    here rather than threaded back out of the service, because the two
    services that write a type row — ``update_type`` and ``schema_change.apply``
    — do not return the same thing and neither returns it to every caller.
    It costs no query: ``diff_fields`` compares two field lists in memory, and
    an empty diff (a label edit, a pointer move) is the honest ``additive``.
    """
    old_defs = validate_fields([dict(raw) for raw in before])
    new_defs = validate_fields([dict(raw) for raw in (rtype.fields or [])])
    diff = diff_fields(old_defs, new_defs)
    return RecordTypeChanged(
        type_key=rtype.key,
        tenant_id=_tenant(rtype),
        schema_version=rtype.schema_version,
        kind=diff.kind.value,
        index_affecting_keys=tuple(diff.keys(ChangeClass.INDEX_AFFECTING)),
    )


def type_deleted(type_key: str, records: Sequence[Any]) -> list[Any]:
    """``RecordTypeDeleted`` plus one ``RecordPurged`` per record that went
    with it — the records first, so a subscriber that drops its own rows per
    record and then forgets the type sees them in that order.

    The purge events carry what the rows held, because after this there is
    nothing to read them from. The table set a record lived in is not part of
    any event, since a subscriber addresses records by ``(type_key, uuid)``
    exactly as the API does.

    The tenant is the bound one. The type row is deleted by the time this is
    called, and the request that deleted it was bound to the row's tenant.
    """
    tenant = bound_tenant()
    events: list[Any] = [_purged(type_key, tenant, record) for record in records]
    events.append(RecordTypeDeleted(type_key=type_key, tenant_id=tenant, purged=len(records)))
    return events
