"""``/api/events/sources`` and ``PUT /api/events/calendars/{id}/sources``.

Listing needs ``events.view``. Enabling a source changes what a calendar's audience sees,
so the write needs the right to change its visibility: the owner's, or ``events.manage``
(``CalendarOwner``; a calendar the caller cannot see is a 404 either way).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_db.deps import get_db

from sm_events.calendar.plugins import registry, source_entries
from sm_events.content.types import type_info
from sm_events.core import constants
from sm_events.core.access import CalendarOwner
from sm_events.core.errors import TenantRequired
from sm_events.core.tenancy import bound_tenant
from sm_events.web.endpoints.calendars_api import Principal, out
from sm_events.web.endpoints.deps import require_view
from sm_events.web.schemas.calendars import CalendarOut
from sm_events.web.schemas.extensions import SourceOut, SourcesIn, TypeOut
from sm_events.web.services.source_viewer import source_viewer_from

router = APIRouter(tags=["extensions"], dependencies=[require_view])


@router.get("/sources")
async def list_sources() -> list[SourceOut]:
    """Every installed plugin source (the built-in ``events`` is always on and not listed)."""
    found = registry.plugin_sources()
    return [
        SourceOut(
            id=source.id,
            label_key=source.label_key,
            color=source.color,
            icon=source.icon,
            public=source.public,
            has_settings=source.settings_model is not None,
            settings_schema=(
                source.settings_model.model_json_schema() if source.settings_model else None
            ),
        )
        for _id, source in sorted(found.items())
    ]


@router.get("/types")
async def list_types() -> list[TypeOut]:
    """Every installed event type: the built-in first, then by id."""
    found = registry.all_types()
    ordered = sorted(found.values(), key=lambda t: (t.id != constants.BUILTIN_TYPE, t.id))
    return [type_info(t) for t in ordered]


@router.put("/calendars/{calendar_id}/sources")
async def set_sources(
    body: SourcesIn,
    request: Request,
    calendar: CalendarOwner,
    who: Principal,
    db=Depends(get_db),
) -> CalendarOut:
    viewer = source_viewer_from(request, who)
    if viewer is None:  # unreachable behind ``CalendarOwner``, which needs a signed-in user
        raise TenantRequired
    await source_entries.write_entries(
        db, bound_tenant(), viewer, calendar, body.sources, body.expected
    )
    return await out(db, request, who, calendar)
