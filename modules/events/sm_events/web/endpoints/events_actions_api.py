"""Workflow, history, overrides and the recurrence preview of one event.

Same rules as :mod:`sm_events.web.endpoints.events_api`: ``events.view`` on every
route, the access policy underneath (404 for an event the caller may not see),
``expected_revision`` on every write (409 ``stale``), and a bus commit at the end.
History is for people who may write the event: it carries actor ids and earlier
drafts, so a viewer of a published event gets 403 and not its past.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from sm_events.content import bus, overrides, revisions, series_change
from sm_events.content.workflow import transition
from sm_events.core import constants
from sm_events.core.access.events import load_event
from sm_events.core.clock import utcnow
from sm_events.core.errors import Forbidden
from sm_events.models import Event
from sm_events.web.endpoints.deps import Principal, content_locales, event_db, require_view
from sm_events.web.schemas.events_in import Expected, Revision
from sm_events.web.schemas.events_out import EventOut, RevisionDetail, RevisionOut
from sm_events.web.schemas.overrides import (
    OverrideIn,
    OverrideResult,
    PreviewIn,
    PreviewOut,
    override_out,
)
from sm_events.web.schemas.workflow import ApproveIn, RejectIn
from sm_events.web.services.events_out import render

router = APIRouter(tags=["events"], dependencies=[require_view])

EVENT = "/events/{event_id}"
RowNumber = Annotated[int, Path(ge=1, le=constants.INT32_MAX)]  # fits the integer column


async def _act(
    request: Request, who: Any, db: Any, event_id: uuid.UUID, action: str, **kw: Any
) -> EventOut:
    event = await transition(db, who, event_id, action, now=utcnow(), **kw)
    await db.refresh(event)
    out = await render(db, who, event, locale=None, default_locale=content_locales(request)[0])
    await bus.commit(db)
    return out


@router.post(f"{EVENT}/submit")
async def submit(
    event_id: uuid.UUID, body: Expected, request: Request, who: Principal, db=Depends(event_db)
) -> EventOut:
    return await _act(request, who, db, event_id, "submit", expected=body.expected_revision)


@router.post(f"{EVENT}/withdraw")
async def withdraw(
    event_id: uuid.UUID, body: Expected, request: Request, who: Principal, db=Depends(event_db)
) -> EventOut:
    return await _act(request, who, db, event_id, "withdraw", expected=body.expected_revision)


@router.post(f"{EVENT}/approve")
async def approve(
    event_id: uuid.UUID, body: ApproveIn, request: Request, who: Principal, db=Depends(event_db)
) -> EventOut:
    return await _act(
        request, who, db, event_id, "approve",
        expected=body.expected_revision, publish_at_local=body.publish_at_local,
    )  # fmt: skip


@router.post(f"{EVENT}/reject")
async def reject(
    event_id: uuid.UUID, body: RejectIn, request: Request, who: Principal, db=Depends(event_db)
) -> EventOut:
    return await _act(
        request, who, db, event_id, "reject", expected=body.expected_revision, note=body.note
    )


@router.post(f"{EVENT}/unschedule")
async def unschedule(
    event_id: uuid.UUID, body: Expected, request: Request, who: Principal, db=Depends(event_db)
) -> EventOut:
    return await _act(request, who, db, event_id, "unschedule", expected=body.expected_revision)


@router.post(f"{EVENT}/unpublish")
async def unpublish(
    event_id: uuid.UUID, body: Expected, request: Request, who: Principal, db=Depends(event_db)
) -> EventOut:
    return await _act(request, who, db, event_id, "unpublish", expected=body.expected_revision)


async def _history_event(db: Any, who: Any, event_id: uuid.UUID) -> Event:
    event, rights = await load_event(db, who, event_id)
    if not rights.write:
        raise Forbidden(constants.EDIT_REFUSED_DETAIL)
    return event


@router.get(f"{EVENT}/revisions")
async def list_revisions(
    event_id: uuid.UUID, who: Principal, db=Depends(event_db)
) -> list[RevisionOut]:
    await _history_event(db, who, event_id)
    rows = await revisions.list_revisions(db, event_id)
    return [RevisionOut.model_validate(r, from_attributes=True) for r in rows]


@router.get(f"{EVENT}/revisions/{{number}}")
async def get_revision(
    event_id: uuid.UUID, number: RowNumber, who: Principal, db=Depends(event_db)
) -> RevisionDetail:
    await _history_event(db, who, event_id)
    row = await revisions.get_revision(db, event_id, number)
    return RevisionDetail.model_validate(row, from_attributes=True)


@router.post(f"{EVENT}/overrides")
async def set_override(
    event_id: uuid.UUID, body: OverrideIn, who: Principal, db=Depends(event_db)
) -> OverrideResult:
    row = await overrides.set_override(db, who, event_id, body)
    event, _rights = await load_event(db, who, event_id)
    out = override_out(row, all_day=event.all_day, timezone=event.timezone)
    result = OverrideResult(**out.model_dump(), event_revision=event.revision)
    await bus.commit(db)
    return result


@router.delete(f"{EVENT}/overrides/{{override_id}}", status_code=204)
async def clear_override(
    event_id: uuid.UUID,
    override_id: RowNumber,
    expected_revision: Annotated[Revision, Query()],
    who: Principal,
    db=Depends(event_db),
) -> Response:
    await overrides.clear_override(db, who, event_id, override_id, expected_revision)
    await bus.commit(db)
    return Response(status_code=204)


@router.post("/recurrence/preview")
async def preview(body: PreviewIn, who: Principal, db=Depends(event_db)) -> PreviewOut:
    return await series_change.preview(db, who, body)
