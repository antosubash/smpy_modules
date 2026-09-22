"""One action over many records, and emptying the trash.

Both routes are the multi-record face of things ``lifecycle`` and ``records``
already do one at a time, and neither adds a rule of its own: the service
composes the single-record calls (:mod:`sm_records.services.bulk`), so
``allowed_roles``, the ``on_delete`` cascade, the claims, the revisions and
the events are the single-record ones. What this module owns is the two
things only an endpoint can: the ceiling on how many records one request may
name, and publishing one event per record the service reports.

``check_type_roles`` here and ``roles=`` into the service, for the reason
``lifecycle.delete_record`` gives: a trash may cascade into records of types
this URL never names, and design §10's narrowing has to reach those too.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.contracts.bulk import BulkAction, BulkRequest, BulkResult, TrashEmptied
from sm_records.deps import (
    actor,
    caller_roles,
    check_type_roles,
    get_settings,
    load_type,
    parse_filters,
    request_db,
    require_edit,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.endpoints.api._responses import WRITE, responses
from sm_records.index.query import Filter
from sm_records.models import RecordType
from sm_records.services import bulk as bulk_service
from sm_records.services.errors import PayloadTooLarge
from sm_records.settings import RecordsSettings

router = APIRouter(
    prefix="/types/{key}",
    route_class=RecordsErrorRoute,
    responses=responses(*WRITE),
)


def _event_for(action: BulkAction, rtype: RecordType, change: bulk_service.Change) -> list[object]:
    """The events one record's change publishes — the single-record builders.

    A trash yields one per record it reached, cascade included, exactly as
    ``DELETE /records/{uuid}`` does; everything else yields one. The service
    could not build these itself: the bus is the endpoint's (architecture rule
    1), and ``events`` imports Starlette.
    """
    if action is BulkAction.TRASH:
        return list(events.trashed(rtype, change.record, change.cascade))
    if action is BulkAction.RESTORE:
        return [events.restored(rtype, change.record)]
    if action is BulkAction.PURGE:
        return [events.purged(rtype, change.record)]
    return [events.updated(rtype, change.record, status_before=change.status_before or "")]


@router.post("/records/bulk", response_model=BulkResult, dependencies=[require_edit])
async def bulk_records(
    body: BulkRequest,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> BulkResult:
    """Apply one action to every record named — or, if any refuses, to none.

    A refusal is a ``409`` whose ``report`` names each failing uuid with the
    status and message that record alone would have answered, and **nothing is
    written**: the batch is the unit of work and of rollback. That is what
    makes the report actionable — the caller deselects what it lists and sends
    the rest — and what keeps a half-applied ``purge`` from existing at all.

    ``expected_versions`` is optional and partial; see
    :class:`~sm_records.contracts.bulk.BulkRequest`.
    """
    check_type_roles(request, rtype)
    if len(body.uuids) > settings.max_bulk_records:
        # Before a record is touched, like every other ceiling in this module:
        # a limit enforced halfway through is a limit that has already done
        # the work it was meant to refuse.
        raise PayloadTooLarge(
            f"{len(body.uuids)} records named, over the {settings.max_bulk_records}-record "
            "limit for one bulk request"
        )
    result, changes = await bulk_service.apply_bulk(
        db,
        rtype,
        action=body.action,
        uuids=body.uuids,
        expected_versions=body.expected_versions,
        settings=settings,
        actor=who,
        roles=caller_roles(request),
    )
    published: list[object] = []
    for change in changes:
        published.extend(_event_for(body.action, rtype, change))
    events.publish(request, *published)
    return result


@router.post(
    "/records/trash/empty",
    response_model=TrashEmptied,
    dependencies=[require_edit],
    # The one status the router's ``WRITE`` bundle does not carry: this route
    # takes the listing grammar, and a ``?filter=`` naming a field that is not
    # queryable is refused by name exactly as it is on the list itself.
    responses=responses(400),
)
async def empty_trash(
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    filters: list[Filter] = Depends(parse_filters),
) -> TrashEmptied:
    """Purge the type's whole trash, or the part of it a ``?filter=`` names.

    Deliberately outside ``max_bulk_records``: the point of emptying the trash
    is not having to name what is in it, and the purge is set-based rather
    than a pass over ORM instances (:func:`sm_records.services.bulk.empty_trash`).

    ``?filter=`` is the listing grammar's, so "empty what this screen is
    showing" is the query the screen listed it with — index rows survive a
    soft delete (§7.3), which is what makes the trash filterable.

    One ``RecordPurged`` per record, as every other purge publishes: it is the
    only way a subscriber hears about a record that is no longer there to be
    read.
    """
    check_type_roles(request, rtype)
    purged = await bulk_service.empty_trash(db, rtype, filters=filters)
    events.publish(request, *[events.purged(rtype, identity) for identity in purged])
    return TrashEmptied(purged=len(purged), filtered=bool(filters))
