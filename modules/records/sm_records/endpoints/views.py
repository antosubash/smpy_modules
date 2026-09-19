"""Inertia view endpoints for the Records admin screens, under ``VIEW_PREFIX``.

Every screen here only *reads* through Inertia — writes go through the JSON
API via ``fetch()`` (design §12), so this module never imports the write side
of the contracts. Route order matters for the two-segment paths: ``/{key}/new``
is declared before ``/{key}/{uuid}``, or a request for the "new record" screen
would be swallowed by the generic editor route with ``uuid == "new"``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from inertia import InertiaResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import constants
from sm_records.contracts.schemas import RecordPage, record_read, type_read
from sm_records.deps import get_settings, load_type, parse_filters, parse_sorts, require_view
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.index.query import Filter, QueryError, Sort
from sm_records.models import RecordType
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.settings import RecordsSettings

router = APIRouter(route_class=RecordsErrorRoute, dependencies=[require_view])

_DEFAULT_SORTS: tuple[Sort, ...] = (Sort(field="position"), Sort(field="updated_at", desc=True))
"""Design plan's default for the record list: hand-ordered types read by
``position`` first, everything else falls back to most-recently-touched."""


@router.get("/", response_model=None)
async def type_list(inertia: InertiaDep, db: AsyncSession = Depends(get_db)) -> InertiaResponse:
    rtypes = await type_service.list_types(db)
    types = [
        type_read(rtype, await type_service.record_count(db, rtype)).model_dump(mode="json")
        for rtype in rtypes
    ]
    return await inertia.render(constants._PAGE_TYPES, {"types": types})


@router.get("/{key}/new", response_model=None)
async def record_new(
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(get_db),
) -> InertiaResponse:
    held = await type_service.record_count(db, rtype)
    return await inertia.render(
        constants._PAGE_RECORD_EDITOR,
        {"type": type_read(rtype, held).model_dump(mode="json"), "record": None},
    )


@router.get("/{key}/{uuid}", response_model=None)
async def record_edit(
    uuid: str,
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(get_db),
) -> InertiaResponse:
    held = await type_service.record_count(db, rtype)
    record = await record_service.get_record(db, rtype, uuid)
    return await inertia.render(
        constants._PAGE_RECORD_EDITOR,
        {
            "type": type_read(rtype, held).model_dump(mode="json"),
            "record": record_read(rtype, record).model_dump(mode="json"),
        },
    )


@router.get("/{key}", response_model=None)
async def record_list(
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(get_db),
    settings: RecordsSettings = Depends(get_settings),
    page: int = Query(default=1, ge=1),
    filters: list[Filter] = Depends(parse_filters),
    sorts: list[Sort] = Depends(parse_sorts),
) -> InertiaResponse:
    """First page, deep-linkable via the same ``page``/``sort``/``filter``
    grammar as ``GET /api/records/types/{key}/records`` — the UI reads the
    list client-side thereafter, but the initial render has to match what a
    shared URL promises."""
    held = await type_service.record_count(db, rtype)
    effective_sorts = list(sorts) if sorts else list(_DEFAULT_SORTS)
    page_size = max(min(settings.default_page_size, settings.max_page_size), 1)
    errors: dict[str, str] = {}
    try:
        items, total = await record_service.list_records(
            db, rtype, settings=settings, filters=filters, sorts=effective_sorts, page=page
        )
    except QueryError as exc:
        # A page navigation, not an API call: Inertia reserves 409 for its own
        # asset-version handshake and shows any other error status in a modal,
        # so a filter on a field that is mid-reindex (design §8.5), unknown or
        # unindexed cannot be a status code here. The screen renders empty
        # with the reason in Inertia's own ``errors`` bag — the same channel
        # form validation uses — and the page shows it inline.
        items, total = [], 0
        errors["filter"] = exc.reason
    records_page = RecordPage(
        items=[record_read(rtype, record) for record in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    props: dict[str, object] = {
        "type": type_read(rtype, held).model_dump(mode="json"),
        "records": records_page.model_dump(mode="json"),
    }
    if errors:
        props["errors"] = errors
    return await inertia.render(constants._PAGE_RECORD_LIST, props)


__all__ = ["router"]
