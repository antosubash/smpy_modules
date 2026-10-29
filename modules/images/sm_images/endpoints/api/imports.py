"""GeoJSON imports: ``/api/images/collections/{id}/imports`` and ``/api/images/imports/{job}``.

Every route is an ``edit`` on the job's collection (owner, an edit share,
``images.manage``): importing writes images into it, and a job's mapping and
source URL are an editor's business. A job of a collection the caller cannot
edit is a 404, exactly like an id that never existed.

Starting a job takes multipart form fields - ``kind`` (``geojson_url`` or
``geojson_base64``), ``mapping`` (JSON, :class:`~sm_images.imports.mapping.Mapping`),
``auto_run_prompts`` (default true; false opts this import out) - and
exactly one source: ``file`` (the GeoJSON, held
by the request's spooled upload, inside the upload body limit) or
``source_url`` (fetched by the runner through the SSRF guard). The answer is
202 with the job; on an eager host (tests, dev without a broker) the import
has already run by then.

A ZIP goes in two calls (``imports.zip_upload``): ``POST
/collections/{id}/imports/zip`` opens the job and a direct upload for the
archive (presigned parts, or the relay route); ``POST /imports/{job}/extract``
- an ``edit`` on the collection again, so a share revoked meanwhile stops it -
seals the uploaded archive to the job and starts the extraction, under the
extractor's right from then on.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from simple_module_core.resources import ACTION_EDIT, ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_db.listeners import current_tenant_id
from simple_module_hosting.resource_deps import RequiresResource, resource_principal
from sqlalchemy import select

from sm_images import constants
from sm_images.access import POLICY, CollectionEdit
from sm_images.deps import require_view
from sm_images.endpoints.api.uploads import host_secret
from sm_images.errors import ServiceUnavailable, UploadNotFound
from sm_images.imports import access, controls, zip_upload
from sm_images.imports.service import start_import
from sm_images.imports.zip_import import launch_sealed
from sm_images.models import Collection, ImportJob
from sm_images.pipeline.runtime import Runtime, current_runtime
from sm_images.schemas.image import DirectCreated
from sm_images.schemas.imports import (
    ImportJobOut,
    ImportJobPage,
    ZipCreate,
    ZipCreated,
    ZipExtract,
    job_out,
)

router = APIRouter(tags=["imports"])

Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]
LIST_MAX = 100


def _runtime() -> Runtime:
    runtime = current_runtime()
    if runtime is None:
        raise ServiceUnavailable("the image pipeline is not running in this process")
    return runtime


def _tenant() -> str:
    tenant = current_tenant_id.get()
    if tenant is None:  # bind_admin ran first; this is the import code's own guard
        raise ServiceUnavailable("no tenant is bound")
    return tenant


def job_collection_stmt(job_id: uuid.UUID) -> Any:
    """The (untrashed) collection holding import job ``job_id``."""
    return (
        select(Collection)
        .join(ImportJob, ImportJob.collection_id == Collection.id)
        .where(ImportJob.id == job_id)
    )


JobCollection = Annotated[
    Collection, Depends(RequiresResource(POLICY, ACTION_EDIT, job_collection_stmt))
]


async def _actor(db: Any, who: ResourcePrincipal, collection: Collection) -> tuple[str, str]:
    """``(user, basis)``: whose edit right a job runs under (``imports.access``)."""
    if who.user_id is None:  # pragma: no cover - require_view admits only signed-in callers
        raise UploadNotFound("Upload not found")
    return who.user_id, await access.basis(db, who, collection)


@router.post("/collections/{collection_id}/imports", status_code=202, dependencies=[require_view])
async def create_import(
    collection: CollectionEdit,
    who: Principal,
    db: Annotated[Any, Depends(get_db)],
    kind: Annotated[str, Form(max_length=40)],
    mapping: Annotated[str, Form(max_length=20_000)] = "{}",
    source_url: Annotated[str | None, Form(max_length=2000)] = None,
    auto_run_prompts: Annotated[bool, Form()] = True,
    file: Annotated[UploadFile | None, File()] = None,
) -> ImportJobOut:
    user, basis = await _actor(db, who, collection)
    row = await start_import(
        _runtime(),
        _tenant(),
        collection,
        kind=kind,
        mapping=mapping,
        source_url=source_url or None,
        upload=file.file if file is not None else None,
        auto_run_prompts=auto_run_prompts,
        created_by=user,
        access_basis=basis,
    )
    return job_out(row)


@router.post(
    "/collections/{collection_id}/imports/zip", status_code=201, dependencies=[require_view]
)
async def create_zip_import(
    body: ZipCreate,
    request: Request,
    collection: CollectionEdit,
    who: Principal,
    db: Annotated[Any, Depends(get_db)],
) -> ZipCreated:
    user, basis = await _actor(db, who, collection)
    job, (token, ticket, urls, presigned) = await zip_upload.start(
        _runtime(),
        _tenant(),
        collection,
        filename=body.filename,
        size=body.size,
        mapping=body.mapping,
        owner=user,
        secret=host_secret(request),
        auto_run_prompts=body.auto_run_prompts,
        access_basis=basis,
    )
    upload = DirectCreated(
        upload_id=token,
        part_size=ticket.part_size,
        part_urls=urls,
        direct=presigned,
        expires_in=constants.DIRECT_UPLOAD_TTL_SECONDS,
    )
    return ZipCreated(job_id=job.id, upload=upload)


@router.post("/imports/{job_id}/extract", status_code=202, dependencies=[require_view])
async def extract_zip_import(
    job_id: uuid.UUID,
    body: ZipExtract,
    collection: JobCollection,
    who: Principal,
    db=Depends(get_db),
) -> ImportJobOut:
    runtime, tenant = _runtime(), _tenant()
    actor = await _actor(db, who, collection)  # the extractor takes the job over
    claimed = {p.no: p.etag for p in body.parts}
    generation = await zip_upload.seal(runtime, tenant, job_id, claimed, actor)
    await launch_sealed(runtime, tenant, job_id, generation)
    return job_out(await controls.get(runtime, tenant, job_id))


@router.get("/collections/{collection_id}/imports", dependencies=[require_view])
async def list_imports(collection: CollectionEdit, db=Depends(get_db)) -> ImportJobPage:
    stmt = (
        select(ImportJob)
        .where(ImportJob.collection_id == collection.id)
        .order_by(ImportJob.created_at.desc())
        .limit(LIST_MAX)
    )
    return ImportJobPage(items=[job_out(r) for r in (await db.execute(stmt)).scalars()])


@router.get("/imports/{job_id}", dependencies=[require_view])
async def get_import(
    job_id: uuid.UUID, collection: JobCollection, db=Depends(get_db)
) -> ImportJobOut:
    stmt = select(ImportJob).where(ImportJob.id == job_id, ImportJob.collection_id == collection.id)
    return job_out((await db.execute(stmt)).scalar_one())


@router.post("/imports/{job_id}/pause", dependencies=[require_view])
async def pause_import(job_id: uuid.UUID, collection: JobCollection) -> ImportJobOut:
    return job_out(await controls.pause(_runtime(), _tenant(), job_id))


@router.post("/imports/{job_id}/resume", status_code=202, dependencies=[require_view])
async def resume_import(
    job_id: uuid.UUID, collection: JobCollection, who: Principal, db=Depends(get_db)
) -> ImportJobOut:
    actor = await _actor(db, who, collection)
    return job_out(await controls.resume(_runtime(), _tenant(), job_id, actor=actor))


@router.post("/imports/{job_id}/restart", status_code=202, dependencies=[require_view])
async def restart_import(
    job_id: uuid.UUID, collection: JobCollection, who: Principal, db=Depends(get_db)
) -> ImportJobOut:
    actor = await _actor(db, who, collection)
    return job_out(await controls.restart(_runtime(), _tenant(), job_id, actor=actor))


@router.post("/imports/{job_id}/retry-failed", status_code=202, dependencies=[require_view])
async def retry_failed_import(
    job_id: uuid.UUID, collection: JobCollection, who: Principal, db=Depends(get_db)
) -> ImportJobOut:
    actor = await _actor(db, who, collection)
    return job_out(await controls.retry_failed(_runtime(), _tenant(), job_id, actor=actor))


@router.delete("/imports/{job_id}", status_code=204, dependencies=[require_view])
async def delete_import(job_id: uuid.UUID, collection: JobCollection) -> Response:
    await controls.delete_job(_runtime(), _tenant(), job_id)
    return Response(status_code=204)
