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

from sm_records import constants, locales, tenancy
from sm_records.contracts.schemas import (
    record_list_read,
    record_read,
    type_read,
)
from sm_records.deps import (
    MAX_PAGE,
    caller_roles,
    get_settings,
    has_edit_permission,
    load_allowed_type,
    parse_sorts,
    parse_trashed,
    parse_view_filters,
    request_db,
    require_view,
)
from sm_records.endpoints import _list_view, views_types
from sm_records.endpoints.api._errors import RecordsViewErrorRoute
from sm_records.endpoints.api.translations import translations_of
from sm_records.index.query import Filter, Sort
from sm_records.media import media_props
from sm_records.models import RecordType
from sm_records.services import _relations
from sm_records.services import expand as expand_service
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services.errors import NotFound
from sm_records.settings import RecordsSettings

# ``bind_admin`` first, for the reason ``endpoints.api``'s router gives; it
# covers ``views_types`` too, which is included below.
router = APIRouter(
    route_class=RecordsViewErrorRoute, dependencies=[Depends(tenancy.bind_admin), require_view]
)
# First, and that is not cosmetic: ``/types/new`` and ``/types/{key}`` must be
# matched before the generic ``/{key}`` record list below, and Starlette
# matches in registration order.
router.include_router(views_types.router)

_DEFAULT_SORTS: tuple[Sort, ...] = (Sort(field="position"), Sort(field="updated_at", desc=True))
"""Design plan's default for the record list: hand-ordered types read by
``position`` first, everything else falls back to most-recently-touched."""


def _locale_props(settings: RecordsSettings) -> dict[str, object]:
    """What the editor's Languages panel needs besides the record.

    Configuration, not data: ``content_locales`` and ``default_content_locale``
    are DB-backed settings (§4.2), so the browser has no other way to know
    which languages the panel should offer a row for. The type's own
    ``translatable`` arrives inside ``type`` and decides whether the panel is
    rendered at all.
    """
    return {
        "content_locales": list(locales.supported(settings)),
        "default_locale": locales.default(settings),
    }


