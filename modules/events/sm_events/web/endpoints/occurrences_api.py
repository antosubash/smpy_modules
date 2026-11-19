"""``GET /api/events/occurrences``: every range question, within fixed bounds.

The bounds (366 days, 2,000 items, ``truncated``) and the visibility rule belong to
the read (:func:`sm_events.calendar.occurrences.occurrences`), not to this router.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from sm_events.calendar.occurrence import OccurrencePage
from sm_events.calendar.occurrences import occurrences
from sm_events.core.tenancy import bound_tenant
from sm_events.web.endpoints.deps import Principal, content_locales, event_db, require_view
from sm_events.web.schemas.occurrences import OccurrenceParams
from sm_events.web.services.source_viewer import source_viewer_from

router = APIRouter(prefix="/occurrences", tags=["occurrences"], dependencies=[require_view])


@router.get("")
async def read_occurrences(
    request: Request, who: Principal, query: OccurrenceParams, db=Depends(event_db)
) -> OccurrencePage:
    return await occurrences(
        db,
        tenant_id=bound_tenant(),
        viewer=who,
        start=query.start,
        end=query.end,
        filters=query.filters,
        default_locale=content_locales(request)[0],
        source_viewer=source_viewer_from(request, who),
    )
