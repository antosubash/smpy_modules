"""``/api/events/events``: list, create, read, edit, trash and restore.

The parent router binds the tenant (first) and the CSRF check; every route needs
``events.view``. Beyond that the policy decides: a calendar the caller may not see
is a 404 and an event they may not see (a draft, to a viewer) is the same 404, with
the same body as a missing id; a write needs write on the calendar, and one on a
published or scheduled event needs ``events.publish`` too (403 ``publish_required``).
Every write quotes ``expected_revision`` (409 ``stale``). The services never commit:
each write handler renders, then finishes with :func:`sm_events.content.bus.commit`,
which publishes the bus events the write queued.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from sm_events.content import bus, listing
from sm_events.content.events_trash import restore_event, trash_event
from sm_events.content.events_write import create_event, update_event
from sm_events.core import constants
from sm_events.core.access.events import load_event
from sm_events.models.enums import EVENT_STATUSES
from sm_events.web.endpoints.deps import Principal, content_locales, event_db, require_view
from sm_events.web.schemas._fields import SupportedInstant
from sm_events.web.schemas.events_in import EventCreate, EventPatch, Expected, Revision
from sm_events.web.schemas.events_out import EventOut, EventPage
from sm_events.web.services.events_out import render, render_items
from sm_events.web.services.source_viewer import source_viewer_from

router = APIRouter(prefix="/events", tags=["events"], dependencies=[require_view])

ListStatus = Literal[*EVENT_STATUSES, constants.STATUS_SCHEDULED]  # type: ignore[valid-type]
LocaleQuery = Annotated[str | None, Query(max_length=constants.LOCALE_MAX)]
PAGE_LIMIT = 10_000


@router.get("")
async def list_events(
    request: Request,
    who: Principal,
    db=Depends(event_db),
    calendar: Annotated[list[uuid.UUID] | None, Query(max_length=constants.CALENDARS_MAX)] = None,
    status: ListStatus | None = None,
    category: uuid.UUID | None = None,
    from_: Annotated[SupportedInstant | None, Query(alias="from")] = None,
    to: SupportedInstant | None = None,
    q: Annotated[str | None, Query(max_length=constants.QUERY_MAX)] = None,
    trashed: bool = False,
    locale: LocaleQuery = None,
    page: Annotated[int, Query(ge=1, le=PAGE_LIMIT)] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=constants.EVENTS_PAGE_MAX)
    ] = constants.EVENTS_PAGE_DEFAULT,
) -> EventPage:
    filters = listing.EventFilters(
        calendar_ids=tuple(calendar or ()),
        status=status,
        category_id=category,
        start=from_,
        end=to,
        q=q or None,
        trashed=trashed,
    )
    rows, total = await listing.list_events(db, who, filters, page=page, page_size=page_size)
    default = content_locales(request)[0]
    items = await render_items(db, who, rows, locale=locale, default_locale=default)
    return EventPage(items=items, total=total, page=page, page_size=page_size)


@router.post("", status_code=201)
async def create(
    body: EventCreate, request: Request, who: Principal, db=Depends(event_db)
) -> EventOut:
    locales = content_locales(request)
    event = await create_event(
        db, who, body, locales=locales, viewer=source_viewer_from(request, who)
    )
    await db.refresh(event)
    out = await render(
        db,
        who,
        event,
        locale=None,
        default_locale=locales[0],
        viewer=source_viewer_from(request, who),
    )
    await bus.commit(db)
    return out


@router.get("/{event_id}")
async def get_event(
    event_id: uuid.UUID,
    request: Request,
    who: Principal,
    db=Depends(event_db),
    locale: LocaleQuery = None,
) -> EventOut:
    event, _rights = await load_event(db, who, event_id)
    return await render(
        db,
        who,
        event,
        locale=locale,
        default_locale=content_locales(request)[0],
        viewer=source_viewer_from(request, who),
    )


@router.patch("/{event_id}")
async def update(
    event_id: uuid.UUID, body: EventPatch, request: Request, who: Principal, db=Depends(event_db)
) -> EventOut:
    locales = content_locales(request)
    event = await update_event(
        db, who, event_id, body, locales=locales, viewer=source_viewer_from(request, who)
    )
    await db.refresh(event)
    out = await render(
        db,
        who,
        event,
        locale=None,
        default_locale=locales[0],
        viewer=source_viewer_from(request, who),
    )
    await bus.commit(db)
    return out


@router.delete("/{event_id}", status_code=204)
async def trash(
    event_id: uuid.UUID,
    who: Principal,
    expected_revision: Annotated[Revision, Query()],
    db=Depends(event_db),
) -> Response:
    await trash_event(db, who, event_id, expected_revision)
    await bus.commit(db)
    return Response(status_code=204)


@router.post("/{event_id}/restore")
async def restore(
    event_id: uuid.UUID, body: Expected, request: Request, who: Principal, db=Depends(event_db)
) -> EventOut:
    event = await restore_event(db, who, event_id, body.expected_revision)
    await db.refresh(event)
    out = await render(
        db,
        who,
        event,
        locale=None,
        default_locale=content_locales(request)[0],
        viewer=source_viewer_from(request, who),
    )
    await bus.commit(db)
    return out
