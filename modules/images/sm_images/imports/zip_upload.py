"""Uploading a ZIP for import: :func:`start` and :func:`seal`.

The archive travels like a direct image upload (``ingest.multipart``): an
``images_upload_session`` with its lease, parts presigned straight to storage
or - on a backend that cannot presign - relayed through this app. The key is
the job's own staging key, named by the job from the start (so deleting the
job, and the janitor, know it).

* :func:`start` - the job (``uploading``) and the session, in one commit.
* :func:`seal` - the extract call. It claims the session (``completing``, so
  every later part or complete call is a 409), assembles the parts, ``head``s
  the object - its size must be the declared one and at most ``zip_max_bytes``
  - and records the size and the fingerprint (``zip_source``). Then **one
  transaction**: the job's compare-and-set ``uploading -> running`` (same
  generation, same session), the key's intent cleared, the session
  ``completed``. Only then is the runner launched. A refusal after assembly
  fails the job and hands the session to the reaper (``aborted``); parts that
  do not add up hand it back ``open`` so the client can re-send them.
* :func:`fail_upload` - ``uploading -> failed``; reconcile uses it too, for a
  job whose upload expired (``recover.expire_uploads``).
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from file_storage.contracts.service import StorageError
from pydantic import ValidationError
from simple_module_db import finalize_session, tenant_context
from sqlalchemy import select, update

from sm_images.errors import FileTooLarge, ImagesError, PartsMismatch
from sm_images.errors import UploadNotFound as Gone
from sm_images.imports import jobs, terminal
from sm_images.imports.jobs import SYNC, now, where
from sm_images.imports.lookup import conflict, get
from sm_images.imports.mapping import MappingError
from sm_images.imports.service import invalid
from sm_images.imports.zip_entries import zip_mapping
from sm_images.imports.zip_source import parts_fingerprint, sha_fingerprint
from sm_images.ingest import multipart
from sm_images.ingest import upload_session as state
from sm_images.ingest.ticket import Ticket
from sm_images.models import Collection, ImportJob, UploadSession, UploadStatus
from sm_images.models.enums import ImportKind, JobStatus
from sm_images.pipeline.runtime import Runtime
from sm_images.storage import keys as storage_keys
from sm_images.storage.intents import clear_intents

__all__ = ["ZIP_CONTENT_TYPE", "fail_upload", "seal", "session_ticket", "start"]

ZIP_CONTENT_TYPE: Final = "application/zip"
_GONE = "Upload not found"


async def start(
    runtime: Runtime,
    tenant: str,
    collection: Collection,
    *,
    filename: str,
    size: int,
    mapping: dict[str, Any] | None,
    owner: str,
    secret: str,
    auto_run_prompts: bool = True,
    access_basis: str | None = None,
    admission: Any = None,
) -> tuple[ImportJob, tuple[str, Ticket, list[str], bool]]:
    """The ``uploading`` job and its upload: ``(job, (upload_id, ticket, part_urls, direct))``."""
    try:
        parsed = zip_mapping(mapping)
    except (ValidationError, MappingError) as exc:
        raise invalid("invalid_mapping", "The mapping is not valid for a ZIP import") from exc
    if size > runtime.settings().zip_max_bytes:
        raise FileTooLarge("The archive is larger than the ZIP size limit")
    job_id = uuid.uuid4()
    key = storage_keys.import_key(tenant, str(job_id), f"source.{uuid.uuid4().hex[:12]}.zip")
    with tenant_context(tenant):
        async with runtime.session_factory() as db:
            upload = await multipart.open_upload(
                db,
                runtime.store(),
                collection,
                key=key,
                image_id=uuid.uuid4(),
                size=size,
                content_type=ZIP_CONTENT_TYPE,
                filename=filename,
                owner=owner,
                secret=secret,
                kind="zip",
                intent_factory=runtime.session_factory,
                admission=admission,
            )
            db.add(
                ImportJob(
                    id=job_id,
                    collection_id=collection.id,
                    kind=ImportKind.ZIP,
                    status=JobStatus.UPLOADING,
                    mapping=parsed.model_dump(exclude_none=True),
                    staged_keys=[key],
                    upload_session_id=uuid.UUID(upload[1].session),
                    heartbeat_at=now(),
                    auto_run_prompts=auto_run_prompts,
                    created_by=owner,
                    run_as=owner,
                    access_basis=access_basis,
                )
            )
            await finalize_session(db)
    return await get(runtime, tenant, job_id), upload


async def session_ticket(runtime: Runtime, tenant: str, row: ImportJob) -> Ticket:
    """The archive's upload, as the ticket the multipart helpers take."""
    stmt = select(UploadSession).where(
        UploadSession.id == row.upload_session_id, UploadSession.tenant_id == tenant
    )
    async with runtime.session_factory() as db:
        found = (await db.execute(stmt)).scalar_one_or_none()
        ticket = None
        if found is not None:
            ticket = Ticket(
                session=str(found.id),
                key=found.storage_key,
                upload=found.backend_upload_id,
                collection=str(found.collection_id),
                image=str(found.image_id),
                tenant=tenant,
                owner="",
                size=found.size,
                part_size=found.part_size,
                filename="",
                content_type=found.content_type,
                kind="zip",
            )
        await db.rollback()
    if ticket is None:
        raise Gone(_GONE)
    return ticket


