"""A job runs under someone's edit right, and stops when that right is gone.

Every import route is an ``edit`` on the collection - but only at the door. A
job then runs for hours in workers, so the right it was accepted under is
recorded on the job (``run_as``, ``access_basis``: :func:`basis`) and
re-checked by the worker (:func:`guard`) when a runner starts, before each
chunk it records and before each download batch fetches anything. Without
it, an editor whose share is revoked keeps importing into the collection.

What still counts as edit, from a worker, is decided by
:func:`sm_images.access.starter_right.holds_right` (shared with regroups,
whole-collection restarts and prompt runs): ownership, an active edit share, or
``images.manage`` for a user still active in the tenant.

A job with no ``run_as`` (made by code, or before this existed) is not checked.
A lost right cancels the job like a delete would: fenced on the generation,
which it bumps, so anything in flight loses at its next fenced write; status
``cancelled``, error ``access_revoked``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from simple_module_core.resources import ResourcePrincipal
from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images.access.starter_right import MANAGE, OWNER, SHARE, holds_right, shared_edit
from sm_images.imports.chunk import Stopped
from sm_images.imports.jobs import CLAIMABLE, load, now, where
from sm_images.imports.manage_right import manager_active
from sm_images.imports.terminal import ERRORS_MAX, release_staging
from sm_images.models import Collection, ImportJob
from sm_images.models.enums import JobStatus
from sm_images.pipeline.runtime import Runtime, first_row

__all__ = [
    "ACCESS_REVOKED",
    "MANAGE",
    "OWNER",
    "SHARE",
    "basis",
    "guard",
    "manager_active",
    "may_edit",
    "revoke",
    "shared_edit",
]

logger = logging.getLogger(__name__)

ACCESS_REVOKED: Final = "access_revoked"


async def basis(db: Any, who: ResourcePrincipal, collection: Collection) -> str:
    """Where ``who``'s edit right on ``collection`` comes from (the caller has
    already established that it has one)."""
    if who.user_id is None:
        return MANAGE
    if collection.owner_id == who.user_id:
        return OWNER
    shared = (await db.execute(shared_edit(who.user_id, collection.id))).first()
    return SHARE if shared is not None else MANAGE


async def may_edit(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> bool:
    """Whether the job's ``run_as`` still holds edit on its collection."""
    stmt = select(ImportJob.run_as, ImportJob.access_basis, ImportJob.collection_id).where(
        *where(tenant, job_id)
    )
    row = await first_row(runtime, stmt)
    if row is None:
        return True  # gone: the runner's own checks stop it
    run_as, recorded, collection_id = row
    return await holds_right(runtime, tenant, collection_id, run_as, recorded)


async def revoke(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> bool:
    """Cancel the job (``access_revoked``) if ``generation`` still owns it,
    bumping the generation; ``False`` when a newer one does."""
    async with runtime.session_factory() as db:
        row = await load(db, tenant, job_id, lock=True)
        if row is None or row.generation != generation or row.status not in CLAIMABLE:
            await db.rollback()
            return False
        row.status = JobStatus.CANCELLED
        row.generation = generation + 1
        row.updated_at = now()
        entry = {"code": ACCESS_REVOKED, "at": now().isoformat()}
        row.errors = [*(row.errors or []), entry][-ERRORS_MAX:]
        await finalize_session(db)
    logger.info("images.import.access_revoked job=%s", job_id)
    await release_staging(runtime, tenant, job_id, generation + 1)
    return True


async def guard(runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int) -> None:
    """Raise :class:`Stopped` - after cancelling the job - once its ``run_as``
    has lost edit."""
    if await may_edit(runtime, tenant, job_id):
        return
    await revoke(runtime, tenant, job_id, generation)
    raise Stopped()
