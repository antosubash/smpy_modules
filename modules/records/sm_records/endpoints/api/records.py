"""Record CRUD endpoints — the document half of the JSON API.

Every write here does two things no framework permission expresses on its
own: it requires ``records.edit`` (the router-level dependency) *and* it
passes ``check_type_roles`` — design §10's per-type ``allowed_roles``
narrowing, which has to be called explicitly because it depends on the
specific ``RecordType`` a path names, not on anything ``RequiresPermission``
can see at route-registration time.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import constants
from sm_records.contracts.schemas import (
    RecordCreate,
    RecordPage,
    RecordRead,
    RecordUpdate,
    record_list_read,
    record_read,
)
from sm_records.deps import (
    MAX_PAGE,
    PageCursor,
    actor,
    caller_roles,
    check_type_roles,
    get_settings,
    load_allowed_type,
    load_type,
    parse_cursor,
    parse_expand,
    parse_filters,
    parse_sorts,
    parse_trashed,
    request_db,
    require_edit,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.endpoints.api.translations import translations_of
from sm_records.index.query import CursorError, Filter, Sort
from sm_records.models import RecordStatus, RecordType
from sm_records.services import _duplicates
from sm_records.services import expand as expand_service
from sm_records.services import records as record_service
from sm_records.services.errors import ValidationFailed
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


@router.get("/records", response_model=RecordPage, dependencies=[require_view])
async def list_records(
    request: Request,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    page: int = Query(default=1, ge=1, le=MAX_PAGE),
    page_size: int | None = Query(default=None, ge=1),
    cursor: PageCursor = Depends(parse_cursor),
    filters: list[Filter] = Depends(parse_filters),
    sorts: list[Sort] = Depends(parse_sorts),
    trashed: bool = Depends(parse_trashed),
    expand: list[str] = Depends(parse_expand),
) -> RecordPage:
    """The type's records, or — with ``?trashed=true`` — only its trash.

    There is no other way to enumerate soft-deleted records: without it a
    trashed record is reachable only by a caller who kept its uuid, which
    makes "trash and restore" a feature you can use once. ``trashed`` costs
    ``records.edit`` (``deps.parse_trashed``); every item comes back with
    ``is_deleted: true``, so the shape needs nothing new.

    ``?expand=a,b`` resolves those relation fields for the whole page in one
    query each (design §9) — never per row, which is the difference between a
    list screen and fifty round trips.

    ``?after=<cursor>`` pages by keyset instead of ``OFFSET`` and
    ``?total=false`` drops the count; both are ``deps.parse_cursor``, which
    also refuses ``page`` and ``after`` together. A malformed cursor, or one
    replayed under a different sort, is a 400 — it cannot be honoured and
    guessing would silently skip rows.

    ``load_allowed_type`` and not ``load_type``: the type's ``allowed_roles``
    narrow this read exactly as they narrow the writes below it (§10).
    """
    try:
        result = await record_service.list_records(
            db,
            rtype,
            settings=settings,
            filters=filters,
            sorts=sorts,
            page=page,
            page_size=page_size,
            trashed=trashed,
            after=cursor.after,
            with_total=cursor.with_total,
        )
    except CursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    expanded = (
        await expand_service.expand(db, rtype, result.items, expand, roles=caller_roles(request))
        if expand
        else None
    )
    return RecordPage(
        # ``record_list_read``, not a comprehension over ``record_read``: a
        # list reads each row leniently but does not validate it, so a page of
        # fifty costs one compiled-model pass rather than fifty (``invalid`` is
        # the record editor's badge — see the contracts module).
        items=record_list_read(rtype, result.items, expanded=expanded),
        total=result.total,
        total_capped=result.total_capped,
        next_cursor=result.next_cursor,
        page=page,
        page_size=settings.clamp_page_size(page_size),
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
        locale=body.locale,
    )
    return record_read(rtype, record)


@router.get("/records/{uuid}", response_model=RecordRead, dependencies=[require_view])
async def get_record(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
    expand: list[str] = Depends(parse_expand),
    with_translations: bool = Query(default=False, alias=constants.TRANSLATIONS_PARAM),
) -> RecordRead:
    """One record, with ``?expand=`` resolving the relation fields it names
    to depth one (design §9). A key that is not a relation field of the type
    is a 400 naming it — ``services.expand`` refuses it with the same
    ``QueryError`` the filter grammar uses for an unknown field.

    ``?translations=true`` adds the record's translation group — itself and
    every sibling, trash included (Phase 5 §4.4). One extra query, and opt-in
    rather than always, because the *list* must never pay it: there it would be
    one query per row for a panel only the editor shows.

    ``invalid`` is topped up with the duplicate check
    (``services._duplicates.conflicts_for``) for the same reason the validator
    runs here and not on the list: a ``unique`` field forced on over existing
    duplicates leaves a record whose payload validates and which no write is
    accepted for, and the editor is where an operator finds that out. One
    existence check per filled ``unique`` field, which is what saving the same
    record already costs.
    """
    record = await record_service.get_record(db, rtype, uuid)
    expanded = (
        await expand_service.expand(db, rtype, [record], expand, roles=caller_roles(request))
        if expand
        else None
    )
    return record_read(
        rtype,
        record,
        expanded=None if expanded is None else expanded[record.uuid],
        translations=await translations_of(db, rtype, record) if with_translations else None,
        extra_invalid=await _duplicates.conflicts_for(db, rtype, record),
    )


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
    # Declared on ``RecordUpdate`` so it is *refused* rather than dropped: a
    # client sending back the record it just read would otherwise get a 200 for
    # a language change that never happened. A record's language is fixed for
    # its lifetime — ``POST /records/{uuid}/translations`` is the only way to
    # have the same content in another one (Phase 5 §4.3).
    if constants.LOCALE_PARAM in body.model_fields_set:
        problem = (
            "locale is fixed for a record's lifetime — create a translation "
            "instead (POST /records/{uuid}/translations)"
        )
        raise ValidationFailed(problem, [{"field": constants.LOCALE_PARAM, "message": problem}])
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
