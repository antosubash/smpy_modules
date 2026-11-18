"""Tenant-bound console screens; their data is loaded from the API."""

import uuid

from fastapi import APIRouter, Depends, Request
from simple_module_core.permissions import grants
from simple_module_db.deps import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import ensure_resolved_permissions
from simple_module_inertia import InertiaResponse
from sqlmodel import select

from sm_events.calendar import calendars as calendar_service
from sm_events.calendar import categories as category_service
from sm_events.calendar.plugins import registry, source_entries
from sm_events.core import constants, tenancy, timezones
from sm_events.core.access.events import load_event
from sm_events.core.access.rights import calendar_rights, calendar_rights_many
from sm_events.core.errors import NotFound
from sm_events.feeds.importing import staging
from sm_events.models import Calendar
from sm_events.web.endpoints.deps import (
    Principal,
    get_settings,
    require_manage,
    require_view,
)
from sm_events.web.endpoints.prefill import parse_prefill
from sm_events.web.endpoints.public import _urls
from sm_events.web.schemas.categories import CategoryOut

router = APIRouter(dependencies=[Depends(tenancy.bind_admin)])


@router.get("/calendars", response_model=None, dependencies=[require_view])
async def calendars_page(request: Request, inertia: InertiaDep) -> InertiaResponse:
    held = await ensure_resolved_permissions(request)
    return await inertia.render(
        constants._PAGE_CALENDARS,
        {
            **tenancy.view_props(request),
            "can_create": grants(held, constants.PERM_EDIT),
            "can_manage": grants(held, constants.PERM_MANAGE),
            "default_timezone": timezones.effective(get_settings(request).default_timezone),
            "user_id": str(request.state.user.id),
            "content_locales": list(get_settings(request).content_locales),
            "public_prefix": _urls.prefix(),
        },
    )


def _import_id(raw: str | None) -> int | None:
    """``?id=`` as an import id (an integer a column holds), else ``None``: a reload resumes it,
    and the API (which checks the caller against the import) decides whether it is theirs."""
    if (
        raw is None
        or not raw.isascii()
        or not raw.isdigit()
        or len(raw) > constants.PAGE_DIGITS_MAX
    ):
        return None
    return int(raw)


@router.get("/import", response_model=None, dependencies=[require_view, require_manage])
async def import_page(
    request: Request,
    inertia: InertiaDep,
    who: Principal,
    db=Depends(get_db),
    id: str | None = None,
) -> InertiaResponse:
    calendars = [
        {k: c[k] for k in ("id", "name", "color", "default_timezone")}
        for c in await _viewer_calendars(db, who, request)
        if c["can_write_events"]
    ]
    return await inertia.render(
        constants._PAGE_IMPORT,
        {
            **tenancy.view_props(request),
            "calendars": calendars,
            "can_publish": who.has(constants.PERM_PUBLISH),
            "max_bytes": staging.effective_max_bytes(get_settings(request)),
            "import_id": _import_id(id),
        },
    )


@router.get("/categories", response_model=None, dependencies=[require_view, require_manage])
async def categories_page(request: Request, inertia: InertiaDep) -> InertiaResponse:
    return await inertia.render(
        constants._PAGE_CATEGORIES,
        {
            **tenancy.view_props(request),
            "content_locales": list(get_settings(request).content_locales),
        },
    )


async def _categories(db) -> list[dict]:
    rows = await category_service.list_categories(db)
    return [CategoryOut.model_validate(row).model_dump(mode="json") for row in rows]


def _calendar_props(cal: Calendar, request: Request, *, can_write_events: bool) -> dict:
    return {
        "id": str(cal.id),
        "name": cal.name,
        "color": cal.color,
        "visibility": cal.visibility,
        "default_timezone": timezones.effective(
            cal.default_timezone or get_settings(request).default_timezone
        ),
        "can_write_events": can_write_events,
    }


def _type_props() -> list[dict]:
    """The installed types as the console's pickers and filters need them."""
    found = registry.all_types()
    ordered = sorted(found.values(), key=lambda t: (t.id != constants.BUILTIN_TYPE, t.id))
    return [{"id": t.id, "label_key": t.label_key, "icon": t.icon} for t in ordered]


