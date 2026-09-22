"""Record revision endpoints — reading the history of one document.

Split out of :mod:`sm_records.endpoints.api.records` for the 300-line cap, and
the seam is the one the services layer already draws: ``records`` is what a
document *is* right now, ``revisions`` is what it used to be. The router
carries the same ``/types/{key}`` prefix and is included beside it, so the
URLs are unchanged — ``/api/records/types/{key}/records/{uuid}/revisions``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.schemas import (
    RecordRead,
    RecordRevisionDetailRead,
    RecordRevisionRestoreRequest,
    RevisionListResponse,
    record_read,
    record_revision_detail_read,
    revision_read,
)
from sm_records.deps import (
    actor,
    check_type_roles,
    get_settings,
    load_allowed_type,
    load_type,
    request_db,
    require_edit,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.models import RecordType, tables_of
from sm_records.services import records as record_service
from sm_records.services import revisions as revision_service
from sm_records.services.errors import NotFound
from sm_records.settings import RecordsSettings

router = APIRouter(prefix="/types/{key}", route_class=RecordsErrorRoute)


@router.get(
    "/records/{uuid}/revisions", response_model=RevisionListResponse, dependencies=[require_view]
)
async def list_revisions(
    uuid: str,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
) -> RevisionListResponse:
    """``load_allowed_type``: a revision is the record's own past payload, so
    a type whose ``allowed_roles`` exclude the caller hides its history with
    its records (§10)."""
    record = await record_service.get_record(db, rtype, uuid)
    revisions = await revision_service.list_revisions(db, record)
    return RevisionListResponse(items=[revision_read(revision) for revision in revisions])


@router.get(
    "/records/{uuid}/revisions/{revision_id}",
    response_model=RecordRevisionDetailRead,
    dependencies=[require_view],
)
async def get_record_revision(
    uuid: str,
    revision_id: int,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
) -> RecordRevisionDetailRead:
    """The read-only preview before restoring: the list entry plus the
    payload it snapshotted. A revision id from another record is a 404 — see
    ``services.revisions.restore``'s own docstring for why that is a 404
    rather than a 403: nothing else in the API takes a revision id, so there
    is no resource here the caller is being refused access to.

    The lookup is against ``tables_of(record).revision``, the type's own
    revision log, not the global ``RecordRevision``: ids restart per table, so
    the global class would happily return an unrelated record's snapshot for a
    collection type."""
    record = await record_service.get_record(db, rtype, uuid)
    revision_table = tables_of(record).revision
    stmt = select(revision_table).where(
        revision_table.id == revision_id, revision_table.record_id == record.id
    )
    revision = (await db.execute(stmt)).scalars().first()
    if revision is None:
        raise NotFound(f"record {uuid} has no revision {revision_id!r}")
    return record_revision_detail_read(revision)


@router.post(
    "/records/{uuid}/revisions/{revision_id}/restore",
    response_model=RecordRead,
    dependencies=[require_edit],
)
async def restore_record_revision(
    uuid: str,
    revision_id: int,
    body: RecordRevisionRestoreRequest,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> RecordRead:
    """Write a past revision's payload back as a new version of the record —
    ``records.edit`` plus the same ``allowed_roles`` narrowing as every other
    record write (design §10), since a restore is a write like any other. A
    payload that no longer fits the *current* schema is the usual ``422``
    (``services.revisions.restore``'s own docstring explains why validating
    against "now" rather than "then" is the correct answer, not a gap)."""
    check_type_roles(request, rtype)
    record = await record_service.get_record(db, rtype, uuid)
    restored = await revision_service.restore(
        db,
        rtype,
        record,
        revision_id=revision_id,
        expected_version=body.expected_version,
        settings=settings,
        actor=who,
    )
    return record_read(rtype, restored)
