"""A URL item's own database phases in ``images.download_items``
(:mod:`sm_images.imports.download`): its claim, a deferral that hands it back
to reconcile, and the layer-3 dedupe that settles it as a duplicate before any
byte moves. Each is one short transaction, fenced on the claim token and the
job's generation.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Final

from simple_module_db import finalize_session
from sqlalchemy import or_, select, update

from sm_images import constants
from sm_images.imports import jobs, settle
from sm_images.imports.jobs import SYNC, now
from sm_images.ingest import dedupe
from sm_images.models import ImportItem, ImportJob
from sm_images.models.enums import ItemStatus, JobStatus
from sm_images.pipeline.runtime import Runtime

__all__ = ["CLAIM_SECONDS", "claim", "defer", "duplicate"]

CLAIM_SECONDS: Final = 900
"""How long a claim holds an item: longer than one item's worst case
(``retrying.INLINE_ATTEMPTS`` fetches of ``download_timeout`` plus the waits)."""


async def claim(
    runtime: Runtime, tenant: str, job_id: uuid.UUID, generation: int, item_id: int
) -> tuple[ImportItem, str] | None:
    """Hold the item for this message: ``(row, token)``, or ``None`` to skip it."""
    token = uuid.uuid4().hex
    stamp = now()
    running = select(ImportJob.id).where(
        ImportJob.id == job_id,
        ImportJob.tenant_id == tenant,
        ImportJob.status == JobStatus.RUNNING,
        ImportJob.generation == generation,
    )
    stmt = (
        update(ImportItem)
        .where(
            ImportItem.id == item_id,
            ImportItem.tenant_id == tenant,
            ImportItem.job_id == job_id,
            ImportItem.status == ItemStatus.PENDING,
            or_(ImportItem.claim_token.is_(None), ImportItem.claim_expires_at < stamp),
            or_(ImportItem.next_attempt_at.is_(None), ImportItem.next_attempt_at <= stamp),
            ImportItem.job_id.in_(running.scalar_subquery()),
        )
        .values(
            claim_token=token,
            claim_expires_at=stamp + timedelta(seconds=CLAIM_SECONDS),
            claim_generation=generation,
            updated_at=stamp,
        )
        .returning(ImportItem.id)
        .execution_options(**SYNC)
    )
    async with runtime.session_factory() as db:
        row = None
        if (await db.execute(stmt)).first() is not None:
            found = select(ImportItem).where(
                ImportItem.id == item_id, ImportItem.tenant_id == tenant
            )
            row = (await db.execute(found)).scalar_one()
            db.expunge(row)
        await finalize_session(db)
    return None if row is None else (row, token)


async def defer(
    runtime: Runtime,
    tenant: str,
    job: tuple,
    item_id: int,
    token: str,
    code: str,
    attempts: int,
    delay: float | None = None,
) -> None:
    """Leave the item ``pending`` and release the claim, for reconcile to re-send
    once ``delay`` seconds have passed - only while this claim, of this
    generation, is still the job's current one. A deferral is progress for the
    poison-job breaker (``defer_progress``): the server said when to come back."""
    job_id, generation = job
    current = select(ImportJob.id).where(
        ImportJob.id == job_id,
        ImportJob.tenant_id == tenant,
        ImportJob.generation == generation,
    )
    async with runtime.session_factory() as db:
        deferred = await db.execute(
            update(ImportItem)
            .where(
                ImportItem.id == item_id,
                ImportItem.tenant_id == tenant,
                ImportItem.status == ItemStatus.PENDING,
                ImportItem.claim_token == token,
                ImportItem.claim_generation == generation,
                ImportItem.job_id.in_(current.scalar_subquery()),
            )
            .values(
                attempts=ImportItem.attempts + attempts,
                last_error=code,
                next_attempt_at=None if delay is None else now() + timedelta(seconds=delay),
                claim_token=None,
                claim_expires_at=None,
                claim_generation=None,
                updated_at=now(),
            )
            .returning(ImportItem.id)
            .execution_options(**SYNC)
        )
        if deferred.first() is not None:
            counted = ImportJob.defer_progress + 1
            stmt = update(ImportJob).where(ImportJob.id.in_(current.scalar_subquery()))
            await db.execute(stmt.values(defer_progress=counted).execution_options(**SYNC))
        await finalize_session(db)


async def duplicate(runtime: Runtime, tenant: str, job: tuple, coll, item, token: str) -> bool:
    """Layer 3, before any byte moves: settle as a duplicate of an existing image."""
    job_id, generation = job
    async with runtime.session_factory() as db:
        dup = await dedupe.find_external(db, coll.id, constants.SOURCE_IMPORT, item.external_id)
        if dup is not None:
            kept = await settle.mark_item(
                db, tenant, item.id, ItemStatus.DUPLICATE, image_id=dup, token=token
            )
            deltas = {ItemStatus.DUPLICATE: 1}
            if kept and not await jobs.bump(db, tenant, job_id, deltas, generation):
                await db.rollback()
                return True
        await finalize_session(db)
    return dup is not None
