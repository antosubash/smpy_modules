"""The fenced SQL of the pipeline: lock, claim, settle, complete, renew, reset.

Every statement is typed SQLAlchemy DML (enum labels, UUIDs and timestamps
bound through the column types) with an explicit ``tenant_id`` predicate: the
framework's soft-delete filter does not reach ``UPDATE``/``DELETE``, and the
images guard sees mappers only.

**One lock order.** Everything that plans, settles, completes or resets an
image's runs first takes :func:`lock_image` - a no-op ``UPDATE`` of the image
row. On Postgres that is the row lock; on SQLite it acquires the writer lock
up front, so a transaction never reads a stale snapshot it later has to
upgrade (``SQLITE_BUSY_SNAPSHOT``, which ignores ``busy_timeout``). It sets
``updated_at`` to itself: not audited, and it does not move a rendition's
cache key (``rendition_url`` versions on ``updated_at``).

**Ownership** of a run is ``(image, step, lease_token)`` *and an unexpired
lease*: a slow worker whose lease expired cannot complete, even if nobody has
reclaimed it yet. A zero-row result means the lease was lost and the work is
discarded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, or_, select, update

from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline.step import StepOutcome

__all__ = [
    "Claim",
    "LockedImage",
    "LostLease",
    "claim",
    "complete",
    "load_runs",
    "lock_image",
    "renew",
    "settle",
]

_SYNC = {"synchronize_session": False}
CODE_MAX = 100
MESSAGE_MAX = 2000


class LostLease(Exception):  # noqa: N818 - a signal, not an error
    """The run's lease is gone: another worker owns it, or it expired."""


@dataclass(frozen=True)
class Claim:
    step: str
    token: uuid.UUID


@dataclass(frozen=True)
class LockedImage:
    id: uuid.UUID
    collection_id: uuid.UUID
    display_generation: int
    display_key: str | None


def _run(tenant: str, image_id: uuid.UUID, step: str | None = None) -> list[Any]:
    where = [StepRun.tenant_id == tenant, StepRun.image_id == image_id]
    if step is not None:
        where.append(StepRun.step == step)
    return where


def _owned(token: uuid.UUID, now: datetime) -> list[Any]:
    return [
        StepRun.status == StepStatus.RUNNING,
        StepRun.lease_token == token,
        StepRun.lease_expires_at >= now,
    ]


def _claimable(now: datetime) -> Any:
    return or_(
        StepRun.status == StepStatus.PENDING,
        and_(StepRun.status == StepStatus.RUNNING, StepRun.lease_expires_at < now),
    )


async def lock_image(db: Any, tenant: str, image_id: uuid.UUID) -> LockedImage | None:
    """Serialise this image's planning; ``None`` if it (or its collection) is gone."""
    live_collection = exists().where(
        Collection.id == Image.collection_id,
        Collection.tenant_id == tenant,
        Collection.is_deleted.is_(False),
    )
    stmt = (
        update(Image)
        .where(
            Image.id == image_id,
            Image.tenant_id == tenant,
            Image.is_deleted.is_(False),
            live_collection,
        )
        .values(updated_at=Image.updated_at)
        .returning(Image.id, Image.collection_id, Image.display_generation, Image.display_key)
        .execution_options(**_SYNC)
    )
    row = (await db.execute(stmt)).first()
    return None if row is None else LockedImage(*row)


async def load_runs(db: Any, tenant: str, image_id: uuid.UUID) -> dict[str, StepRun]:
    # ``populate_existing``: the fenced DML here never synchronises the
    # session, so a second load in one transaction must re-read the rows.
    stmt = select(StepRun).where(*_run(tenant, image_id)).execution_options(populate_existing=True)
    rows = (await db.execute(stmt)).scalars()
    return {r.step: r for r in rows}


async def insert_missing(db: Any, image_id: uuid.UUID, steps: list[str]) -> None:
    """Rows for enabled steps that have none. Safe without ``ON CONFLICT``: every
    inserter holds the image lock, and ingest's rows commit with the image."""
    for step in steps:
        db.add(StepRun(image_id=image_id, step=step))
    if steps:
        await db.flush()


async def settle(
    db: Any,
    tenant: str,
    image_id: uuid.UUID,
    step: str,
    status: StepStatus,
    code: str,
    now: datetime,
) -> None:
    """Executor-decided final state for a pending or abandoned run."""
    await db.execute(
        update(StepRun)
        .where(*_run(tenant, image_id, step), _claimable(now))
        .values(
            status=status,
            error_code=code[:CODE_MAX],
            error_message=None,
            output=None,
            finished_at=now,
            lease_token=None,
            lease_expires_at=None,
        )
        .execution_options(**_SYNC)
    )


async def claim(
    db: Any, tenant: str, image_id: uuid.UUID, steps: list[str], now: datetime, lease_s: int
) -> list[Claim]:
    """One conditional ``UPDATE … RETURNING``: the rows it returns are ours."""
    if not steps:
        return []
    token = uuid.uuid4()
    stmt = (
        update(StepRun)
        .where(*_run(tenant, image_id), StepRun.step.in_(steps), _claimable(now))
        .values(
            status=StepStatus.RUNNING,
            lease_token=token,
            lease_expires_at=now + timedelta(seconds=lease_s),
            attempts=StepRun.attempts + 1,
            started_at=now,
            finished_at=None,
            error_code=None,
            error_message=None,
            output=None,
        )
        .returning(StepRun.step, StepRun.lease_token)
        .execution_options(**_SYNC)
    )
    rows = (await db.execute(stmt)).all()
    return sorted((Claim(step, tok) for step, tok in rows), key=lambda c: c.step)


def _terminal(outcome: StepOutcome) -> dict[str, Any]:
    if outcome.status == "completed":
        return {"status": StepStatus.COMPLETED, "output": outcome.output, "error_code": None}
    if outcome.status == "skipped":
        output = {"reason": outcome.reason} if outcome.reason else None
        code = outcome.code[:CODE_MAX] if outcome.code else None
        return {"status": StepStatus.SKIPPED, "output": output, "error_code": code}
    return {
        "status": StepStatus.FAILED,
        "output": None,
        "error_code": (outcome.code or "failed")[:CODE_MAX],
        "error_message": (outcome.message or "")[:MESSAGE_MAX] or None,
    }


async def complete(
    db: Any,
    tenant: str,
    image_id: uuid.UUID,
    step: str,
    token: uuid.UUID,
    outcome: StepOutcome,
    now: datetime,
    *,
    version: int | None,
    revision: int | None = None,
) -> bool:
    """Record ``outcome`` if the lease is still ours; ``False`` = lost, discard."""
    values = {"error_message": None, **_terminal(outcome)}
    stmt = (
        update(StepRun)
        .where(*_run(tenant, image_id, step), *_owned(token, now))
        .values(
            **values,
            finished_at=now,
            lease_token=None,
            lease_expires_at=None,
            step_version=version,
            prompt_revision=revision,
        )
        .returning(StepRun.id)
        .execution_options(**_SYNC)
    )
    return (await db.execute(stmt)).first() is not None


async def renew(
    db: Any,
    tenant: str,
    image_id: uuid.UUID,
    step: str,
    token: uuid.UUID,
    now: datetime,
    lease_s: int,
) -> bool:
    """Push the lease out; ``False`` once it is lost (it is never revived)."""
    stmt = (
        update(StepRun)
        .where(*_run(tenant, image_id, step), *_owned(token, now))
        .values(lease_expires_at=now + timedelta(seconds=lease_s))
        .returning(StepRun.id)
        .execution_options(**_SYNC)
    )
    return (await db.execute(stmt)).first() is not None
