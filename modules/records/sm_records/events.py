"""Publishing this module's domain events — the endpoint half.

:mod:`sm_records.contracts.events` declares what is published; this is where
and when. Two rules, both of them from somewhere else:

**From the endpoint, never the service.** ``docs/architecture.md`` rule 1:
services never import FastAPI, and the bus arrives at runtime on
``request.app.state.sm.event_bus``. It is the seam
:func:`sm_records.menu.mark_dirty` already uses.

**After the commit, never inside it.** :func:`sm_records.deferred.defer` runs a
job once the route's dependency teardown has committed and closed the session,
which is the whole reason that module exists. Published inline, a subscriber
could act on a write the request then rolled back — and it would read the
record back through a *different* session that cannot see it yet, which is the
same GH #257 shape ``CommitBeforeResponseMiddleware`` fixes for clients.

**In the tenant it describes.** :func:`~sm_records.deferred.defer` runs the job
inside the tenant bound when it was queued, so a subscriber finds
``current_tenant_id`` bound to the event's ``tenant_id``. Each builder below
reads the tenant off the type row it was handed. The request is bound to that
tenant, and the framework refuses any row that disagrees, so the two are the
same value.

A host with no subscribers pays one attribute lookup and one ``await`` that
returns immediately: :meth:`EventBus.publish` returns before gathering
anything when nothing is listening. That is what makes emitting one event per
record of a bulk path affordable.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import partial
from typing import Any

from starlette.requests import Request

from sm_records.contracts.events import (
    RecordCreated,
    RecordPurged,
    RecordRestored,
    RecordTrashed,
    RecordTypeChanged,
    RecordTypeDeleted,
    RecordUpdated,
)
from sm_records.deferred import defer
from sm_records.schema.diff import diff_fields
from sm_records.schema.fields import validate_fields
from sm_records.schema.types import ChangeClass
from sm_records.tenancy import bound_tenant

__all__ = [
    "created",
    "imported",
    "publish",
    "purged",
    "restored",
    "trashed",
    "type_changed",
    "type_deleted",
    "updated",
]


async def _publish_all(bus: Any, events: Sequence[Any]) -> None:
    for event in events:
        await bus.publish(event)


def publish(request: Request, *events: Any) -> None:
    """Queue ``events`` for publication once this request has committed.

    A no-op when the host has no bus — ``app.state.sm`` is the framework's,
    and a harness that mounted this module's routers by hand may not have one.
    Silently, because a module that refused to serve a request over an
    optional integration would be the wrong kind of strict.

    One job for all of them, in order: the events of one request describe one
    operation, and a subscriber that sees a cascade's trash events out of order
    cannot tell which record the operator actually asked about.
    """
    flat = [event for event in events if event is not None]
    if not flat:
        return
    bus = getattr(getattr(request.app.state, "sm", None), "event_bus", None)
    if bus is None:
        return
    defer(request, partial(_publish_all, bus, flat))


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
    return RecordPurged(
        type_key=rtype.key,
        tenant_id=_tenant(rtype),
        uuid=record.uuid,
        locale=record.locale,
        translation_group=record.translation_group,
    )


def imported(rtype: Any, written: Iterable[tuple[str, Any]]) -> list[Any]:
    """The events of one import file — one per row that wrote, in file order.

    ``written`` is ``(action, record)`` per successful row, which is what
    ``services.import_.import_records`` collects into the list a caller hands
    it. A row that was skipped as unchanged, or that failed, produces nothing:
    the file mentioned it, the database did not change because of it.
    """
    out: list[Any] = []
    for action, record in written:
        out.append(
            created(rtype, record)
            if action == "created"
            else updated(rtype, record, status_before=record.status.value)
        )
    return out


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


def type_deleted(type_key: str, records: Sequence[Any], collection: str | None = None) -> list[Any]:
    """``RecordTypeDeleted`` plus one ``RecordPurged`` per record that went
    with it — the records first, so a subscriber that drops its own rows per
    record and then forgets the type sees them in that order.

    The purge events carry what the rows held, because after this there is
    nothing to read them from. ``collection`` is accepted and unused for now;
    the table set a record lived in is not part of any event, since a
    subscriber addresses records by ``(type_key, uuid)`` exactly as the API
    does.

    The tenant is the bound one. The type row is deleted by the time this is
    called, and the request that deleted it was bound to the row's tenant.
    """
    tenant = bound_tenant()
    events: list[Any] = [
        RecordPurged(
            type_key=type_key,
            tenant_id=tenant,
            uuid=record.uuid,
            locale=record.locale,
            translation_group=record.translation_group,
        )
        for record in records
    ]
    events.append(RecordTypeDeleted(type_key=type_key, tenant_id=tenant, purged=len(records)))
    return events
