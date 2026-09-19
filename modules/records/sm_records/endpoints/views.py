"""Inertia view endpoints for the Records admin screens, under ``VIEW_PREFIX``.

Every screen here only *reads* through Inertia — writes go through the JSON
API via ``fetch()`` (design §12), so this module never imports the write side
of the contracts. Route order matters for the two-segment paths: ``/{key}/new``
is declared before ``/{key}/{uuid}``, or a request for the "new record" screen
would be swallowed by the generic editor route with ``uuid == "new"``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from inertia import InertiaResponse
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import constants
from sm_records.contracts.schemas import (
    RecordPage,
    record_list_read,
    record_read,
    type_read,
)
from sm_records.deps import (
    get_settings,
    load_type,
    parse_sorts,
    parse_view_filters,
    request_db,
    require_manage_types,
    require_view,
)
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
async def type_list(inertia: InertiaDep, db: AsyncSession = Depends(request_db)) -> InertiaResponse:
    rtypes = await type_service.list_types(db)
    types = [
        type_read(rtype, *await type_service.record_counts(db, rtype)).model_dump(mode="json")
        for rtype in rtypes
    ]
    return await inertia.render(constants._PAGE_TYPES, {"types": types})


def _editor_context(request: Request, rtypes: list[RecordType]) -> dict[str, object]:
    """What the schema editor needs besides the type: the relation-target
    choices and the role names ``allowed_roles`` can be drawn from. Roles come
    from the framework's registry rather than a module list, so a role added
    by another module is offered here without this one knowing it."""
    registry = getattr(getattr(request.app.state, "sm", None), "permissions", None)
    role_map = getattr(registry, "role_map", None) or {}
    return {
        "target_types": [{"key": t.key, "label": t.label} for t in rtypes],
        "roles": sorted(role_map),
    }


# Declared before the ``/{key}`` family: ``types`` is a reserved type key
# (constants.RESERVED_TYPE_KEYS) precisely so these two never lose to it.
#
# Both carry ``require_manage_types`` on top of the router's ``require_view``:
# the screen renders the whole type definition, its ``allowed_roles`` and the
# install's role list, and every button on it calls an API that already
# requires ``records.manage_types``. A ``records.view`` holder reaching it saw
# all of that and could press none of it.
@router.get("/types/new", response_model=None, dependencies=[require_manage_types])
async def type_new(
    request: Request, inertia: InertiaDep, db: AsyncSession = Depends(request_db)
) -> InertiaResponse:
    rtypes = await type_service.list_types(db)
    return await inertia.render(
        constants._PAGE_TYPE_EDITOR,
        {"type": None, **_editor_context(request, rtypes)},
    )


@router.get("/types/{key}", response_model=None, dependencies=[require_manage_types])
async def type_edit(
    request: Request,
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
) -> InertiaResponse:
    rtypes = await type_service.list_types(db)
    live, trashed = await type_service.record_counts(db, rtype)
    return await inertia.render(
        constants._PAGE_TYPE_EDITOR,
        {
            "type": type_read(rtype, live, trashed).model_dump(mode="json"),
            **_editor_context(request, rtypes),
        },
    )


@router.get("/{key}/new", response_model=None)
async def record_new(
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
) -> InertiaResponse:
    counts = await type_service.record_counts(db, rtype)
    return await inertia.render(
        constants._PAGE_RECORD_EDITOR,
        {"type": type_read(rtype, *counts).model_dump(mode="json"), "record": None},
    )


@router.get("/{key}/{uuid}", response_model=None)
async def record_edit(
    uuid: str,
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
) -> InertiaResponse:
    counts = await type_service.record_counts(db, rtype)
    record = await record_service.get_record(db, rtype, uuid)
    return await inertia.render(
        constants._PAGE_RECORD_EDITOR,
        {
            "type": type_read(rtype, *counts).model_dump(mode="json"),
            "record": record_read(rtype, record).model_dump(mode="json"),
        },
    )


@router.get("/{key}", response_model=None)
async def record_list(
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    page: int = Query(default=1, ge=1),
    parsed: tuple[list[Filter], str | None] = Depends(parse_view_filters),
    sorts: list[Sort] = Depends(parse_sorts),
) -> InertiaResponse:
    """First page, deep-linkable via the same ``page``/``sort``/``filter``
    grammar as ``GET /api/records/types/{key}/records`` — the UI reads the
    list client-side thereafter, but the initial render has to match what a
    shared URL promises."""
    counts = await type_service.record_counts(db, rtype)
    effective_sorts = list(sorts) if sorts else list(_DEFAULT_SORTS)
    page_size = max(min(settings.default_page_size, settings.max_page_size), 1)
    filters, malformed = parsed
    errors: dict[str, str] = {}
    items: list = []
    total = 0
    if malformed is not None:
        # A ``?filter=`` term that does not parse at all, which the API answers
        # with a 400 raised from the dependency. Here it joins the same
        # ``errors`` bag a refused-but-well-formed filter uses, for the same
        # reason: this is a page navigation, and a bare status code is an
        # Inertia error modal over a screen that already knows how to say what
        # is wrong with a filter.
        errors["filter"] = malformed
    else:
        try:
            items, total = await record_service.list_records(
                db, rtype, settings=settings, filters=filters, sorts=effective_sorts, page=page
            )
        except QueryError as exc:
            # A page navigation, not an API call: Inertia reserves 409 for its
            # own asset-version handshake and shows any other error status in a
            # modal, so a filter on a field that is mid-reindex (design §8.5),
            # unknown or unindexed cannot be a status code here. The screen
            # renders empty with the reason in Inertia's own ``errors`` bag —
            # the same channel form validation uses — and shows it inline.
            items, total = [], 0
            errors["filter"] = exc.reason
    records_page = RecordPage(
        # One lenient read per row and no per-row validation — see
        # ``contracts.schemas.record_list_read``.
        items=record_list_read(rtype, items),
        total=total,
        page=page,
        page_size=page_size,
    )
    # ``errors`` is sent on every render, empty or not: the list refetches
    # with ``only: ["records", "errors"]`` and Inertia merges partial props
    # over the page it has, so a prop that is simply absent when the filter
    # is clean would leave the previous request's notice on screen.
    props: dict[str, object] = {
        "type": type_read(rtype, *counts).model_dump(mode="json"),
        "records": records_page.model_dump(mode="json"),
        "errors": errors,
    }
    return await inertia.render(constants._PAGE_RECORD_LIST, props)


__all__ = ["router"]