def _enabled_sources(rows: list[Calendar]) -> list[dict]:
    """The installed plugin sources enabled on any of ``rows``: what the console's source
    filter offers. Only ids, labels and colours, never a calendar's settings."""
    found: dict[str, dict] = {}
    for row in rows:
        for entry in source_entries.read(row.sources):
            source = registry.get_source(entry.id)
            if source is not None:
                found[entry.id] = {
                    "id": entry.id,
                    "label_key": source.label_key,
                    "color": source.color,
                }
    return [found[key] for key in sorted(found)]


async def _viewer_calendars(
    db, who, request: Request, rows: list[Calendar] | None = None
) -> list[dict]:
    """The calendars the viewer can see, with what the screens need of each."""
    rows = await calendar_service.list_calendars(db, who) if rows is None else rows
    rights = await calendar_rights_many(db, who, rows)
    return [
        _calendar_props(row, request, can_write_events=rights[row.id].write_events) for row in rows
    ]


@router.get("/", response_model=None, dependencies=[require_view])
async def calendar_page(
    request: Request, inertia: InertiaDep, who: Principal, db=Depends(get_db)
) -> InertiaResponse:
    settings = get_settings(request)
    rows = await calendar_service.list_calendars(db, who)
    return await inertia.render(
        constants._PAGE_CALENDAR,
        {
            **tenancy.view_props(request),
            "calendars": await _viewer_calendars(db, who, request, rows),
            "sources": _enabled_sources(rows),
            "types": _type_props(),
            "categories": await _categories(db),
            "default_timezone": timezones.effective(settings.default_timezone),
            "content_locales": list(settings.content_locales),
            "editor_url": constants.EDITOR_URL,
        },
    )


def _editor_props(request: Request, cal: Calendar, can_write: bool, categories: list[dict]) -> dict:
    calendar = _calendar_props(cal, request, can_write_events=can_write)
    return {
        **tenancy.view_props(request),
        "calendar": {k: calendar[k] for k in ("id", "name", "default_timezone")},
        "content_locales": list(get_settings(request).content_locales),
        "categories": categories,
        "types": _type_props(),
        "default_timezone": calendar["default_timezone"],
    }


@router.get("/list", response_model=None, dependencies=[require_view])
async def events_page(
    request: Request, inertia: InertiaDep, who: Principal, db=Depends(get_db)
) -> InertiaResponse:
    calendars = await _viewer_calendars(db, who, request)
    return await inertia.render(
        constants._PAGE_EVENTS,
        {
            **tenancy.view_props(request),
            "content_locales": list(get_settings(request).content_locales),
            "can_create": any(c["can_write_events"] for c in calendars),
            "categories": await _categories(db),
            "calendars": calendars,
        },
    )


@router.get(
    f"/edit/{constants.EVENT_NEW_SEGMENT}", response_model=None, dependencies=[require_view]
)
async def editor_new_page(
    request: Request,
    inertia: InertiaDep,
    who: Principal,
    calendar: uuid.UUID | None = None,
    db=Depends(get_db),
) -> InertiaResponse:
    cal = None
    if calendar is not None:
        cal = (
            await db.execute(select(Calendar).where(Calendar.id == calendar))
        ).scalar_one_or_none()
    if cal is None or not (await calendar_rights(db, who, cal)).write_events:
        raise NotFound
    props = _editor_props(request, cal, True, await _categories(db))
    prefill = parse_prefill(request.query_params)
    return await inertia.render(
        constants._PAGE_EVENT_EDITOR, {**props, "event_id": None, "prefill": prefill}
    )


@router.get("/edit/{event_id}", response_model=None, dependencies=[require_view])
async def editor_page(
    event_id: uuid.UUID, request: Request, inertia: InertiaDep, who: Principal, db=Depends(get_db)
) -> InertiaResponse:
    event, rights = await load_event(db, who, event_id)
    cal = (await db.execute(select(Calendar).where(Calendar.id == event.calendar_id))).scalar_one()
    props = _editor_props(request, cal, rights.write, await _categories(db))
    return await inertia.render(constants._PAGE_EVENT_EDITOR, {**props, "event_id": str(event.id)})
