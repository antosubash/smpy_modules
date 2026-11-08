"""``/imports``: upload a Mailchimp export, preview and map it, apply, discard (R12, R16).

``bind_admin`` first, then ``newsletter.manage`` on every route, and the import's list must be
readable to the caller (an unreadable one is a 404). A refusal names a file by index and line,
never by name, and never repeats a cell.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Request, Response
from simple_module_db import finalize_session
from simple_module_db.deps import get_db
from simple_module_db.listeners import current_user_id
from simple_module_hosting.permissions import RequiresPermission
from sm_records.contracts.newsletter import caller_roles
from sm_records.contracts.newsletter_import import ImportTargets
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException

from sm_newsletter.campaigns.access import require_list
from sm_newsletter.core import constants
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_import import ImportBadMapping, ImportNotCsv, ImportTooManyFiles
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.imports import archive, launch, service, staging
from sm_newsletter.imports.constants import MAX_FILES
from sm_newsletter.imports.csv_safe import errors_csv
from sm_newsletter.models import ImportJob
from sm_newsletter.web.schemas.campaigns import parse_payload
from sm_newsletter.web.schemas.imports import (
    ImportOut,
    ImportPatch,
    ImportSummaryOut,
    to_out,
)

router = APIRouter(
    prefix="/imports",
    dependencies=[Depends(bind_admin), Depends(RequiresPermission(constants.PERM_MANAGE))],
)

MAX_FIELDS = 8
"""Non-file parts in the upload form: ``list`` and a few spare."""


async def _targets(db: AsyncSession, tenant: str, job: ImportJob) -> ImportTargets:
    return await staging.targets_for(db, tenant, job.list_type_key)


async def _out(db: AsyncSession, tenant: str, job: ImportJob) -> ImportOut:
    return to_out(job, await _targets(db, tenant, job))


async def _read_upload(request: Request) -> tuple[str, list[UploadFile]]:
    try:
        # ``max_part_size`` limits only non-file parts (the ``list`` field); files spool to disk.
        form = await request.form(
            max_part_size=4 * 1024, max_files=MAX_FILES, max_fields=MAX_FIELDS
        )
    except (MultiPartException, HTTPException) as exc:
        # Starlette words these itself and never quotes the upload; ours are fixed, too.
        too_many = "Too many files" in str(getattr(exc, "message", None) or exc.detail)
        raise (ImportTooManyFiles if too_many else ImportNotCsv) from None
    key = form.get("list")
    files = [f for f in form.getlist("files") if isinstance(f, UploadFile)]
    if not isinstance(key, str) or not key or len(key) > constants.MAX_TYPE_KEY_LEN:
        for f in files:
            await f.close()
        raise NotFound()
    return key, files


@router.post("", response_model=ImportOut, status_code=201)
async def upload(
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> ImportOut:
    key, files = await _read_upload(request)
    try:
        await require_list(db, tenant_id=tenant, list_type_key=key, roles=caller_roles(request))
        job = await staging.stage(
            db,
            tenant_id=tenant,
            list_type_key=key,
            sources=archive.sources([(f.filename or "", f.file) for f in files]),
            created_by=current_user_id.get(),
            now=datetime.now(UTC),
        )
        out = await _out(db, tenant, job)
        await finalize_session(db)
        return out
    finally:
        for f in files:
            await f.close()


@router.get("", response_model=list[ImportSummaryOut])
async def list_imports(
    request: Request, tenant: str = Depends(bind_admin), db: AsyncSession = Depends(get_db)
) -> list[ImportSummaryOut]:
    jobs = await service.list_imports(db, tenant_id=tenant, roles=caller_roles(request))
    return [ImportSummaryOut.model_validate(j) for j in jobs]


async def _job(
    request: Request, db: AsyncSession, tenant: str, import_id: int, *, orphan_ok: bool = False
) -> ImportJob:
    return await service.get_import(
        db, tenant_id=tenant, import_id=import_id, roles=caller_roles(request), orphan_ok=orphan_ok
    )


@router.get("/{import_id}", response_model=ImportOut)
async def get_import(
    import_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> ImportOut:
    return await _out(db, tenant, await _job(request, db, tenant, import_id))


@router.patch("/{import_id}", response_model=ImportOut)
async def set_mapping(
    import_id: int,
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> ImportOut:
    data = parse_payload(ImportPatch, payload, error=ImportBadMapping)
    job = await _job(request, db, tenant, import_id)
    targets = await _targets(db, tenant, job)
    job = await service.set_mapping(
        db, tenant_id=tenant, job=job, raw=data.mapping, targets=targets
    )
    return to_out(job, targets)


@router.post("/{import_id}/apply", response_model=ImportOut, status_code=202)
async def apply(
    import_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> ImportOut:
    job = await _job(request, db, tenant, import_id)
    await service.queue_apply(db, tenant_id=tenant, job=job)
    await finalize_session(db)  # ``queued`` is committed before a worker can see the id
    await launch.launch(request.app, tenant_id=tenant, import_id=import_id)
    return await _out(db, tenant, await _job(request, db, tenant, import_id))


@router.delete("/{import_id}", status_code=204)
async def discard(
    import_id: int,
    request: Request,
    status: Literal["staged", "queued", "running", "done", "failed"] | None = None,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    job = await _job(request, db, tenant, import_id, orphan_ok=True)  # a deleted list's too
    await service.discard(db, tenant_id=tenant, job=job, expected_status=status)
    return Response(status_code=204)


@router.get("/{import_id}/errors.csv")
async def errors(
    import_id: int,
    request: Request,
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    job = await _job(request, db, tenant, import_id)
    return Response(
        errors_csv(job),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="import-{job.id}-errors.csv"',
            "Cache-Control": "no-store",
        },
    )
