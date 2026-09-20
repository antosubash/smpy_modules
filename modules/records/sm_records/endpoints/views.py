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
    caller_roles,
    get_settings,
    has_edit_permission,
    load_allowed_type,
    load_type,
    parse_sorts,
    parse_trashed,
    parse_view_filters,
    request_db,
    require_manage_types,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.index.query import Filter, QueryError, Sort
from sm_records.models import RecordType
from sm_records.services import _relations
from sm_records.services import expand as expand_service
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services._common import role_blocked
from sm_records.services.errors import NotFound
from sm_records.settings import RecordsSettings

router = APIRouter(route_class=RecordsErrorRoute, dependencies=[require_view])

_DEFAULT_SORTS: tuple[Sort, ...] = (Sort(field="position"), Sort(field="updated_at", desc=True))
"""Design plan's default for the record list: hand-ordered types read by
``position`` first, everything else falls back to most-recently-touched."""


@router.get("/", response_model=None)
async def type_list(
    request: Request, inertia: InertiaDep, db: AsyncSession = Depends(request_db)
) -> InertiaResponse:
    """The same omission ``GET /api/records/types`` makes: a type whose
    ``allowed_roles`` exclude the caller is not a card they can open, so it is
    not a card (§10)."""
    rtypes = [
        rtype
        for rtype in await type_service.list_types(db)
        if not role_blocked(rtype, caller_roles(request))
    ]
    types = [
        type_read(rtype, *await type_service.record_counts(db, rtype)).model_dump(mode="json")
        for rtype in rtypes
    ]
    return await inertia.render(constants._PAGE_TYPES, {"types": types})


def _editor_context(
    request: Request, rtypes: list[RecordType], settings: RecordsSettings
) -> dict[str, object]:
    """What the schema editor needs besides the type: the relation-target
    choices and the role names ``allowed_roles`` can be drawn from. Roles come
    from the framework's registry rather than a module list, so a role added
    by another module is offered here without this one knowing it.

    ``public_route_prefix`` rides along too: it is a DB-backed setting (design
    §11), so the browser has no other way to build the URL the "Public"
    toggle's help text shows once it is switched on.
    """
    registry = getattr(getattr(request.app.state, "sm", None), "permissions", None)
    role_map = getattr(registry, "role_map", None) or {}
    return {
        "target_types": [{"key": t.key, "label": t.label} for t in rtypes],
        "roles": sorted(role_map),
        "public_route_prefix": settings.public_route_prefix,
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
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> InertiaResponse:
    rtypes = await type_service.list_types(db)
    return await inertia.render(
        constants._PAGE_TYPE_EDITOR,
        {"type": None, **_editor_context(request, rtypes, settings)},
    )


@router.get("/types/{key}", response_model=None, dependencies=[require_manage_types])
async def type_edit(
    request: Request,
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> InertiaResponse:
    rtypes = await type_service.list_types(db)
    live, trashed = await type_service.record_counts(db, rtype)
    return await inertia.render(
        constants._PAGE_TYPE_EDITOR,
        {
            "type": type_read(rtype, live, trashed).model_dump(mode="json"),
            **_editor_context(request, rtypes, settings),
        },
    )


@router.get("/{key}/new", response_model=None)
async def record_new(
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
) -> InertiaResponse:
    """``load_allowed_type`` here and on the two screens below: design §10's
    ``allowed_roles`` narrow the record surface, views included, or the same
    caller reads on one screen what the JSON API refuses them on the next."""
    counts = await type_service.record_counts(db, rtype)
    return await inertia.render(
        constants._PAGE_RECORD_EDITOR,
        {"type": type_read(rtype, *counts).model_dump(mode="json"), "record": None},
    )


@router.get("/{key}/{uuid}", response_model=None)
async def record_edit(
    request: Request,
    uuid: str,
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
) -> InertiaResponse:
    """The editor, with its relation fields already resolved.

    Expansion is not optional here for the same reason it is not on the list
    (§9): a relation picker showing stored UUIDs is not an editor, and a
    second request per field to turn them into titles is the round-trip
    ``?expand=`` exists to avoid.

    ``referrer_count`` is the "Referenced by" badge — ``_relations.referrer_count``,
    which is by construction the same number the panel behind it reports as
    ``total`` (both are distinct referring records). Deliberately not part of
    ``RecordRead``: the list screen would pay it per row for a number only
    this screen shows, and the panel is its own endpoint.
    """
    counts = await type_service.record_counts(db, rtype)
    try:
        record = await record_service.get_record(db, rtype, uuid)
    except NotFound:
        # A soft-deleted record 404s from ``get_record`` — the framework's
        # filter hides it. Restore/purge are only reachable from this screen
        # (FAIL-3), so a caller who can edit gets the trashed row instead of
        # a dead end; anyone else still sees the same 404 as before.
        if not await has_edit_permission(request, db):
            raise
        record = await record_service.get_deleted_record(db, rtype, uuid)
    expanded = await expand_service.expand(
        db,
        rtype,
        [record],
        expand_service.relation_field_keys(rtype),
        roles=caller_roles(request),
    )
    return await inertia.render(
        constants._PAGE_RECORD_EDITOR,
        {
            "type": type_read(rtype, *counts).model_dump(mode="json"),
            "record": record_read(rtype, record, expanded=expanded[record.uuid]).model_dump(
                mode="json"
            ),
            "referrer_count": await _relations.referrer_count(db, record),
        },
    )


@router.get("/{key}", response_model=None)
async def record_list(
    request: Request,
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    page: int = Query(default=1, ge=1),
    parsed: tuple[list[Filter], str | None] = Depends(parse_view_filters),
    sorts: list[Sort] = Depends(parse_sorts),
    trashed: bool = Depends(parse_trashed),
) -> InertiaResponse:
    """First page, deep-linkable via the same ``page``/``sort``/``filter``
    grammar as ``GET /api/records/types/{key}/records`` — the UI reads the
    list client-side thereafter, but the initial render has to match what a
    shared URL promises. ``?trashed=true`` (``records.edit`` only, see
    ``parse_trashed``) lists the trash instead — the only way the admin ever
    enumerates soft-deleted rows to restore one (FAIL-3)."""
    counts = await type_service.record_counts(db, rtype)
    effective_sorts = list(sorts) if sorts else list(_DEFAULT_SORTS)
    page_size = settings.clamp_page_size(None)
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
                db,
                rtype,
                settings=settings,
                filters=filters,
                sorts=effective_sorts,
                page=page,
                trashed=trashed,
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
    # Always, for every relation column the screen renders (§9: the generic
    # list is the one caller that always expands). One batched query per
    # relation field for the whole page — never one per row, which is what
    # ``record_list_read`` takes the finished map rather than a session for.
    expanded = await expand_service.expand(
        db, rtype, items, expand_service.relation_field_keys(rtype), roles=caller_roles(request)
    )
    records_page = RecordPage(
        # One lenient read per row and no per-row validation — see
        # ``contracts.schemas.record_list_read``.
        items=record_list_read(rtype, items, expanded=expanded),
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
        "trashed": trashed,
    }
    return await inertia.render(constants._PAGE_RECORD_LIST, props)


__all__ = ["router"]
