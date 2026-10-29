"""A job runs under someone's edit right, and stops when that right is gone.

Every import route is an ``edit`` on the collection - but only at the door. A
job then runs for hours in workers, so the right it was accepted under is
recorded on the job (``run_as``, ``access_basis``: :func:`basis`) and
re-checked by the worker (:func:`guard`) when a runner starts, before each
chunk it records and before each download batch fetches anything. Without
it, an editor whose share is revoked keeps importing into the collection.

What still counts as edit, from a worker:

* ``run_as`` owns the collection;
* an active (unexpired) edit share names them - the same ``EXISTS`` the access
  policy builds (``sharing.policy.share_exists_for``);
* the right came from ``images.manage`` and :func:`holds_manage` confirms it
  still holds (``imports.manage_right``: the framework has no request-free
  permission resolver, so it reads the grant tables). An answer of "cannot
  tell" keeps the job.

A job with no ``run_as`` (made by code, or before this existed) is not checked.
A lost right cancels the job like a delete would: fenced on the generation,
which it bumps, so anything in flight loses at its next fenced write; status
``cancelled``, error ``access_revoked``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from sharing.policy import share_exists_for
from simple_module_core.resources import ACTION_EDIT, ResourcePrincipal
from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images.access import COLLECTION_RESOURCE
from sm_images.imports.chunk import Stopped
from sm_images.imports.jobs import CLAIMABLE, load, now, where
from sm_images.imports.manage_right import holds_manage
from sm_images.imports.terminal import ERRORS_MAX, release_staging
from sm_images.models import Collection, ImportJob
from sm_images.models.enums import JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = [
    "ACCESS_REVOKED",
    "MANAGE",
    "OWNER",
    "SHARE",
    "basis",
    "guard",
    "holds_manage",
    "may_edit",
    "revoke",
]

logger = logging.getLogger(__name__)

OWNER: Final = "owner"
SHARE: Final = "share"
MANAGE: Final = "manage"
ACCESS_REVOKED: Final = "access_revoked"

_SHARES = share_exists_for(COLLECTION_RESOURCE, Collection.id)


def _shared(user_id: str, collection_id: uuid.UUID) -> Any:
    clause = _SHARES(ResourcePrincipal(user_id=user_id), ACTION_EDIT)
    return select(Collection.id).where(Collection.id == collection_id, clause)


async def basis(db: Any, who: ResourcePrincipal, collection: Collection) -> str:
    """Where ``who``'s edit right on ``collection`` comes from (the caller has
    already established that it has one)."""
    if who.user_id is None:
        return MANAGE
    if collection.owner_id == who.user_id:
        return OWNER
    shared = (await db.execute(_shared(who.user_id, collection.id))).first()
    return SHARE if shared is not None else MANAGE


async def may_edit(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> bool:
    """Whether the job's ``run_as`` still holds edit on its collection."""
    stmt = (
        select(ImportJob.run_as, ImportJob.access_basis, Collection.id, Collection.owner_id)
        .join(Collection, Collection.id == ImportJob.collection_id)
        .where(*where(tenant, job_id))
    )
    async with runtime.session_factory() as db:
        row = (await db.execute(stmt)).first()
        shared = None
        if row is not None and row[0] is not None and row[3] != row[0]:
            shared = (await db.execute(_shared(row[0], row[2]))).first()
        await finalize_session(db)
    if row is None:
        return True  # gone, or its collection is: the runner's own checks stop it
    run_as, recorded, _, owner = row
    if run_as is None or owner == run_as or shared is not None:
        return True
    if recorded == MANAGE:
        held = await holds_manage(runtime, tenant, run_as)
        if held is None:
            logger.info("images.import.manage_unverifiable job=%s", job_id)
        return held is not False
    return False


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
