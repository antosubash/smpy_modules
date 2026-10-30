"""``images.reconcile``'s image-dispatch recovery (:mod:`sm_images.jobs.reconcile`).

* a ``running`` step run with *no* lease (an older writer) is first put back
  to ``pending``, or it would never expire;
* step runs ``pending`` for longer than the cutoff, or ``running`` with an
  expired lease, are dispatched again - the claim's conditional ``UPDATE``
  makes a duplicate harmless;
* placeholder skips whose step is enabled and installed again are dispatched,
  which reopens them (:mod:`sm_images.jobs.placeholders`);
* images whose processing cycle never concluded are dispatched, which decides
  ``ImageProcessed`` once.

Each image is dispatched on its own: one that fails is logged and counted as
``failed_dispatches``, and the rest still go.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from functools import partial
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import and_, or_, select, update

from sm_images.jobs.placeholders import reopenable_images
from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline.orchestrate import submit_dispatch
from sm_images.pipeline.runtime import Runtime

__all__ = ["BATCH", "dispatch_images", "ids", "repair_unleased"]

logger = logging.getLogger(__name__)

BATCH = 500


async def ids(runtime: Runtime, stmt: Any, column: Any) -> list[Any]:
    """Every id ``stmt`` selects, in keyset batches."""
    out: list[Any] = []
    after = None
    while True:
        page = stmt.order_by(column).limit(BATCH)
        if after is not None:
            page = page.where(column > after)
        async with runtime.session_factory() as db:
            rows = list((await db.execute(page)).scalars())
            await finalize_session(db)
        out += rows
        if len(rows) < BATCH:
            return out
        after = rows[-1]


async def repair_unleased(runtime: Runtime, tenant: str, cutoff: datetime) -> int:
    async with runtime.session_factory() as db:
        stmt = (
            update(StepRun)
            .where(
                StepRun.tenant_id == tenant,
                StepRun.status == StepStatus.RUNNING,
                StepRun.lease_expires_at.is_(None),
                or_(StepRun.started_at.is_(None), StepRun.started_at < cutoff),
            )
            .values(status=StepStatus.PENDING, lease_token=None)
            .returning(StepRun.id)
            .execution_options(synchronize_session=False)
        )
        n = len((await db.execute(stmt)).all())
        await finalize_session(db)
    return n


def _stranded(tenant: str, now: datetime, cutoff: datetime) -> Any:
    """Runs of live images in live collections only: dead work is not re-sent."""
    return (
        select(StepRun.image_id)
        .distinct()
        .join(Image, Image.id == StepRun.image_id)
        .join(Collection, Collection.id == Image.collection_id)
        .where(
            StepRun.tenant_id == tenant,
            Image.tenant_id == tenant,
            Image.is_deleted.is_(False),
            Collection.is_deleted.is_(False),
            or_(
                and_(StepRun.status == StepStatus.PENDING, StepRun.created_at < cutoff),
                and_(StepRun.status == StepStatus.RUNNING, StepRun.lease_expires_at < now),
            ),
        )
    )


def _unconcluded(tenant: str, cutoff: datetime) -> Any:
    return select(Image.id).where(
        Image.tenant_id == tenant,
        Image.processed_generation < Image.processing_generation,
        Image.created_at < cutoff,
    )


async def dispatch_images(
    runtime: Runtime, tenant: str, now: datetime, cutoff: datetime
) -> Counter[str]:
    """Dispatch every stranded, unconcluded or reopenable image once."""
    stranded = await ids(runtime, _stranded(tenant, now, cutoff), StepRun.image_id)
    unconcluded = await ids(runtime, _unconcluded(tenant, cutoff), Image.id)
    reopen = await reopenable_images(runtime, tenant, partial(ids, runtime))
    done: Counter[str] = Counter(reopened=len(reopen))
    for image_id in dict.fromkeys([*stranded, *unconcluded, *reopen]):
        try:
            await submit_dispatch(runtime, tenant, image_id)
        except Exception:
            logger.exception("images.reconcile.dispatch_failed image=%s", image_id)
            done["failed_dispatches"] += 1
            continue
        done["dispatched"] += 1
    return done
