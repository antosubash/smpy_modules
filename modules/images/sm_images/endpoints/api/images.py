"""Images in a collection: multipart and base64 upload, the gallery list, and
``/images/{image_id}`` read, manual location and soft delete.

Uploading is an ``edit`` on the collection (owner, an edit share,
``images.manage``); deleting an image is owner or ``images.manage``. Every
response names the image ``id`` and ``status: created | duplicate``.

**A multipart batch isolates its files**: each one is read, sniffed and
guarded on its own, and inserted in its own savepoint, so a refused or failed
file is reported in ``results`` and the rest still land. A request carrying a
single file is answered with that file's own status instead (415, 413, ...),
which is what a one-file client expects.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.resource_deps import resource_principal

from sm_images import constants
from sm_images.access import (
    CollectionEdit,
    CollectionView,
    ImageCollectionEdit,
    ImageCollectionOwner,
    ImageCollectionView,
)
from sm_images.deps import get_settings, require_view
from sm_images.errors import ImagesError, InvalidUpload, UploadFailed, UseDirectUpload
from sm_images.ingest import Duplicate, IngestMeta, IngestService, parse_batch_metadata
from sm_images.ingest.b64 import decode_base64
from sm_images.ingest.guards import read_bounded
from sm_images.models import Image, ReviewStatus, StepStatus
from sm_images.schemas.image import (
    Base64Upload,
    BatchOut,
    ImageOut,
    ImagePageOut,
    ImagePatch,
    UploadResult,
)
from sm_images.services import gallery, present
from sm_images.storage import store_for

logger = logging.getLogger(__name__)
router = APIRouter(tags=["images"])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
_TOO_MANY = "Too many files in one upload"
_FAILED = "The file could not be stored"


def ingest_service(request: Request, db: Any = Depends(get_db)) -> IngestService:
    sm = getattr(request.app.state, "sm", None)
    return IngestService(
        db,
        store_for(request.app),
        get_settings(request),
        bus=getattr(sm, "event_bus", None),
    )


Ingest = Annotated[IngestService, Depends(ingest_service)]


def result(outcome: Image | Duplicate, filename: str | None = None) -> UploadResult:
    if isinstance(outcome, Duplicate):
        return UploadResult(filename=filename, status="duplicate", id=outcome.image_id)
    return UploadResult(filename=filename or outcome.filename, status="created", id=outcome.id)


def _refused(filename: str | None, exc: ImagesError) -> UploadResult:
    return UploadResult(filename=filename, status="error", code=exc.code, detail=exc.detail)


async def _read(ingest: IngestService, file: UploadFile) -> tuple[bytes, Any]:
    limit = ingest.settings.direct_upload_threshold
    data = await read_bounded(file, limit, over=UseDirectUpload)
    return data, ingest.inspect(data)


@router.post("/collections/{collection_id}/images", dependencies=[require_view])
async def upload_images(
    collection: CollectionEdit,
    ingest: Ingest,
    files: Annotated[list[UploadFile], File()],
    metadata: Annotated[str | None, Form(max_length=constants.METADATA_MAX_BYTES)] = None,
) -> BatchOut:
    if len(files) > ingest.settings.batch_max:
        raise InvalidUpload(_TOO_MANY, constants.CODE_BATCH_TOO_LARGE)
    metas = parse_batch_metadata(metadata)
    read: list[tuple[UploadFile, Any] | ImagesError] = []
    for file in files:
        try:
            read.append((file, await _read(ingest, file)))
        except ImagesError as exc:
            read.append(exc)
    # Every intent before the first insert (see IngestService.reserve).
    slots = iter(
        await ingest.reserve(collection, [r[1][1].ext for r in read if isinstance(r, tuple)])
    )
    results: list[UploadResult] = []
    errors: list[ImagesError] = []
    for file, entry in zip(files, read, strict=True):
        if isinstance(entry, ImagesError):
            results.append(_refused(file.filename, entry))
            errors.append(entry)
            continue
        (data, info), name = entry[1], file.filename
        try:
            outcome = await ingest.add_image(
                collection,
                data=data,
                slot=next(slots),
                filename=name,
                meta=metas.get(name or "", IngestMeta()),
                source=constants.SOURCE_UPLOAD,
                inspected=info,
            )
            results.append(result(outcome, name))
        except ImagesError as exc:
            results.append(_refused(name, exc))
            errors.append(exc)
        except Exception:
            logger.exception("images.upload.file_failed", extra={"file_name": name})
            failed = UploadFailed(_FAILED)
            results.append(_refused(name, failed))
            errors.append(failed)
    if len(files) == 1 and errors:
        raise errors[0]
    return BatchOut(results=results)


@router.post("/collections/{collection_id}/images/base64", dependencies=[require_view])
async def upload_base64(
    body: Base64Upload, collection: CollectionEdit, ingest: Ingest
) -> UploadResult:
    data = decode_base64(body.data, ingest.settings.max_image_bytes)
    outcome = await ingest.add_image(
        collection,
        data=data,
        filename=body.filename,
        meta=body.to_ingest(),
        source=constants.SOURCE_UPLOAD,
    )
    return result(outcome, body.filename)


@router.get("/collections/{collection_id}/images", dependencies=[require_view])
async def list_images(
    collection: CollectionView,
    db=Depends(get_db),
    has_location: bool | None = None,
    step: str | None = Query(None, max_length=100),
    step_status: StepStatus | None = None,
    review_status: ReviewStatus | None = None,
    group: uuid.UUID | None = None,
    limit: int = Query(constants.PAGE_DEFAULT, ge=1, le=constants.PAGE_MAX),
    cursor: str | None = Query(None, max_length=200),
) -> ImagePageOut:
    filters = gallery.Filters(has_location, step, step_status, review_status, group)
    rows, token, total = await gallery.list_page(
        db, collection, filters, limit=limit, cursor=cursor
    )
    return ImagePageOut(
        items=await present.present(db, collection, rows), next_cursor=token, total=total
    )


@router.get("/images/{image_id}", dependencies=[require_view])
async def get_image(
    image_id: uuid.UUID, collection: ImageCollectionView, who: Principal, db=Depends(get_db)
) -> ImageOut:
    row = await gallery.get(db, collection, image_id)
    return await present.present_detail(db, collection, row, who)


@router.patch("/images/{image_id}", dependencies=[require_view])
async def patch_image(
    image_id: uuid.UUID, body: ImagePatch, collection: ImageCollectionEdit, db=Depends(get_db)
) -> ImageOut:
    if (body.lat is None) != (body.lng is None):
        raise InvalidUpload("lat and lng are set together", constants.CODE_INVALID_METADATA)
    image = await gallery.get(db, collection, image_id)
    image = await gallery.set_location(db, collection, image, body.lat, body.lng)
    return await present.present_one(db, collection, image)


@router.delete("/images/{image_id}", status_code=204, dependencies=[require_view])
async def delete_image(
    image_id: uuid.UUID, collection: ImageCollectionOwner, db=Depends(get_db)
) -> Response:
    await gallery.delete(db, collection, await gallery.get(db, collection, image_id))
    return Response(status_code=204)
