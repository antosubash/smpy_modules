"""Shared record test builders."""

from __future__ import annotations
from decimal import Decimal
from sm_records.records.index.reduce import ReduceSpec, register_reduce_provider
from sm_records.records.index.reduce_rebuild import recompute, verify_type
from sm_records.models import IndexReduce, RecordStatus
from sm_records.records.services import records as record_service
from sqlalchemy import select

STATE = "orders_per_state"


def state_spec(with_value: bool = True) -> ReduceSpec:
    """The README's example: orders grouped by ship state, totals folded."""
    return ReduceSpec(
        key=STATE,
        group_by=lambda record, rtype: (record.data or {}).get("state"),
        value=(lambda record, rtype: Decimal((record.data or {}).get("total") or 0))
        if with_value
        else None,
        # What the fold is *of*, which is what a stored reading's ``metric``
        # reports: ``sum:total``, the same string the live reading gives for
        # ``metric=sum:total``. Without it the metric is the bare ``"sum"``.
        value_label="total",
    )


async def stored(db, rtype, key: str = STATE) -> dict[str, tuple[int, Decimal | None]]:
    rows = (
        (
            await db.execute(
                select(IndexReduce).where(IndexReduce.type_id == rtype.id, IndexReduce.key == key)
            )
        )
        .scalars()
        .all()
    )
    return {row.group_value: (int(row.count), row.sum) for row in rows}


async def assert_matches_recompute(db, rtype, spec) -> dict:
    """The invariant every transition below is measured against: whatever the
    deltas did, the table equals what a fresh fold of the records says."""
    live = await recompute(db, rtype, spec, batch_size=50)
    held = await stored(db, rtype, spec.key)
    assert {g: (c, None if s is None else Decimal(s)) for g, (c, s) in held.items()} == {
        g: (c, None if s is None else Decimal(s)) for g, (c, s) in live.items()
    }
    return held


async def make(db, rtype, settings, state, total, name="n"):
    return await record_service.create_record(
        db,
        rtype,
        data={"state": state, "total": str(total), "name": name},
        settings=settings,
        status=RecordStatus.PUBLISHED,
    )
