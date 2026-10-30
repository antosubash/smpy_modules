"""Billing-op claims and completion run on the database's clock, like the op's
``not_after``: a worker whose wall clock is off neither shortens a writer's
claim nor lets a settler take a live one over, and ``done_at`` (which the
sweep's retention compares) is the database's time too."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sm_images.core.billing import ops as billing_ops
from sm_images.core.billing import settle as billing_settle
from sm_images.core.tenancy import DEFAULT_TENANT as T
from sm_images.ingest.slots import INGEST_CLAIM
from sm_images.models import BillingOp
from sm_images.models.billing_op import OP_INGEST
from sqlalchemy import select

SKEW = timedelta(hours=2)


def _clock(monkeypatch, module, offset: timedelta) -> None:
    """``module``'s wall clock runs ``offset`` away from the database's."""

    class Skewed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + offset

    monkeypatch.setattr(module, "datetime", Skewed)


def _utc(at: datetime) -> datetime:
    return at if at.tzinfo else at.replace(tzinfo=UTC)


async def _open(pipe) -> billing_ops.Claimed:
    async with pipe.db_state.session_factory() as s:
        key = f"k-{uuid.uuid4().hex}"
        claimed = await billing_ops.open_op(
            s, OP_INGEST, uuid.uuid4(), 10, key, claim=INGEST_CLAIM, old=None
        )
        await s.commit()
    return claimed


async def _row(pipe, op_id: int) -> BillingOp:
    async with pipe.db_state.session_factory() as s:
        return (await s.execute(select(BillingOp).where(BillingOp.id == op_id))).scalar_one()


async def test_a_writer_with_a_slow_clock_still_holds_its_claim(pipe, monkeypatch):
    _clock(monkeypatch, billing_ops, -SKEW)  # the writer's clock is two hours behind
    claimed = await _open(pipe)
    row = await _row(pipe, claimed.op_id)
    expected = datetime.now(UTC) + INGEST_CLAIM
    assert abs(_utc(row.claim_expires_at) - expected) < timedelta(seconds=5)
    assert await billing_ops.settle(pipe.db_state.session_factory, T) == 0  # not taken over
    assert (await _row(pipe, claimed.op_id)).claim_token == claimed.token


async def test_a_settler_with_a_fast_clock_does_not_take_a_live_claim(pipe, monkeypatch):
    claimed = await _open(pipe)
    _clock(monkeypatch, billing_settle, SKEW)  # the reconcile worker runs two hours ahead
    assert await billing_ops.settle(pipe.db_state.session_factory, T) == 0
    row = await _row(pipe, claimed.op_id)
    assert (row.claim_token, row.done_at) == (claimed.token, None)


async def test_done_at_is_the_databases_time(pipe, monkeypatch):
    claimed = await _open(pipe)
    _clock(monkeypatch, billing_ops, -SKEW)
    async with pipe.db_state.session_factory() as s:
        assert await billing_ops.finish(s, claimed, None)
        await s.commit()
    row = await _row(pipe, claimed.op_id)
    assert abs(_utc(row.done_at) - datetime.now(UTC)) < timedelta(seconds=5)


async def test_the_sweep_measures_age_on_the_databases_clock(pipe, monkeypatch):
    claimed = await _open(pipe)
    async with pipe.db_state.session_factory() as s:
        assert await billing_ops.finish(s, claimed, None)
        row = await s.get(BillingOp, claimed.op_id)
        row.repaired_at = datetime.now(UTC)  # examined: only its age keeps it now
        await s.commit()
    factory = pipe.db_state.session_factory
    _clock(monkeypatch, billing_ops, timedelta(days=30))  # a janitor far ahead
    assert await billing_ops.sweep(factory, T, timedelta(days=7)) == 0  # done just now
    assert (await _row(pipe, claimed.op_id)).done_at is not None
    assert await billing_ops.sweep(factory, T, -timedelta(minutes=1)) == 1  # sweepable by age
