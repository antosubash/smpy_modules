"""``/api/events/calendars``: list, create, edit, visibility, ownership, trash.

The parent router binds the tenant (first) and the CSRF check. Every
``{calendar_id}`` route loads its row through the access policy, so a calendar
the caller may not see is a 404, and one they see but may not change a 403.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal

from sm_events.calendar import calendars as service
from sm_events.core.access import CalendarEdit, CalendarOwner, CalendarView
from sm_events.core.access.rights import calendar_rights
from sm_events.core.constants import OWNER_NOT_ALLOWED_CODE, OWNER_NOT_ALLOWED_DETAIL
from sm_events.core.errors import Invalid
from sm_events.models import Calendar
from sm_events.web.endpoints.deps import get_settings, require_edit, require_manage, require_view
from sm_events.web.schemas.calendars import (
    CalendarCreate,
    CalendarOut,
    CalendarPatch,
    OwnerIn,
    VisibilityIn,
)
from sm_events.web.services.members import active_member

router = APIRouter(prefix="/calendars", tags=["calendars"], dependencies=[require_view])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]


async def out(db, who: ResourcePrincipal, cal: Calendar, *, trashed: bool = False) -> CalendarOut:
    rights = await calendar_rights(db, who, cal, include_deleted=trashed)
    return CalendarOut.model_validate(cal).model_copy(
        update={
            "can_edit": rights.edit_calendar,
            "can_own": rights.own,
            "can_write_events": rights.write_events,
            "can_publish": rights.publish,
        }
    )


@router.get("")
async def list_calendars(
    who: Principal, db=Depends(get_db), trashed: bool = Query(False)
) -> list[CalendarOut]:
    rows = await service.list_calendars(db, who, trashed=trashed)
    return [await out(db, who, row, trashed=trashed) for row in rows]


@router.post("", status_code=201, dependencies=[require_edit])
async def create_calendar(
    body: CalendarCreate, request: Request, who: Principal, db=Depends(get_db)
) -> CalendarOut:
    row = await service.create_calendar(
        db, who, body, default_tz=get_settings(request).default_timezone
    )
    return await out(db, who, row)


@router.get("/{calendar_id}")
async def get_calendar(calendar: CalendarView, who: Principal, db=Depends(get_db)) -> CalendarOut:
    return await out(db, who, calendar)


@router.patch("/{calendar_id}")
async def update_calendar(
    body: CalendarPatch, calendar: CalendarEdit, who: Principal, db=Depends(get_db)
) -> CalendarOut:
    return await out(db, who, await service.update_calendar(db, calendar, body))


@router.put("/{calendar_id}/visibility")
async def set_visibility(
    body: VisibilityIn, calendar: CalendarOwner, who: Principal, db=Depends(get_db)
) -> CalendarOut:
    return await out(db, who, await service.set_visibility(db, calendar, body.visibility))


@router.put("/{calendar_id}/owner", dependencies=[require_manage])
async def transfer_owner(
    body: OwnerIn, request: Request, calendar: CalendarOwner, who: Principal, db=Depends(get_db)
) -> CalendarOut:
    """``events.manage`` only: hand the calendar to another active member of the
    tenant (the owner themself cannot give it away)."""
    if not await active_member(request, db, body.owner_id):
        raise Invalid(OWNER_NOT_ALLOWED_DETAIL, code=OWNER_NOT_ALLOWED_CODE)
    return await out(db, who, await service.set_owner(db, calendar, body.owner_id))


@router.delete("/{calendar_id}", status_code=204)
async def delete_calendar(calendar: CalendarOwner, who: Principal, db=Depends(get_db)) -> Response:
    await service.trash_calendar(db, calendar, who)
    return Response(status_code=204)


@router.post("/{calendar_id}/restore")
async def restore_calendar(
    calendar_id: uuid.UUID, who: Principal, db=Depends(get_db)
) -> CalendarOut:
    row = await service.restore_calendar(db, who, calendar_id)
    return await out(db, who, row)
