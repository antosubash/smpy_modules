"""``/api/events``: follow an event for reminders, "my reminders", and the delivery status.

The parent router binds the tenant (first) and the CSRF check. Every route needs ``events.view``
**and** goes through :func:`caller`, the one dependency that makes a route act as its own
signed-in caller: a follow is one user's private data, so there is no route that takes another
user's id, no follow id to guess (a follow is addressed by its event, always the caller's), and
nothing lists who follows what. A route-table test fails on a route that skips it.

An event the caller cannot see, one that is trashed and one that does not exist answer the same
404. While reminders cannot be delivered (:mod:`~sm_events.reminders.availability`) a write that
would start or change reminders is 503 ``reminders_unavailable``; reads answer, and stopping is
never refused.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.errors import NotFound
from sm_events.core.errors_reminders import RemindersUnavailable
from sm_events.reminders import access, follows, leads, limits, mine
from sm_events.reminders.availability import availability
from sm_events.web.endpoints.deps import Principal, get_settings, require_manage, require_view
from sm_events.web.schemas.reminders import (
    DeliveryCounts,
    DeliveryOut,
    FollowIn,
    FollowOut,
    MineCalendarOut,
    MineItemOut,
    MinePageOut,
    StatusOut,
)

router = APIRouter(tags=["reminders"], dependencies=[require_view])

EVENT_FOLLOW = "/events/{event_id}/follow"
PATH_PATTERN = rf"^{constants.ROUTE_PREFIX_API}/events/[^/]+/follow$"
"""The follow routes, as the rate-limit rule matches them."""
RATE = limits.FOLLOW_RATE
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=limits.MINE_PAGE_MAX)]


async def caller(who: Principal) -> ResourcePrincipal:
    """The signed-in caller, and only them: the one dependency every route here uses. A
    request with no user (the framework refuses those first) is the missing-id 404 anyway."""
    if who.user_id is None:
        raise NotFound
    return who


Caller = Annotated[ResourcePrincipal, Depends(caller)]


async def _out(
    request: Request,
    db: Any,
    who: ResourcePrincipal,
    event_id: uuid.UUID,
    state: follows.FollowState,
) -> FollowOut:
    ok = event_id in await access.deliverable(request.app, db, who, {event_id})
    return FollowOut(
        leads=list(state.leads),
        defaults=list(state.defaults),
        next_due=state.next_due,
        deliverable=ok,
        code=None if ok else constants.REMINDERS_NO_ACCESS_CODE,
    )


@router.get("/reminders/status", response_model_exclude_none=True)
async def reminders_status(request: Request, who: Caller, db=Depends(get_db)) -> StatusOut:
    found = await availability(request.app, db)
    manager = who.has(constants.PERM_MANAGE)
    return StatusOut(
        available=found.available,
        reason=found.reason if manager else None,
        leads=list(limits.REMINDER_LEADS),
    )


@router.get(EVENT_FOLLOW)
async def get_follow(
    event_id: uuid.UUID, request: Request, who: Caller, db=Depends(get_db)
) -> FollowOut:
    state = await follows.get_follow(
        db, who, event_id, settings=get_settings(request), now=utcnow()
    )
    return await _out(request, db, who, event_id, state)


@router.put(EVENT_FOLLOW)
async def put_follow(
    event_id: uuid.UUID, body: FollowIn, request: Request, who: Caller, db=Depends(get_db)
) -> FollowOut:
    settings = get_settings(request)
    if body.leads and not (await availability(request.app, db)).available:
        raise RemindersUnavailable
    state = await follows.set_follow(
        db,
        who,
        event_id,
        body.leads,
        locale=follows.request_locale(request, _default_locale(request)),
        settings=settings,
        now=utcnow(),
    )
    return await _out(request, db, who, event_id, state)


@router.delete(EVENT_FOLLOW, status_code=204)
async def delete_follow(event_id: uuid.UUID, who: Caller, db=Depends(get_db)) -> Response:
    await follows.delete_follow(db, who, event_id)
    return Response(status_code=204)


def _default_locale(request: Request) -> str:
    locales = get_settings(request).content_locales
    return locales[0] if locales else "en"


@router.get("/reminders/mine")
async def my_reminders(
    request: Request,
    who: Caller,
    db=Depends(get_db),
    page: Page = 1,
    page_size: PageSize = limits.MINE_PAGE_SIZE,
    locale: str | None = Query(default=None, max_length=constants.LOCALE_MAX),
) -> MinePageOut:
    found = await mine.my_reminders(
        db,
        who,
        locale=locale or follows.request_locale(request, _default_locale(request)),
        page=page,
        page_size=page_size,
        settings=get_settings(request),
        now=utcnow(),
    )
    ok = await access.deliverable(request.app, db, who, {i.event_id for i in found.items})
    return MinePageOut(
        items=[
            MineItemOut(
                event_id=i.event_id,
                title=i.title,
                lang=i.lang,
                calendar=MineCalendarOut(
                    id=i.calendar.id, name=i.calendar.name, color=i.calendar.color
                ),
                leads=list(i.leads),
                next_start=i.next_start,
                deliverable=i.event_id in ok,
            )
            for i in found.items
        ],
        total=found.total,
        hidden=found.hidden,
        page=found.page,
        page_size=found.page_size,
    )


@router.get("/reminders/delivery", dependencies=[require_manage])
async def delivery(request: Request, who: Caller, db=Depends(get_db)) -> DeliveryOut:
    """Counts for managers; never who. The 30-day figures are wired to the ledger with the beat
    (until then there is nothing sent to count)."""
    settings = get_settings(request)
    found = await availability(request.app, db)
    return DeliveryOut(
        enabled=settings.reminders_enabled,
        available=found.available,
        reason=found.reason,
        defaults=list(leads.install_defaults(settings)),
        window_days=limits.STATS_WINDOW_DAYS,
        counts=DeliveryCounts(sent=0, failed={}, unfinished=0),
    )
