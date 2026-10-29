"""Settling the outbox (``images_billing_op``): claim, run, finish.

**Every op is claimed before it runs.** :func:`claim` is a conditional
``UPDATE`` - pending, and unclaimed or its claim expired - that stamps a fresh
``claim_token`` and ``claim_expires_at``. Only the claimant runs it, and every
later write (rehold progress, done, failed) is conditional on that token, so
two settlers (the after-commit attempt and reconcile, two reconcile ticks)
never run one op twice. A settler that dies holding a claim is replaced once
the claim expires (:data:`CLAIM`).

**A release waits** for two things: the op named by ``after_id`` is done, and
billing confirms that the hold the image names *now* is committed
(:func:`_safe_to_release`). The first alone is not enough: a ``rehold`` that
found the image naming a newer hold is done without having installed
anything, and releasing the old hold then would leave the image counted by
nothing until the newer hold's own commit lands.

Ops are tenant rows; every statement here also names the tenant.
:data:`HOOK` is a test seam called at each step (deterministic interleavings).
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import aliased

from sm_images import billing
from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import OP_COMMIT, OP_REHOLD, OP_RELEASE

__all__ = ["CLAIM", "HOOK", "ClaimLost", "Op", "claim", "hook", "save", "settle"]

logger = logging.getLogger(__name__)
PAGE = 100
PAGES = 10
CLAIM = timedelta(minutes=5)
BACKOFF = timedelta(minutes=1)
BACKOFF_MAX = timedelta(hours=1)

_DONE, _FINISHED, _WAIT = "done", "finished", "wait"

HOOK: Callable[[str, Any], Awaitable[None]] | None = None
"""Tests only: awaited as ``HOOK(point, op)`` at each step of a settlement."""

_COLUMNS = (
    BillingOp.id,
    BillingOp.op,
    BillingOp.image_id,
    BillingOp.hold_id,
    BillingOp.attempts,
    BillingOp.replacement_hold_id,
    BillingOp.generation,
)


@dataclass(frozen=True)
class Op:
    """What a settler reads of a claimed op."""

    id: int
    op: str
    image_id: uuid.UUID | None
    hold_id: str
    attempts: int
    replacement_hold_id: str | None
    generation: int


class ClaimLost(Exception):  # noqa: N818 - reads as the condition
    """Another settler took this op over (our claim expired): stop touching it."""


async def hook(point: str, op: Any) -> None:
    if HOOK is not None:
        await HOOK(point, op)


def _due(tenant: str, now: datetime, ids: list[int] | None) -> Any:
    prior = aliased(BillingOp)
    waited = exists().where(prior.id == BillingOp.after_id, prior.done_at.is_not(None))
    stmt = select(BillingOp.id).where(
        BillingOp.tenant_id == tenant,
        BillingOp.done_at.is_(None),
        or_(BillingOp.next_attempt_at.is_(None), BillingOp.next_attempt_at <= now),
        or_(BillingOp.claim_token.is_(None), BillingOp.claim_expires_at <= now),
        or_(BillingOp.after_id.is_(None), waited),
    )
    if ids is not None:
        stmt = stmt.where(BillingOp.id.in_(ids))
    return stmt.order_by(BillingOp.id).limit(PAGE)


async def settle(
    factory: Any, tenant: str, ids: list[int] | None = None, now: datetime | None = None
) -> int:
    """Claim and run the due ops (``ids`` only, when given), dependants after
    what they wait for; how many finished. Bounded to :data:`PAGES` pages."""
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


def _mine(op_id: int, token: str) -> list[Any]:
    return [BillingOp.id == op_id, BillingOp.claim_token == token, BillingOp.done_at.is_(None)]


async def claim(factory: Any, tenant: str, op_id: int, now: datetime) -> tuple[str, Op] | None:
    """Take the op for this settler; ``(token, op)`` or ``None`` when another
    settler holds it (or it is done, or not due)."""
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


async def save(factory: Any, op_id: int, token: str, **values: Any) -> None:
    """Persist progress on an op we hold; :class:`ClaimLost` when we do not."""
    async with factory() as db:
        got = await db.execute(
            update(BillingOp)
            .where(*_mine(op_id, token))
            .values(**values)
            .returning(BillingOp.id)
            .execution_options(synchronize_session=False)
        )
        held = got.first() is not None
        await finalize_session(db)
    if not held:
        raise ClaimLost(op_id)


async def _attempt(factory: Any, tenant: str, op_id: int, now: datetime) -> bool:
    claimed = await claim(factory, tenant, op_id, now)
    if claimed is None:
        return False
    token, op = claimed
    await hook("claimed", op)
    meter = billing.storage_meter(factory)
    try:
        outcome = _DONE if meter is None else await _apply(factory, tenant, op, token, meter)
        if outcome == _WAIT:  # not safe yet: left for a later pass, no attempt counted
            await save(factory, op.id, token, claim_token=None, claim_expires_at=None)
            return False
        if outcome == _DONE:  # a rehold finishes in its own swap (_FINISHED)
            await save(factory, op.id, token, done_at=now, last_error=None, claim_token=None)
    except ClaimLost:
        return False
    except Exception as exc:
        logger.warning("images.billing_op.failed op=%s id=%s", op.op, op.id, exc_info=True)
        await _failed(factory, op, token, now, exc)
        return False
    return True


async def _apply(factory: Any, tenant: str, op: Any, token: str, meter: Any) -> str:
    """Run ``op``: :data:`_DONE` (mark it done), :data:`_FINISHED` (a rehold
    marked itself) or :data:`_WAIT` (a release not safe to run yet)."""
    from sm_billing.contracts.metering import HoldExpired, HoldNotFound

    from sm_images import billing_rehold

    if op.op == OP_RELEASE:
        if not await _safe_to_release(factory, tenant, op, meter):
            return _WAIT
        await meter.release(op.hold_id)
        return _DONE
    if op.op == OP_COMMIT:
        try:
            await meter.commit(op.hold_id)
            return _DONE
        except (HoldExpired, HoldNotFound):
            await save(factory, op.id, token, op=OP_REHOLD)
            op = replace(op, op=OP_REHOLD)
    await billing_rehold.run(factory, tenant, op, token, meter)
    return _FINISHED


async def _safe_to_release(factory: Any, tenant: str, op: Any, meter: Any) -> bool:
    """The image is gone, names no hold, names this very hold, or names a hold
    billing confirms committed."""
    if op.image_id is None:
        return True
    async with factory() as db:
        current = (
            await db.execute(
                select(Image.storage_hold_id)
                .where(Image.id == op.image_id, Image.tenant_id == tenant)
                .execution_options(include_deleted=True)
            )
        ).first()
        await finalize_session(db)
    if current is None or current[0] is None or current[0] == op.hold_id:
        return True
    hold = await meter.get_hold(current[0])
    return hold is not None and hold.status == "committed"


async def _failed(factory: Any, op: Any, token: str, now: datetime, exc: Exception) -> None:
    attempts = op.attempts + 1
    wait = min(BACKOFF * 2 ** min(attempts - 1, 10), BACKOFF_MAX)
    with contextlib.suppress(ClaimLost):  # another settler took over
        await save(
            factory,
            op.id,
            token,
            attempts=attempts,
            next_attempt_at=now + wait,
            last_error=f"{type(exc).__name__}: {exc}"[:500],
            claim_token=None,
            claim_expires_at=None,
        )
