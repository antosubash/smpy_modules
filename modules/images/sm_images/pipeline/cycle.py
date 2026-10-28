"""Run resets and the processing cycle (split from :mod:`.claim`, same rules).

A reset never touches a run someone holds a live lease on. ``bump_cycle`` and
``mark_processed`` are the two halves of "``ImageProcessed`` once per cycle":
an accepted reset starts a cycle, and only the conditional ``UPDATE`` that
moves ``processed_generation`` up to it may emit the event.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, update

from sm_images.models import Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline.claim import _owned, _run

__all__ = ["bump_cycle", "mark_processed", "release", "reset_runs"]

_SYNC = {"synchronize_session": False}


async def release(
    db: Any, tenant: str, image_id: uuid.UUID, step: str, token: uuid.UUID, now: datetime
) -> bool:
    """Give a still-owned run back to ``pending`` (its result could not be published)."""
    stmt = (
        update(StepRun)
        .where(*_run(tenant, image_id, step), *_owned(token, now))
        .values(status=StepStatus.PENDING, lease_token=None, lease_expires_at=None)
        .returning(StepRun.id)
        .execution_options(**_SYNC)
    )
    return (await db.execute(stmt)).first() is not None


async def reset_runs(
    db: Any, tenant: str, image_id: uuid.UUID, steps: list[str], now: datetime
) -> int:
    """Back to ``pending`` - never a run someone holds a live lease on."""
    if not steps:
        return 0
    live = and_(StepRun.status == StepStatus.RUNNING, StepRun.lease_expires_at >= now)
    stmt = (
        update(StepRun)
        .where(*_run(tenant, image_id), StepRun.step.in_(steps), ~live)
        .values(
            status=StepStatus.PENDING,
            lease_token=None,
            lease_expires_at=None,
            error_code=None,
            error_message=None,
            output=None,
            started_at=None,
            finished_at=None,
        )
        .returning(StepRun.id)
        .execution_options(**_SYNC)
    )
    return len((await db.execute(stmt)).all())


async def bump_cycle(db: Any, tenant: str, image_id: uuid.UUID) -> None:
    """A new processing cycle: ``ImageProcessed`` may be decided once more."""
    await db.execute(
        update(Image)
        .where(Image.id == image_id, Image.tenant_id == tenant)
        .values(processing_generation=Image.processing_generation + 1)
        .execution_options(**_SYNC)
    )


async def mark_processed(db: Any, tenant: str, image_id: uuid.UUID) -> tuple[Any, int] | None:
    """Conclude the current cycle; ``(collection_id, cycle)`` for the one winner."""
    stmt = (
        update(Image)
        .where(
            Image.id == image_id,
            Image.tenant_id == tenant,
            Image.is_deleted.is_(False),
            Image.processed_generation < Image.processing_generation,
        )
        .values(processed_generation=Image.processing_generation)
        .returning(Image.collection_id, Image.processing_generation)
        .execution_options(**_SYNC)
    )
    row = (await db.execute(stmt)).first()
    return None if row is None else (row[0], row[1])
