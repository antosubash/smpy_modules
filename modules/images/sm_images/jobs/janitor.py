"""``images.janitor``: the daily clean-up beat (spec §7 "Purge", plan decision 4).

A platform enumerator like ``images.reconcile``, and it reuses its tenant
enumeration (:func:`sm_images.jobs.reconcile.tenants`). Per tenant, under
``tenant_context(t)`` and each in its own session:

* abandoned direct uploads are reclaimed (:func:`reap_expired_uploads`) -
  first, so a purge never races an upload's own clean-up;
* trashed rows past ``janitor_grace_days`` are purged with their objects
  (:func:`sm_images.jobs.purge.purge_expired`);
* staged sources that a finished import job failed to delete itself are
  deleted once past the grace period (:func:`sm_images.ingest.imports.cleanup.reap_staging`);
* storage-billing outbox ops done before the grace period are deleted
  (:func:`sm_images.core.billing.ops.sweep`).

Each is a phase of its own (:func:`sm_images.jobs.phases.run_phases`): one that
raises is logged and counted as ``failed_phases``, and the rest still run.

Then **one narrow platform pass**, under ``all_tenants()``, over the
write-ahead intents (:class:`ObjectIntent` has no tenant - the key embeds it):
:func:`reap_intents` deletes the objects of intents older than the grace
period that no row references - the crash and rollback orphans, and replaced
display generations or renditions whose after-commit delete failed.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from simple_module_db import all_tenants, finalize_session, tenant_context
from sqlalchemy import delete, select, update

from sm_images.core.billing import ops as billing_ops
from sm_images.core.tenancy import all_tenants as tagged
from sm_images.ingest.imports.cleanup import reap_staging
from sm_images.ingest.upload_reaper import reap_expired_uploads
from sm_images.jobs.phases import Phase, run_phases
from sm_images.jobs.purge import MIN_INTENT_AGE, PurgeReport, purge_expired
from sm_images.jobs.reconcile import tenants
from sm_images.models import (
    Collection,
    Image,
    ImportJob,
    ObjectIntent,
    Rendition,
    UploadSession,
    UploadStatus,
)
from sm_images.pipeline.runtime import Runtime

__all__ = [
    "CAP",
    "FAILURE_LIMIT",
    "MIN_INTENT_AGE",
    "IntentReport",
    "PurgeReport",
    "janitor_async",
    "janitor_tenant",
    "purge_expired",
    "reap_intents",
]

logger = logging.getLogger(__name__)

CAP = 1000
FAILURE_LIMIT = 20
"""Failed object deletes after which one intent pass stops trying."""
_CHUNK = 500
_LIVE_UPLOADS = (UploadStatus.OPEN, UploadStatus.COMPLETING)


@dataclass
class IntentReport:
    dry_run: bool
    reaped: list[str] = field(default_factory=list)
    """Unreferenced: object deleted, intent removed (on a dry run: would be)."""
    referenced: list[str] = field(default_factory=list)
    """A row owns the object; only the stale intent is removed."""


def _uuid(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


async def _scalars(db: Any, stmt: Any) -> set[Any]:
    """A deliberate cross-tenant read (the caller entered ``all_tenants()``)."""
    stmt = tagged(stmt.execution_options(include_deleted=True))
    return set((await db.execute(stmt)).scalars())


async def _owned(db: Any, keys: list[str]) -> set[str]:
    """The keys some row (trashed ones included) still points at."""
    found: set[str] = set()
    found |= await _scalars(db, select(Image.storage_key).where(Image.storage_key.in_(keys)))
    found |= await _scalars(db, select(Image.display_key).where(Image.display_key.in_(keys)))
    found |= await _scalars(
        db, select(Rendition.storage_key).where(Rendition.storage_key.in_(keys))
    )
    found |= await _scalars(db, select(ImportJob.source_key).where(ImportJob.source_key.in_(keys)))
    found |= await _scalars(
        db,
        select(UploadSession.storage_key).where(
            UploadSession.storage_key.in_(keys), UploadSession.status.in_(_LIVE_UPLOADS)
        ),
    )
    # A map archive is owned while its collection names it: one a build never
    # published, or one a rebuild or a visibility change replaced, is not.
    found |= await _scalars(db, select(Collection.map_key).where(Collection.map_key.in_(keys)))
    jobs: dict[uuid.UUID, list[str]] = {}
    for key in keys:  # images/<tenant>/imports/<job>/...
        parts = key.split("/")
        if len(parts) >= 5 and parts[2] == "imports" and (job := _uuid(parts[3])):
            jobs.setdefault(job, []).append(key)
    if jobs:
        # Owned only while its job still names it: a terminal job *detaches*
        # its staged keys before deleting them, so a failed delete is reaped here.
        stmt = select(ImportJob.source_key, ImportJob.staged_keys).where(
            ImportJob.id.in_(list(jobs))
        )
        named: set[str] = set()
        for source_key, staged in (await db.execute(tagged(stmt))).all():
            named.update(k for k in [source_key, *(staged or [])] if k)
        found.update(k for keys in jobs.values() for k in keys if k in named)
    return found


async def reap_intents(
    db: Any,
    store: Any,
    *,
    now: datetime,
    grace_days: int,
    dry_run: bool = False,
    cap: int = CAP,
) -> IntentReport:
    """Reap up to ``cap`` intents older than the grace period. The caller has
    entered ``all_tenants()`` and commits. An object whose delete fails keeps
    its intent for the next pass."""
    cutoff = now - max(timedelta(days=grace_days), MIN_INTENT_AGE)
    # An intent whose delete failed before (``attempted_at``) goes to the back:
    # one key that will never delete must not take the whole cap of every pass.
    stmt = (
        select(ObjectIntent.key)
        .where(ObjectIntent.created_at <= cutoff)
        .order_by(
            ObjectIntent.attempted_at.asc().nulls_first(), ObjectIntent.created_at, ObjectIntent.key
        )
        .limit(cap)
    )
    keys = list((await db.execute(stmt)).scalars())
    owned: set[str] = set()
    for i in range(0, len(keys), _CHUNK):
        owned |= await _owned(db, keys[i : i + _CHUNK])
    report = IntentReport(dry_run, [k for k in keys if k not in owned], sorted(owned))
    if dry_run:
        return report
    gone: list[str] = []
    failed: list[str] = []
    for key in report.reaped:
        if len(failed) >= FAILURE_LIMIT:
            break  # storage is down: the rest wait for the next pass
        try:
            await store.delete_keys([key])
            gone.append(key)
        except Exception:
            logger.warning("images.janitor.object_delete_failed key=%s", key, exc_info=True)
            failed.append(key)
    report.reaped = gone
    if failed:
        await db.execute(
            update(ObjectIntent).where(ObjectIntent.key.in_(failed)).values(attempted_at=now)
        )
    done = gone + report.referenced
    for i in range(0, len(done), _CHUNK):
        chunk = done[i : i + _CHUNK]
        await db.execute(delete(ObjectIntent).where(ObjectIntent.key.in_(chunk)))
    return report


async def janitor_tenant(
    runtime: Runtime, tenant: str, now: datetime, *, dry_run: bool = False
) -> Counter[str]:
    """One tenant's clean-up; the caller has bound ``tenant``."""
    store, grace = runtime.store(), runtime.settings().janitor_grace_days
    factory = runtime.session_factory

    async def uploads() -> int:
        async with factory() as db:
            reaped = await reap_expired_uploads(db, store, now, CAP)
            await finalize_session(db)
        return reaped

    async def purge() -> dict[str, int]:
        async with factory() as db:
            report = await purge_expired(
                db, store, now=now, grace_days=grace, dry_run=dry_run, cap=CAP
            )
            await finalize_session(db)
        return {
            "images_purged": len(report.images),
            "collections_purged": len(report.collections),
            "objects_deleted": len(report.keys),
        }

    age = timedelta(days=grace)  # measured on the database's clock, as done_at is
    phases: list[Phase] = [("purge", purge)]
    if not dry_run:
        phases = [
            ("uploads_reaped", uploads),
            *phases,
            ("import_staging_reaped", partial(reap_staging, runtime, tenant, now, grace)),
            ("billing_ops_swept", partial(billing_ops.sweep, factory, tenant, age)),
        ]
    done: Counter[str] = Counter()
    await run_phases(done, "janitor", tenant, phases)
    return done


async def janitor_async(
    runtime: Runtime, now: datetime, *, dry_run: bool = False
) -> dict[str, int]:
    """Every tenant in its own scope, then the platform intent pass. A failure
    is logged and counted and does not stop the rest."""
    total: Counter[str] = Counter()
    for tenant in await tenants(runtime):
        try:
            with tenant_context(tenant):
                total.update(await janitor_tenant(runtime, tenant, now, dry_run=dry_run))
        except Exception:
            logger.exception("images.janitor.tenant_failed tenant=%s", tenant)
            total["failed_tenants"] += 1
    try:
        with all_tenants():
            async with runtime.session_factory() as db:
                report = await reap_intents(
                    db,
                    runtime.store(),
                    now=now,
                    grace_days=runtime.settings().janitor_grace_days,
                    dry_run=dry_run,
                )
                await finalize_session(db)
        total["intents_reaped"] += len(report.reaped)
    except Exception:
        logger.exception("images.janitor.intents_failed")
        total["failed_intent_pass"] += 1
    return dict(total)
