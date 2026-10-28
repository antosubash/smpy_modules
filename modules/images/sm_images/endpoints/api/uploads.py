"""Direct uploads: start, relay a part, complete, abort (see ``ingest.direct``).

``POST /collections/{id}/uploads`` is an ``edit`` on the collection. The later
calls carry the signed ``upload_id`` instead of a collection in the path;
``complete`` re-checks ``edit`` on the collection the ticket names, so a share
revoked mid-upload stops it.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response
from simple_module_core.resources import ACTION_EDIT, ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal

from sm_images import constants
from sm_images.access import POLICY, CollectionEdit, collection_stmt
from sm_images.deps import require_view
from sm_images.endpoints.api.images import Ingest, result
from sm_images.errors import UploadNotFound
from sm_images.ingest import direct
from sm_images.models import Collection
from sm_images.schemas.image import (
    DirectComplete,
    DirectCreate,
    DirectCreated,
    PartOut,
    UploadResult,
)
from sm_images.storage import store_for

router = APIRouter(tags=["uploads"])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
UploadId = Annotated[str, Path(max_length=constants.DIRECT_TOKEN_MAX)]


def _secret(request: Request) -> str:
    settings = getattr(getattr(request.app.state, "sm", None), "settings", None)
    return getattr(settings, "secret_key", "") or ""


def _ticket(request: Request, upload_id: str, who: ResourcePrincipal) -> direct.Ticket:
    return direct.load_ticket(upload_id, secret=_secret(request), owner=who.user_id)


async def _editable(db: Any, who: ResourcePrincipal, ticket: direct.Ticket) -> Collection:
    stmt = POLICY.filter(who, ACTION_EDIT, collection_stmt(uuid.UUID(ticket.collection)))
    found = (await db.execute(stmt)).scalars().first()
    if found is None:
        raise UploadNotFound("Upload not found")
    return found


@router.post("/collections/{collection_id}/uploads", status_code=201, dependencies=[require_view])
async def start_upload(
    body: DirectCreate, request: Request, collection: CollectionEdit, who: Principal, ingest: Ingest
) -> DirectCreated:
    if who.user_id is None:  # pragma: no cover - require_view admits only signed-in callers
        raise UploadNotFound("Upload not found")
    token, ticket, urls, presigned = await direct.start(
        store_for(request.app),
        collection,
        filename=body.filename,
        size=body.size,
        content_type=body.content_type,
        max_bytes=ingest.settings.max_image_bytes,
        owner=who.user_id,
        secret=_secret(request),
    )
    return DirectCreated(
        upload_id=token,
        part_size=ticket.part_size,
        part_urls=urls,
        direct=presigned,
        expires_in=constants.DIRECT_UPLOAD_TTL_SECONDS,
    )


@router.put(
    f"{constants.UPLOADS_PATH}/{{upload_id}}/parts/{{part_no}}", dependencies=[require_view]
)
async def put_part(upload_id: UploadId, part_no: int, request: Request, who: Principal) -> PartOut:
    ticket = _ticket(request, upload_id, who)
    part = await direct.write_part(store_for(request.app), ticket, part_no, request.stream())
    return PartOut(no=part.no, etag=part.etag, size=part.size)


@router.post(f"{constants.UPLOADS_PATH}/{{upload_id}}/complete", dependencies=[require_view])
async def complete_upload(
    upload_id: UploadId,
    body: DirectComplete,
    request: Request,
    who: Principal,
    ingest: Ingest,
) -> UploadResult:
    ticket = _ticket(request, upload_id, who)
    collection = await _editable(ingest.db, who, ticket)
    meta = body.metadata.to_ingest() if body.metadata else direct.IngestMeta()
    outcome = await direct.complete(
        ingest,
        collection,
        ticket,
        claimed={p.no: p.etag for p in body.parts},
        filename=body.filename,
        meta=meta,
    )
    return result(outcome, body.filename or ticket.filename)


@router.delete(
    f"{constants.UPLOADS_PATH}/{{upload_id}}", status_code=204, dependencies=[require_view]
)
async def abort_upload(
    upload_id: UploadId, request: Request, who: Principal, db=Depends(get_db)
) -> Response:
    ticket = _ticket(request, upload_id, who)
    await direct.abort(db, store_for(request.app), ticket)
    return Response(status_code=204)
