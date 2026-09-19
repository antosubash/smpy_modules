"""Record CRUD endpoints — the document half of the JSON API.

Every write here does two things no framework permission expresses on its
own: it requires ``records.edit`` (the router-level dependency) *and* it
passes ``check_type_roles`` — design §10's per-type ``allowed_roles``
narrowing, which has to be called explicitly because it depends on the
specific ``RecordType`` a path names, not on anything ``RequiresPermission``
can see at route-registration time.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.schemas import (
    RecordCreate,
    RecordPage,
    RecordRead,
    RecordRevisionDetailRead,
    RecordRevisionRestoreRequest,
    RecordUpdate,
    RevisionListResponse,
    record_list_read,
    record_read,
    record_revision_detail_read,
    revision_read,
)
from sm_records.deps import (
    actor,
    caller_roles,
    check_type_roles,
    get_settings,
    load_type,
    parse_filters,
    parse_sorts,
    request_db,
    require_edit,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.index.query import Filter, Sort
from sm_records.models import RecordRevision, RecordStatus, RecordType
from sm_records.services import records as record_service
from sm_records.services import revisions as revision_service
from sm_records.services.errors import NotFound, ValidationFailed
from sm_records.settings import RecordsSettings

router = APIRouter(prefix="/types/{key}", route_class=RecordsErrorRoute)


def _status(raw: str | None) -> RecordStatus | None:
    if raw is None:
        return None
    try:
        return RecordStatus(raw)
    except ValueError as exc:
        raise ValidationFailed(
            f"status must be 'draft' or 'published', not {raw!r}",
            [{"field": "status", "message": f"unknown status {raw!r}"}],
        ) from exc


def _page_size(settings: RecordsSettings, page_size: int | None) -> int:
    return max(min(page_size or settings.default_page_size, settings.max_page_size), 1)


@router.get("/records", response_model=RecordPage, dependencies=[require_view])
async def list_records(
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1),
    filters: list[Filter] = Depends(parse_filters),
    sorts: list[Sort] = Depends(parse_sorts),
) -> RecordPage:
    items, total = await record_service.list_records(
        db, rtype, settings=settings, filters=filters, sorts=sorts, page=page, page_size=page_size
    )
    return RecordPage(
        # ``record_list_read``, not a comprehension over ``record_read``: a
        # list reads each row leniently but does not validate it, so a page of
        # fifty costs one compiled-model pass rather than fifty (``invalid`` is
        # the record editor's badge — see the contracts module).
        items=record_list_read(rtype, items),
        total=total,
        page=page,
        page_size=_page_size(settings, page_size),
    )


@router.post("/records", response_model=RecordRead, status_code=201, dependencies=[require_edit])
async def create_record(
    body: RecordCreate,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> RecordRead:
    check_type_roles(request, rtype)
    record = await record_service.create_record(
        db,
        rtype,
        data=body.data,
        settings=settings,
        status=_status(body.status) or RecordStatus.DRAFT,
        slug=body.slug,
        position=body.position,
        actor=who,
    )
    return record_read(rtype, record)


@router.get("/records/{uuid}", response_model=RecordRead, dependencies=[require_view])
async def get_record(
    uuid: str, rtype: RecordType = Depends(load_type), db: AsyncSession = Depends(request_db)
) -> RecordRead:
    record = await record_service.get_record(db, rtype, uuid)
    return record_read(rtype, record)


@router.put("/records/{uuid}", response_model=RecordRead, dependencies=[require_edit])
async def update_record(
    uuid: str,
    body: RecordUpdate,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> RecordRead:
    check_type_roles(request, rtype)
    record = await record_service.get_record(db, rtype, uuid)
    updated = await record_service.update_record(
        db,
        rtype,
        record,
        expected_version=body.expected_version,
        data=body.data,
        settings=settings,
        status=_status(body.status),
        slug=body.slug,
        position=body.position,
        actor=who,
    )
    return record_read(rtype, updated)


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
    await record_service.soft_delete_record(
        db, rtype, record, actor=who, settings=settings, roles=caller_roles(request)
    )


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
    await record_service.hard_delete_record(db, rtype, record)


@router.get(
    "/records/{uuid}/revisions", response_model=RevisionListResponse, dependencies=[require_view]
)
async def list_revisions(
    uuid: str, rtype: RecordType = Depends(load_type), db: AsyncSession = Depends(request_db)
) -> RevisionListResponse:
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
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
) -> RecordRevisionDetailRead:
    """The read-only preview before restoring: the list entry plus the
    payload it snapshotted. A revision id from another record is a 404 — see
    ``services.revisions.restore``'s own docstring for why that is a 404
    rather than a 403: nothing else in the API takes a revision id, so there
    is no resource here the caller is being refused access to."""
    record = await record_service.get_record(db, rtype, uuid)
    stmt = select(RecordRevision).where(
        RecordRevision.id == revision_id, RecordRevision.record_id == record.id
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
