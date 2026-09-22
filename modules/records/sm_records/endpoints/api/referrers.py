"""The reverse relation query: what points at this record (design §9).

Its own module rather than another route on ``records``: the forward read is
about one document, and this is a question about the *graph* — one indexed
lookup over ``records_index_ref`` and a permission rule of its own, since the
referrers live in types the URL never names.

That rule is the whole subtlety here. ``records.view`` gates the endpoint —
and, through ``load_allowed_type``, so does the *target* record's own type —
but a referrer whose type narrows ``allowed_roles`` past the caller is
dropped from ``items`` while still counting towards ``total`` (design §10):
the count stays honest, it is the same number the delete dialog and a
``restrict`` refusal speak, and ``hidden`` says how many rows it covers that
this caller will not be shown. Nothing about them leaks — not their type, and
not their position, since ``items`` is paginated over the visible set alone.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.relations import ReferrersResponse, referrer_read
from sm_records.deps import (
    MAX_PAGE,
    caller_roles,
    get_settings,
    has_edit_permission,
    load_allowed_type,
    request_db,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.endpoints.api._responses import LISTING, responses
from sm_records.models import RecordType
from sm_records.services import _relations
from sm_records.services import records as record_service
from sm_records.services.errors import NotFound
from sm_records.settings import RecordsSettings

router = APIRouter(
    prefix="/types/{key}",
    route_class=RecordsErrorRoute,
    responses=responses(*LISTING),
)


@router.get(
    "/records/{uuid}/referrers", response_model=ReferrersResponse, dependencies=[require_view]
)
async def list_referrers(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    page: int = Query(default=1, ge=1, le=MAX_PAGE),
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

    A **trashed target** is accepted for a caller holding ``records.edit``,
    exactly as ``views.record_edit`` is: that screen renders the badge for a
    record in the trash, and "what still points at this?" is precisely the
    question someone deciding whether to restore or purge one is asking. A
    ``records.view`` holder, who cannot reach the trash at all, still gets
    the same 404 they always did.
    """
    record = await _target_record(request, db, rtype, uuid)
    refs, total, hidden = await _relations.paged_referrers(
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
        hidden=hidden,
    )


async def _target_record(request: Request, db: AsyncSession, rtype: RecordType, uuid: str):
    """The record the panel is about, trash included for an editor.

    The same fallback ``views.record_edit`` makes, and for the same reason:
    the badge that opens this panel is rendered on the trashed record's own
    editor screen, so a 404 here is a dead end behind a number the UI just
    showed. ``NotFound`` is re-raised untouched for anyone without
    ``records.edit``.
    """
    try:
        return await record_service.get_record(db, rtype, uuid)
    except NotFound:
        if not await has_edit_permission(request, db):
            raise
        return await record_service.get_deleted_record(db, rtype, uuid)


__all__ = ["router"]
