"""The fenced SQL of a group run, on its ``images_prompt_result`` row.

A group result is its own run record: ``status``, ``lease_token``,
``lease_expires_at`` and ``ai_started_at`` play the parts ``images_step_run``
plays for an image step.

* :func:`request` (under :func:`lock_group`) - a run nobody has in flight goes
  to ``pending`` with a *dispatch lease*: until it expires the request counts
  as on its way and a second request is refused. A lost message (delivery is
  at-most-once) therefore blocks nothing past ``step_lease_seconds``.
* :func:`claim` - one conditional ``UPDATE``: a ``pending`` row, or a
  ``running`` one whose lease expired, becomes ours under a new token.
* :func:`renew` and :func:`start_call` - only while the lease is ours;
  ``start_call`` once per lease, so a redelivered message never pays twice.

Every statement names the tenant: the framework's filter does not reach DML.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update

from sm_images.models import Group, PromptResult
from sm_images.models.enums import StepStatus

__all__ = ["claim", "in_flight", "lock_group", "owned", "renew", "request", "start_call", "wanted"]

_SYNC = {"synchronize_session": False}


def _row(tenant: str, prompt_id: uuid.UUID, group_id: uuid.UUID) -> list[Any]:
    return [
        PromptResult.tenant_id == tenant,
        PromptResult.prompt_id == prompt_id,
        PromptResult.group_id == group_id,
    ]


def _owned(token: uuid.UUID, now: datetime) -> list[Any]:
    return [
        PromptResult.status == StepStatus.RUNNING,
        PromptResult.lease_token == token,
        PromptResult.lease_expires_at >= now,
    ]


def owned(row: PromptResult | None, token: uuid.UUID, now: datetime) -> bool:
    return (
        row is not None
        and row.status is StepStatus.RUNNING
        and row.lease_token == token
        and row.lease_expires_at is not None
        and row.lease_expires_at >= now
    )


def in_flight(row: PromptResult, now: datetime) -> bool:
    return (
        row.status in (StepStatus.PENDING, StepStatus.RUNNING)
        and row.lease_expires_at is not None
        and row.lease_expires_at >= now
    )


def wanted(row: PromptResult | None, scope: str, revision: int, now: datetime) -> bool:
    """Whether a request with ``scope`` (``missing|stale|all``) runs this group."""
    if row is None:
        return True
    if in_flight(row, now):
        return False
    if scope == "all" or row.status is not StepStatus.COMPLETED:
        return True
    return scope == "stale" and row.prompt_revision != revision


async def lock_group(db: Any, tenant: str, group_id: uuid.UUID) -> bool:
    """Serialise this group's requests and completions (a no-op ``UPDATE``:
    the row lock on Postgres, the writer lock up front on SQLite)."""
    stmt = (
        update(Group)
        .where(Group.id == group_id, Group.tenant_id == tenant)
        .values(updated_at=Group.updated_at)
        .returning(Group.id)
        .execution_options(**_SYNC)
    )
    return (await db.execute(stmt)).first() is not None


async def load(db: Any, tenant: str, prompt_id: uuid.UUID, group_id: uuid.UUID) -> Any:
    stmt = (
        select(PromptResult)
        .where(*_row(tenant, prompt_id, group_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def request(
    db: Any,
    tenant: str,
    prompt_id: uuid.UUID,
    group_id: uuid.UUID,
    scope: str,
    revision: int,
    now: datetime,
    lease_s: int,
) -> bool:
    """Mark the group's run requested; ``False`` when ``scope`` does not want it
    or it is already in flight. The caller commits, then dispatches."""
    if not await lock_group(db, tenant, group_id):
        return False
    row = await load(db, tenant, prompt_id, group_id)
    if not wanted(row, scope, revision, now):
        return False
    if row is None:
        row = PromptResult(prompt_id=prompt_id, group_id=group_id)
        db.add(row)
    row.status = StepStatus.PENDING
    row.requested_at = now  # what reconcile ages a lost dispatch by
    row.lease_token = None
    row.lease_expires_at = now + timedelta(seconds=lease_s)
    row.ai_started_at = None
    await db.flush()
    return True


async def claim(
    db: Any, tenant: str, prompt_id: uuid.UUID, group_id: uuid.UUID, now: datetime, lease_s: int
) -> uuid.UUID | None:
    token = uuid.uuid4()
    claimable = or_(
        PromptResult.status == StepStatus.PENDING,
        and_(PromptResult.status == StepStatus.RUNNING, PromptResult.lease_expires_at < now),
    )
    stmt = (
        update(PromptResult)
        .where(*_row(tenant, prompt_id, group_id), claimable)
        .values(
            status=StepStatus.RUNNING,
            lease_token=token,
            lease_expires_at=now + timedelta(seconds=lease_s),
            ai_started_at=None,
        )
        .returning(PromptResult.id)
        .execution_options(**_SYNC)
    )
    return token if (await db.execute(stmt)).first() is not None else None


async def renew(
    db: Any,
    tenant: str,
    prompt_id: uuid.UUID,
    group_id: uuid.UUID,
    token: uuid.UUID,
    now: datetime,
    lease_s: int,
) -> bool:
    stmt = (
        update(PromptResult)
        .where(*_row(tenant, prompt_id, group_id), *_owned(token, now))
        .values(lease_expires_at=now + timedelta(seconds=lease_s))
        .returning(PromptResult.id)
        .execution_options(**_SYNC)
    )
    return (await db.execute(stmt)).first() is not None


async def start_call(
    db: Any, tenant: str, prompt_id: uuid.UUID, group_id: uuid.UUID, token: uuid.UUID, now: datetime
) -> bool:
    """Mark the consolidation call started, once per lease (see the module docstring)."""
    stmt = (
        update(PromptResult)
        .where(
            *_row(tenant, prompt_id, group_id),
            *_owned(token, now),
            PromptResult.ai_started_at.is_(None),
        )
        .values(ai_started_at=now)
        .returning(PromptResult.id)
        .execution_options(**_SYNC)
    )
    return (await db.execute(stmt)).first() is not None
