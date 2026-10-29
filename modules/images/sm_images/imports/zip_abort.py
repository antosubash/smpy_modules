"""Aborting a ZIP import's upload when its ``uploading`` job is deleted
(``cleanup.delete_job``): :func:`abort_upload`."""

from __future__ import annotations

import uuid

from simple_module_db import finalize_session

from sm_images.errors import UploadNotFound as Gone
from sm_images.imports.zip_upload import session_ticket
from sm_images.ingest import upload_session as state
from sm_images.models import ImportJob
from sm_images.pipeline.runtime import Runtime

__all__ = ["abort_upload"]


async def abort_upload(runtime: Runtime, tenant: str, row: ImportJob) -> None:
    """Abort an ``uploading`` job's upload before the job goes: the session
    ``open -> aborted`` (a compare-and-set; a seal holding it is a 409
    ``upload_in_progress`` and the delete waits), then its parts and staged
    object are discarded and the session recorded clean. A cleanup that fails
    leaves ``cleaned_at`` NULL for the reaper."""
    if row.upload_session_id is None:
        return
    try:
        ticket = await session_ticket(runtime, tenant, row)
    except Gone:
        return
    async with runtime.session_factory() as db:
        try:
            claimed = await state.claim_abort(db, ticket)
        except Gone:
            claimed = False
        if not claimed:
            await db.rollback()
            return  # completed: the job owns the object now
        try:
            await state.discard(
                db, runtime.store(), ticket.key, ticket.upload, uuid.UUID(ticket.image)
            )
        except Exception:
            await db.rollback()
            return
        await state.mark_cleaned(db, uuid.UUID(ticket.session))
        await finalize_session(db)
