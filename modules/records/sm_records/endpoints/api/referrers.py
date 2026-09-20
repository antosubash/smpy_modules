"""The reverse relation query: what points at this record (design §9).

Its own module rather than another route on ``records``: the forward read is
about one document, and this is a question about the *graph* — one indexed
lookup over ``records_index_ref`` and a permission rule of its own, since the
referrers live in types the URL never names.

That rule is the whole subtlety here. ``records.view`` gates the endpoint, but
a referrer whose type narrows ``allowed_roles`` past the caller is dropped
from ``items`` while still counting towards ``total`` (design §10): the count
stays honest — it is the same number the delete dialog and a ``restrict``
refusal speak — and nothing about the hidden row leaks, not even its type.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.relations import ReferrersResponse, referrer_read
from sm_records.deps import (
    caller_roles,
    get_settings,
    load_type,
    request_db,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.models import RecordType
from sm_records.services import _relations
from sm_records.services import records as record_service
from sm_records.settings import RecordsSettings

router = APIRouter(prefix="/types/{key}", route_class=RecordsErrorRoute)


@router.get(
    "/records/{uuid}/referrers", response_model=ReferrersResponse, dependencies=[require_view]
)
async def list_referrers(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1),
) -> ReferrersResponse:
    """Every record referencing this one, trash included, one page at a time.

    Trashed referrers are *listed* here and flagged ``is_deleted`` — unlike on
    the delete path, which excludes them on purpose (a trashed referrer
    neither blocks a ``restrict`` nor is followed by a ``cascade``). The panel
    answers "what points here", and a reference that comes back the moment
    somebody restores a record is part of that answer.

    ``field_label`` comes from the *referring* type's own field definition, so
    the panel says "Order → Customer" rather than repeating this record's
    vocabulary back at the reader.
    """
    record = await record_service.get_record(db, rtype, uuid)
    refs, total = await _relations.paged_referrers(
        db,
        record,
        roles=caller_roles(request),
        page=page,
        page_size=settings.clamp_page_size(page_size),
    )
    return ReferrersResponse(
        items=[
            referrer_read(
                ref.record,
                ref.rtype,
                ref.field_key,
                _relations.field_label(ref.rtype, ref.field_key),
                ref.on_delete,
            )
            for ref in refs
        ],
        total=total,
    )


__all__ = ["router"]
