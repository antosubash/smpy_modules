"""The two Record **Type** screens — the type list and the schema editor.

Split from :mod:`sm_records.endpoints.views` for the 300-line cap, along the
seam the JSON API already has between ``endpoints/api/types.py`` and
``endpoints/api/records.py``: this module renders the schema, that one renders
the content stored against it.

Its router is included into ``views.router`` **first**, and that ordering is
load-bearing: ``/types/new`` and ``/types/{key}`` have to be matched before the
generic ``/{key}`` record list, which would otherwise swallow them as a type
keyed ``types``. ``constants.RESERVED_TYPE_KEYS`` refuses that key for the same
reason, so the two defences agree.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from inertia import InertiaResponse
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import constants, locales
from sm_records.collections import collections
from sm_records.contracts.schemas import type_read
from sm_records.deps import (
    caller_roles,
    get_settings,
    load_type,
    request_db,
    require_manage_types,
)
from sm_records.endpoints.api._errors import RecordsViewErrorRoute
from sm_records.models import RecordType
from sm_records.services import types as type_service
from sm_records.services._common import role_blocked
from sm_records.settings import RecordsSettings

router = APIRouter(route_class=RecordsViewErrorRoute)


@router.get("/", response_model=None)
async def type_list(
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> InertiaResponse:
    """The same omission ``GET /api/records/types`` makes: a type whose
    ``allowed_roles`` exclude the caller is not a card they can open, so it is
    not a card (§10).

    ``public_route_prefix`` rides along for the same reason
    ``_editor_context`` sends it to the schema editor (Missing-15): a public
    type's URL is otherwise verifiable nowhere but that editor, and the hub
    is where most visits to a type actually start (UX-R13.1's row-links-to-
    records design)."""
    rtypes = [
        rtype
        for rtype in await type_service.list_types(db)
        if not role_blocked(rtype, caller_roles(request))
    ]
    types = [
        type_read(rtype, *await type_service.record_counts(db, rtype)).model_dump(mode="json")
        for rtype in rtypes
    ]
    return await inertia.render(
        constants._PAGE_TYPES,
        {"types": types, "public_route_prefix": settings.public_route_prefix},
    )


def _editor_context(
    request: Request, rtypes: list[RecordType], settings: RecordsSettings
) -> dict[str, object]:
    """What the schema editor needs besides the type: the relation-target
    choices and the role names ``allowed_roles`` can be drawn from. Roles come
    from the framework's registry rather than a module list, so a role added
    by another module is offered here without this one knowing it.

    ``public_route_prefix`` rides along too: it is a DB-backed setting (design
    §11), so the browser has no other way to build the URL the "Public"
    toggle's help text shows once it is switched on. ``content_locales`` is
    there for the same reason: the "Translatable" toggle has to be able to say
    which languages it would be turning on, and that list is configuration the
    browser cannot see.

    ``collections`` is the same kind of fact and the most invisible of them
    all: which collections exist is decided by the *host's Python*
    (Phase 5 §6.1), so it is not derivable from anything the browser holds.
    Empty on a host that declares none, and the new-type form then offers no
    control at all — the inert case of §6.5, visible in the UI.
    """
    registry = getattr(getattr(request.app.state, "sm", None), "permissions", None)
    role_map = getattr(registry, "role_map", None) or {}
    return {
        "target_types": [{"key": t.key, "label": t.label} for t in rtypes],
        "roles": sorted(role_map),
        "public_route_prefix": settings.public_route_prefix,
        "content_locales": list(locales.supported(settings)),
        "default_locale": locales.default(settings),
        "collections": list(collections()),
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
    live, trashed, invalid = await type_service.record_counts(db, rtype)
    return await inertia.render(
        constants._PAGE_TYPE_EDITOR,
        {
            "type": type_read(rtype, live, trashed, invalid).model_dump(mode="json"),
            **_editor_context(request, rtypes, settings),
        },
    )


__all__ = ["router"]
