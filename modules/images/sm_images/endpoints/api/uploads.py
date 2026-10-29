"""Direct uploads: start, relay a part, complete, abort (see ``ingest.direct``).

``POST /collections/{id}/uploads`` is an ``edit`` on the collection. The later
calls carry the signed ``upload_id`` instead of a collection in the path, and
each of them - part, complete, abort - resolves the ticket's collection through
the same ``RequiresResource(POLICY, ACTION_EDIT, ...)`` dependency the
collection routes use (:data:`TicketCollection`), behind the same
``images.view`` gate. So a share revoked mid-upload stops every later call
(404, or 403 where the collection is still visible), and the routes treat an
API token exactly as the collection routes do.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response
from simple_module_core.resources import ACTION_EDIT, ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import RequiresResource, resource_principal

from sm_images import billing, constants
from sm_images.access import POLICY, CollectionEdit, collection_stmt
from sm_images.deps import require_view
from sm_images.endpoints.api.images import Ingest, result
from sm_images.errors import UploadNotFound, UploadNotOpen
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
from sm_images.tenancy import bound_tenant

router = APIRouter(tags=["uploads"])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
UploadId = Annotated[str, Path(max_length=constants.DIRECT_TOKEN_MAX)]


def host_secret(request: Request) -> str:
    """The host's ``secret_key``, which signs direct-upload tickets."""
    settings = getattr(getattr(request.app.state, "sm", None), "settings", None)
    return getattr(settings, "secret_key", "") or ""


async def upload_ticket(upload_id: UploadId, request: Request, who: Principal) -> direct.Ticket:
    """The caller's own, unexpired ticket in the bound tenant, or 404."""
    return direct.load_ticket(upload_id, secret=host_secret(request), owner=who.user_id)


Ticket = Annotated[direct.Ticket, Depends(upload_ticket)]


def ticket_collection_stmt(ticket: Ticket) -> Any:
    return collection_stmt(uuid.UUID(ticket.collection))


TicketCollection = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_EDIT, ticket_collection_stmt))
]
"""``edit`` on the ticket's collection, checked on every call, not just at start."""


@router.post("/collections/{collection_id}/uploads", status_code=201, dependencies=[require_view])
async def start_upload(
    body: DirectCreate, request: Request, collection: CollectionEdit, who: Principal, ingest: Ingest
) -> DirectCreated:
    if who.user_id is None:  # pragma: no cover - require_view admits only signed-in callers
        raise UploadNotFound("Upload not found")
    token, ticket, urls, presigned = await direct.start(
        ingest.db,
        store_for(request.app),
        collection,
        filename=body.filename,
        size=body.size,
        content_type=body.content_type,
        max_bytes=ingest.settings.max_image_bytes,
        owner=who.user_id,
        secret=host_secret(request),
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
async def put_part(
    part_no: int,
    request: Request,
    ticket: Ticket,
    collection: TicketCollection,
    db=Depends(get_db),
) -> PartOut:
    part = await direct.write_part(db, store_for(request.app), ticket, part_no, request.stream())
    return PartOut(no=part.no, etag=part.etag, size=part.size)


@router.post(f"{constants.UPLOADS_PATH}/{{upload_id}}/complete", dependencies=[require_view])
async def complete_upload(
    request: Request,
    body: DirectComplete,
    ticket: Ticket,
    collection: TicketCollection,
    ingest: Ingest,
) -> UploadResult:
    if ticket.kind != "image":  # a ZIP is sealed by its import's extract, never here
        raise UploadNotOpen("This upload is completed by its import's extract")
    done = await direct.existing(ingest.db, ticket)
    if done is not None:  # a replay is answered before any capacity check
        return result(done, body.filename or ticket.filename)
    await billing.check(request.app, bound_tenant(), ticket.size)
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
    request: Request, ticket: Ticket, collection: TicketCollection, db=Depends(get_db)
) -> Response:
    await direct.abort(db, store_for(request.app), ticket)
    return Response(status_code=204)
