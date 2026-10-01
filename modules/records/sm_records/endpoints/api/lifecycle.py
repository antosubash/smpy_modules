"""Trash, restore and purge — a record's existence rather than its content.

Split out of :mod:`sm_records.endpoints.api.records` for the 300-line cap,
along the seam the services layer already draws between ``records`` and
``_lifecycle``. The router carries the same ``/types/{key}`` prefix and is
included beside it, so the URLs are unchanged.

All three publish (:mod:`sm_records.events`), and the trash is the one that
could not be published from anywhere else: a delete cascades into records of
types the URL never names (design §9), and only the list
``soft_delete_record`` returns says which.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.contracts.schemas import RecordRead, record_read
from sm_records.deps import (
    actor,
    caller_roles,
    check_type_roles,
    get_settings,
    load_type,
    request_db,
    require_edit,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.endpoints.api._responses import WRITE, responses
from sm_records.models import RecordType
from sm_records.services import records as record_service
from sm_records.settings import RecordsSettings

router = APIRouter(
    prefix="/types/{key}",
    route_class=RecordsErrorRoute,
    responses=responses(*WRITE),
)


@router.delete("/records/{uuid}", status_code=204, dependencies=[require_edit])
async def delete_record(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> None:
    check_type_roles(request, rtype)
    record = await record_service.get_record(db, rtype, uuid)
    # ``roles`` and not only ``check_type_roles``: the delete may cascade into
    # — or rewrite — records of types this URL never names, and design §10's
    # narrowing has to reach those too. See ``services._lifecycle``.
    cascade = await record_service.soft_delete_record(
        db, rtype, record, actor=who, settings=settings, roles=caller_roles(request)
    )
    events.publish(request, *events.trashed(rtype, record, cascade))


@router.post("/records/{uuid}/restore", response_model=RecordRead, dependencies=[require_edit])
async def restore_record(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> RecordRead:
    check_type_roles(request, rtype)
    record = await record_service.get_deleted_record(db, rtype, uuid)
    restored = await record_service.restore_record(db, rtype, record, settings=settings, actor=who)
    events.publish(request, events.restored(rtype, restored))
    return record_read(rtype, restored)


@router.delete("/records/{uuid}/purge", status_code=204, dependencies=[require_edit])
async def purge_record(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
) -> None:
    check_type_roles(request, rtype)
    record = await record_service.get_deleted_record(db, rtype, uuid)
    # Built before the purge: afterwards the row is expunged and the uuid it
    # names is the one thing a subscriber cannot look up any more.
    purged = events.purged(rtype, record)
    await record_service.hard_delete_record(db, rtype, record)
    events.publish(request, purged)