@router.get("/{key}/new", response_model=None)
async def record_new(
    request: Request,
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> InertiaResponse:
    """``load_allowed_type`` here and on the two screens below: design §10's
    ``allowed_roles`` narrow the record surface, views included, or the same
    caller reads on one screen what the JSON API refuses them on the next.

    ``translations`` is an empty list rather than absent: the record does not
    exist yet, so it has no group — but the panel reads one prop shape on both
    screens, and an absent key would leave it rendering the previous page's."""
    counts = await type_service.record_counts(db, rtype)
    return await inertia.render(
        constants._PAGE_RECORD_EDITOR,
        {
            "type": type_read(rtype, *counts).model_dump(mode="json"),
            "record": None,
            "translations": [],
            "media_api": media_props(request),
            **_locale_props(settings),
            **tenancy.view_props(request),
        },
    )


@router.get("/{key}/{uuid}", response_model=None)
async def record_edit(
    request: Request,
    uuid: str,
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> InertiaResponse:
    """The editor, with its relation fields already resolved.

    Expansion is not optional here for the same reason it is not on the list
    (§9): a relation picker showing stored UUIDs is not an editor, and a
    second request per field to turn them into titles is the round-trip
    ``?expand=`` exists to avoid.

    ``translations`` is filled unconditionally here, unlike on the JSON API
    where it costs ``?translations=true`` (§4.4): this screen renders the
    Languages panel on every load, and a second request to populate it is the
    round trip the prop exists to avoid. One query, for one record.

    **Unconditionally, except on a host that publishes in one language** (S1).
    The panel is rendered only when ``content_locales`` has more than one entry
    (``pages/RecordEditor.tsx``), so on a monolingual install the query fills a
    prop nothing reads — the same "inert when unused" rule
    :func:`~sm_records.services._translations.published_siblings` applies to the
    public read. The explicit routes (``?translations=true`` and
    ``GET …/translations``) are untouched: a caller that asked for the group
    gets it whatever the install publishes in.

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
    translations = (
        [] if len(locales.supported(settings)) == 1 else await translations_of(db, rtype, record)
    )
    return await inertia.render(
        constants._PAGE_RECORD_EDITOR,
        {
            "type": type_read(rtype, *counts).model_dump(mode="json"),
            "record": record_read(
                rtype, record, expanded=expanded[record.uuid], translations=translations
            ).model_dump(mode="json"),
            "translations": [item.model_dump(mode="json") for item in translations],
            "referrer_count": await _relations.referrer_count(db, record),
            # Where the ``media`` picker lists and uploads (:mod:`sm_records.media`),
            # or ``None`` for the plain text box. Also on the new-record screen.
            "media_api": media_props(request),
            **_locale_props(settings),
            **tenancy.view_props(request),
        },
    )


@router.get("/{key}", response_model=None)
async def record_list(
    request: Request,
    inertia: InertiaDep,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    page: int = Query(default=1, ge=1, le=MAX_PAGE),
    page_size: int | None = Query(default=None, ge=1),
    parsed: tuple[list[Filter], str | None] = Depends(parse_view_filters),
    sorts: list[Sort] = Depends(parse_sorts),
    trashed: bool = Depends(parse_trashed),
    after: str | None = Query(default=None),
) -> InertiaResponse:
    """First page, deep-linkable via the same ``page``/``after``/``sort``/
    ``filter`` grammar as ``GET /api/records/types/{key}/records`` — a shared
    URL has to render what it promises. ``?trashed=true`` (``records.edit``
    only, see ``parse_trashed``) lists the trash instead — the only way the
    admin ever enumerates soft-deleted rows to restore one (FAIL-3).

    ``?after=<cursor>`` is the footer's way past ``max_count``, where the
    numbered pager stops (``_list_view``): the page comes back with
    ``page: null`` and the next ``next_cursor``. Every refusal the API
    answers with a 400 — a malformed filter, a refused field, a cursor that
    does not decode or belongs to another sort, ``page`` and ``after``
    together — is a reason in ``errors["filter"]`` here, rendered as the
    list's notice rather than an error modal."""
    counts = await type_service.record_counts(db, rtype)
    effective_sorts = list(sorts) if sorts else list(_DEFAULT_SORTS)
    # ``?page_size=`` the same way the JSON API takes it, clamped to
    # ``max_page_size`` rather than refused: the list footer offers 25/50/100
    # (UX-R18) and writes the choice into the URL, which is where every other
    # piece of this screen's state already lives.
    size = settings.clamp_page_size(page_size)
    filters, malformed = parsed
    cursor = after or None
    items, total, capped, next_cursor, refused = await _list_view.run_listing(
        db,
        rtype,
        settings=settings,
        filters=filters,
        malformed=malformed,
        sorts=effective_sorts,
        page=page,
        page_size=size,
        trashed=trashed,
        after=cursor,
    )
    errors: dict[str, str] = {} if refused is None else {"filter": refused}
    # Always, for every relation column the screen renders (§9: the generic
    # list is the one caller that always expands). One batched query per
    # relation field for the whole page — never one per row, which is what
    # ``record_list_read`` takes the finished map rather than a session for.
    expanded = await expand_service.expand(
        db, rtype, items, expand_service.relation_field_keys(rtype), roles=caller_roles(request)
    )
    records_page = _list_view.RecordListViewPage(
        # One lenient read per row and no per-row validation — see
        # ``contracts.schemas.record_list_read``.
        items=record_list_read(rtype, items, expanded=expanded),
        total=total,
        total_capped=capped,
        next_cursor=next_cursor,
        page=None if cursor else page,
        page_size=size,
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
        # The import menu refuses an over-size file before uploading it, and
        # says the limit in its dialog (review R9/M13). The browser has no
        # other way to know a DB-backed setting.
        "max_import_bytes": settings.max_import_bytes,
        # U14/Missing-15: a public type's public URL is otherwise visible
        # nowhere but the type editor (``_editor_context``'s own comment) —
        # an admin who lands on the list first (the far more common path,
        # per the hub's own row-links-to-records design) had no way to
        # verify the thing they turned on without a detour through "Edit
        # schema". Same DB-backed setting, same reason the browser can't
        # derive it on its own.
        "public_route_prefix": settings.public_route_prefix,
        # The ``media`` column's thumbnails resolve ids through it.
        "media_api": media_props(request),
        # No default locale filter anywhere above: the admin list defaults to
        # **all** locales (§4.4), because an editor's question is "what
        # exists", not "what exists in English". The selector narrows it with
        # an ordinary ``?filter=locale:eq:de``.
        **_locale_props(settings),
        # Which tenant this screen reads, and whether the host has several
        # (tenancy design §J) — read-only; on every records screen.
        **tenancy.view_props(request),
    }
    return await inertia.render(constants._PAGE_RECORD_LIST, props)


__all__ = ["router"]