async def _measure(runtime: Runtime, ticket: Ticket, parts: list[Any]) -> tuple[int, str]:
    """``(size, fingerprint)`` of the assembled object, within the limits."""
    store = runtime.store()
    found = await store.head(ticket.key)
    if found is None:
        raise Gone(_GONE)
    size, etag = found
    if size != ticket.size:
        raise PartsMismatch("The stored archive is not the declared size")
    if size > runtime.settings().zip_max_bytes:
        raise FileTooLarge("The archive is larger than the ZIP size limit")
    if etag:
        return size, etag.strip().strip('"')
    derived = parts_fingerprint(parts, ticket.part_size)
    return size, derived or await sha_fingerprint(store, ticket.key)


async def _seal_row(
    db: Any, tenant: str, row: ImportJob, ticket: Ticket, token: uuid.UUID, size: int, fp: str
) -> int:
    """The seal's job CAS; with ``row.run_as`` set by :func:`seal`, the job runs
    under the extractor's right from here on (``imports.access``)."""
    stmt = (
        update(ImportJob)
        .where(
            *where(tenant, row.id),
            ImportJob.status == JobStatus.UPLOADING,
            ImportJob.generation == row.generation,
            ImportJob.upload_session_id == row.upload_session_id,
        )
        .values(
            status=JobStatus.RUNNING,
            source_key=ticket.key,
            staged_keys=[ticket.key],
            source_etag=fp,
            source_size=size,
            run_as=row.run_as,
            access_basis=row.access_basis,
            heartbeat_at=now(),
            updated_at=now(),
        )
        .returning(ImportJob.generation)
        .execution_options(**SYNC)
    )
    found = (await db.execute(stmt)).first()
    if found is None:
        await db.rollback()
        raise conflict("job_changed", "The import changed meanwhile")
    await clear_intents(db, [ticket.key])
    await state.finish(db, ticket, token)  # completing -> completed, or roll back
    await finalize_session(db)
    return int(found[0])


async def fail_upload(runtime: Runtime, tenant: str, row: ImportJob, code: str) -> None:
    """``uploading -> failed`` (this generation only), then its staging released."""
    stmt = (
        update(ImportJob)
        .where(
            *where(tenant, row.id),
            ImportJob.status == JobStatus.UPLOADING,
            ImportJob.generation == row.generation,
        )
        .values(
            status=JobStatus.FAILED,
            errors=[*(row.errors or []), {"code": code, "at": now().isoformat()}],
            updated_at=now(),
        )
        .returning(ImportJob.id)
    )
    if await jobs.returning_one(runtime, stmt) is not None:
        await terminal.release_staging(runtime, tenant, row.id, row.generation)


async def seal(
    runtime: Runtime,
    tenant: str,
    job_id: uuid.UUID,
    claimed: dict[int, str | None],
    actor: tuple[str, str] | None = None,
) -> int:
    """Seal the uploaded archive to its job; the generation to run it under.
    ``actor`` - the extractor and the basis of their right - takes the job over."""
    with tenant_context(tenant):
        row = await get(runtime, tenant, job_id)  # detached: safe to amend
        if actor is not None:
            row.run_as, row.access_basis = actor
        if row.kind is not ImportKind.ZIP or row.upload_session_id is None:
            raise conflict("not_a_zip_import", "This import does not take an archive")
        if row.status is not JobStatus.UPLOADING:
            raise conflict("already_sealed", "This archive was already handed to its import")
        ticket = await session_ticket(runtime, tenant, row)
        async with runtime.session_factory() as db:
            token = await state.claim_complete(db, ticket)
            if token is None:
                raise conflict("already_sealed", "This archive was already handed to its import")
            assembled = False
            try:
                try:
                    parts = await multipart.assemble(runtime.store(), ticket, claimed)
                except StorageError as exc:
                    raise Gone(_GONE) from exc
                assembled = True
                await state.renew(db, ticket, token)
                size, fingerprint = await _measure(runtime, ticket, parts)
                await state.renew(db, ticket, token)
                return await _seal_row(db, tenant, row, ticket, token, size, fingerprint)
            except Exception as exc:
                await state.settle(
                    db, ticket, token, UploadStatus.ABORTED if assembled else UploadStatus.OPEN
                )
                if assembled:
                    code = exc.code if isinstance(exc, ImagesError) and exc.code else "seal_failed"
                    await fail_upload(runtime, tenant, row, code)
                raise
