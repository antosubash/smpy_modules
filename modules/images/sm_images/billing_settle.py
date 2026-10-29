"""Settling the outbox (``images_billing_op``): claim, run, finish.

**Every op is claimed before it runs.** :func:`claim` is a conditional
``UPDATE`` - pending, and unclaimed or its claim expired - that stamps a fresh
``claim_token``. Only the claimant runs it, and its finishing write is
conditional on that token, so two settlers (the after-commit attempt and
reconcile; or reconcile and an executor whose claim expired) never both finish
one op. A writer that dies holding a claim is taken over once it expires.

**An image's ``swap`` ops run one at a time, oldest first** (:func:`_due`).
So while one is pending nothing else changes the hold the image names, and a
retry of its billing call (same key: billing returns the same hold) and the
install that follows see the same old hold.

Running an op is :mod:`sm_images.billing_install`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import aliased

from sm_images import billing, billing_ops
from sm_images.models import BillingOp
from sm_images.models.billing_op import OP_RELEASE, OP_SWAP

__all__ = ["CLAIM", "ClaimLost", "Op", "claim", "settle"]

logger = logging.getLogger(__name__)
PAGE = 100
PAGES = 10
CLAIM = timedelta(minutes=5)
BACKOFF = timedelta(minutes=1)
BACKOFF_MAX = timedelta(hours=1)
BILLING_OP_MAX_AGE = timedelta(days=7)
"""No op older than this calls billing: billing keeps a key's outcome for 30
days after it settles (its retention), so a call is always answered by it."""
OP_EXPIRED = "op_expired"


_COLUMNS = (
    BillingOp.id,
    BillingOp.op,
    BillingOp.image_id,
    BillingOp.hold_id,
    BillingOp.old_hold_id,
    BillingOp.quantity,
    BillingOp.idempotency_key,
    BillingOp.attempts,
    BillingOp.created_at,
)


@dataclass(frozen=True)
class Op:
    """What a settler reads of a claimed op."""

    id: int
    op: str
    image_id: uuid.UUID | None
    hold_id: str | None
    old_hold_id: str | None
    quantity: int
    idempotency_key: str | None
    attempts: int
    created_at: datetime


class ClaimLost(Exception):  # noqa: N818 - reads as the condition
    """Another settler took this op over (our claim expired): stop touching it."""


def _due(tenant: str, now: datetime, ids: list[int] | None) -> Any:
    older = aliased(BillingOp)
    queued = exists().where(
        older.tenant_id == tenant,
        older.image_id == BillingOp.image_id,
        older.op == OP_SWAP,
        older.done_at.is_(None),
        older.id < BillingOp.id,
    )
    stmt = select(BillingOp.id).where(
        BillingOp.tenant_id == tenant,
        BillingOp.done_at.is_(None),
        or_(BillingOp.next_attempt_at.is_(None), BillingOp.next_attempt_at <= now),
        or_(BillingOp.claim_token.is_(None), BillingOp.claim_expires_at <= now),
        or_(BillingOp.op != OP_SWAP, ~queued),
    )
    if ids is not None:
        stmt = stmt.where(BillingOp.id.in_(ids))
    return stmt.order_by(BillingOp.id).limit(PAGE)


async def settle(
    factory: Any, tenant: str, ids: list[int] | None = None, now: datetime | None = None
) -> int:
    """Claim and run the due ops (``ids`` only, when given); how many finished.
    Bounded to :data:`PAGES` pages; a page that finished nothing ends it."""
    now = now or datetime.now(UTC)
    done = 0
    for _ in range(PAGES):
        async with factory() as db:
            found = list((await db.execute(_due(tenant, now, ids))).scalars())
            await finalize_session(db)
        ran = [await _attempt(factory, tenant, op_id, now) for op_id in found]
        done += sum(ran)
        if not any(ran):
            break
    return done


async def claim(factory: Any, tenant: str, op_id: int, now: datetime) -> tuple[str, Op] | None:
    """Take the op for this settler; ``(token, op)`` or ``None`` when another
    holds it (or it is done)."""
    token = uuid.uuid4().hex
    async with factory() as db:
        got = await db.execute(
            update(BillingOp)
            .where(
                BillingOp.id == op_id,
                BillingOp.tenant_id == tenant,
                BillingOp.done_at.is_(None),
                or_(BillingOp.claim_token.is_(None), BillingOp.claim_expires_at <= now),
            )
            .values(claim_token=token, claim_expires_at=now + CLAIM)
            .returning(*_COLUMNS)
            .execution_options(synchronize_session=False)
        )
        op = got.first()
        await finalize_session(db)
    return None if op is None else (token, Op(**op._mapping))


async def _attempt(factory: Any, tenant: str, op_id: int, now: datetime) -> bool:
    claimed = await claim(factory, tenant, op_id, now)
    if claimed is None:
        return False
    token, op = claimed
    from sm_images import billing_install as run

    mine = billing_ops.Claimed(op.id, token, op.idempotency_key or "")
    try:
        meter = billing.storage_meter(factory)
        if meter is None:
            await run.finish_op(factory, mine, None)
        elif op.op != OP_RELEASE and _expired(op, now):
            await run.finish_op(factory, mine, None, OP_EXPIRED)  # the repair takes over
        elif op.op == OP_RELEASE:
            await run.release_hold(meter, op.hold_id)
            await run.finish_op(factory, mine, op.hold_id)
        else:
            await run.swap(factory, tenant, op, mine, meter)
    except ClaimLost:
        return False
    except Exception as exc:
        logger.warning("images.billing_op.failed op=%s id=%s", op.op, op.id, exc_info=True)
        await _failed(factory, op, token, now, exc)
        return False
    return True


def _expired(op: Op, now: datetime) -> bool:
    created = op.created_at if op.created_at.tzinfo else op.created_at.replace(tzinfo=UTC)
    return created < now - BILLING_OP_MAX_AGE


async def _failed(factory: Any, op: Op, token: str, now: datetime, exc: Exception) -> None:
    attempts = op.attempts + 1
    wait = min(BACKOFF * 2 ** min(attempts - 1, 10), BACKOFF_MAX)
    async with factory() as db:
        await db.execute(
            update(BillingOp)
            .where(BillingOp.id == op.id, BillingOp.claim_token == token)
            .values(
                attempts=attempts,
                next_attempt_at=now + wait,
                last_error=f"{type(exc).__name__}: {exc}"[:500],
                claim_token=None,
                claim_expires_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        await finalize_session(db)
