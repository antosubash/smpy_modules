"""Content snapshots: take, download, upload, and the restore approval gate.

Taking and staging need ``pagebuilder.publish``; only ``pagebuilder.approve``
can apply one. Self-approval is allowed, matching the page workflow — imports
are not held to a stricter rule than pages without a deliberate decision to
tighten both.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from pagebuilder.contracts.schemas import (
    ImportApplyResponse,
    ImportDecisionRequest,
    PendingImportRead,
    SnapshotCreateRequest,
    SnapshotListResponse,
    SnapshotRead,
)
from pagebuilder.deps import get_snapshot_service
from pagebuilder.endpoints.api._deps import require_approve, require_publish
from pagebuilder.snapshots.service import SnapshotService

router = APIRouter()

_ZIP_MEDIA_TYPE = "application/zip"


def _actor(request: Request) -> str | None:
    user = getattr(request.state, "user", None)
    return getattr(user, "email", None) if user else None


@router.get("/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(
    service: SnapshotService = Depends(get_snapshot_service),
) -> SnapshotListResponse:
    return SnapshotListResponse(
        items=[SnapshotRead.model_validate(s) for s in await service.list()]
    )


@router.post(
    "/snapshots",
    response_model=SnapshotRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_publish],
)
async def take_snapshot(
    body: SnapshotCreateRequest | None = None,
    service: SnapshotService = Depends(get_snapshot_service),
) -> SnapshotRead:
    snapshot = await service.take(body.note if body else None)
    return SnapshotRead.model_validate(snapshot)


@router.get("/snapshots/{snapshot_id}/download", dependencies=[require_publish])
async def download_snapshot(
    snapshot_id: int,
    service: SnapshotService = Depends(get_snapshot_service),
) -> FileResponse:
    # A temp file rather than an in-memory buffer: a bundle legitimately holds
    # a whole media library, which is not something to hold twice in RAM.
    # ``delete=False`` because FileResponse streams it after this returns; the
    # background task below is what removes it.
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
        target = Path(handle.name)
    await service.download(snapshot_id, target)
    return FileResponse(
        target,
        media_type=_ZIP_MEDIA_TYPE,
        filename=f"content-snapshot-{snapshot_id}.zip",
        background=BackgroundTask(target.unlink, missing_ok=True),
    )


@router.post(
    "/snapshots/upload",
    response_model=SnapshotRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_publish],
)
async def upload_snapshot(
    file: UploadFile,
    service: SnapshotService = Depends(get_snapshot_service),
) -> SnapshotRead:
    snapshot = await service.upload(await file.read(), note=file.filename)
    return SnapshotRead.model_validate(snapshot)


@router.delete(
    "/snapshots/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_publish],
)
async def delete_snapshot(
    snapshot_id: int,
    service: SnapshotService = Depends(get_snapshot_service),
) -> None:
    await service.delete(snapshot_id)


@router.post(
    "/snapshots/{snapshot_id}/restore",
    response_model=PendingImportRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_publish],
)
async def request_restore(
    snapshot_id: int,
    service: SnapshotService = Depends(get_snapshot_service),
) -> PendingImportRead:
    """Stage a restore for approval. Nothing is written to the site here."""
    staged = await service.request_restore(snapshot_id)
    return PendingImportRead.model_validate(staged)


@router.get("/imports/pending", response_model=PendingImportRead | None)
async def get_pending_import(
    service: SnapshotService = Depends(get_snapshot_service),
) -> PendingImportRead | None:
    staged = await service.pending()
    return PendingImportRead.model_validate(staged) if staged else None


@router.post(
    "/imports/{import_id}/approve",
    response_model=ImportApplyResponse,
    dependencies=[require_approve],
)
async def approve_import(
    import_id: int,
    request: Request,
    service: SnapshotService = Depends(get_snapshot_service),
) -> ImportApplyResponse:
    result = await service.approve(import_id, _actor(request))
    return ImportApplyResponse.model_validate(result)


@router.post(
    "/imports/{import_id}/reject",
    response_model=PendingImportRead,
    dependencies=[require_approve],
)
async def reject_import(
    import_id: int,
    request: Request,
    body: ImportDecisionRequest | None = None,
    service: SnapshotService = Depends(get_snapshot_service),
) -> PendingImportRead:
    staged = await service.reject(
        import_id, _actor(request), body.note if body else None
    )
    return PendingImportRead.model_validate(staged)
