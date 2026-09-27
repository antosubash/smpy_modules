"""The reduce index as a maintained aggregate: every transition, by delta.

Phase 5 §5.2. A reduce row is a *fold* over many records rather than a
projection of one, so it cannot be rewritten wholesale on a write the way the
map index rows are — it has to be **moved**, by the difference between what a
record contributed before the write and what it contributes after. Every test
here is one transition of that, and the standard it is held to is always the
same: *the stored table must equal a from-scratch recompute*.

The rebuild/verify half lives in ``test_reduce_verify.py`` and the live
``GROUP BY`` in ``test_aggregate.py``, for the 300-line cap.
"""

from __future__ import annotations

from decimal import Decimal

from sm_records.index.reduce import ReduceSpec, register_reduce_provider
from sm_records.index.reduce_rebuild import recompute, verify_type
from sm_records.models import IndexReduce, RecordStatus
from sm_records.services import records as record_service
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


async def test_create_inserts_the_group_then_increments_it(db, order_type, settings):
    spec = state_spec()
    register_reduce_provider(spec)
    await make(db, order_type, settings, "CA", 10)
    assert await stored(db, order_type) == {"CA": (1, Decimal("10.00000"))}
    await make(db, order_type, settings, "CA", 5)
    assert await stored(db, order_type) == {"CA": (2, Decimal("15.00000"))}
    await make(db, order_type, settings, "NY", 7)
    await assert_matches_recompute(db, order_type, spec)


async def test_a_record_with_no_group_is_in_none(db, order_type, settings):
    """``group_by`` returning ``None`` is how a spec declines a record — not an
    "unknown" bucket it never asked for."""
    spec = state_spec()
    register_reduce_provider(spec)
    await record_service.create_record(
        db, order_type, data={"total": "3", "name": "n"}, settings=settings
    )
    assert await stored(db, order_type) == {}
    await assert_matches_recompute(db, order_type, spec)


async def test_update_that_changes_the_group_moves_the_record(db, order_type, settings):
    spec = state_spec()
    register_reduce_provider(spec)
    record = await make(db, order_type, settings, "CA", 10)
    await make(db, order_type, settings, "CA", 4)

    await record_service.update_record(
        db,
        order_type,
        record,
        expected_version=record.version,
        data={"state": "NY", "total": "10", "name": "n"},
        settings=settings,
    )
    assert await stored(db, order_type) == {
        "CA": (1, Decimal("4.00000")),
        "NY": (1, Decimal("10.00000")),
    }
    await assert_matches_recompute(db, order_type, spec)


async def test_update_that_changes_only_the_value_leaves_the_group(db, order_type, settings):
    spec = state_spec()
    register_reduce_provider(spec)
    record = await make(db, order_type, settings, "CA", 10)
    await record_service.update_record(
        db,
        order_type,
        record,
        expected_version=record.version,
        data={"state": "CA", "total": "25", "name": "n"},
        settings=settings,
    )
    assert await stored(db, order_type) == {"CA": (1, Decimal("25.00000"))}
    await assert_matches_recompute(db, order_type, spec)


async def test_the_last_record_of_a_group_deletes_its_row(db, order_type, settings):
    """A group at zero is removed, not left at zero: the table is exactly the
    set of non-empty groups, which is what makes it comparable to a recompute
    row for row."""
    spec = state_spec()
    register_reduce_provider(spec)
    record = await make(db, order_type, settings, "CA", 10)
    await record_service.update_record(
        db,
        order_type,
        record,
        expected_version=record.version,
        data={"state": "NY", "total": "10", "name": "n"},
        settings=settings,
    )
    assert "CA" not in await stored(db, order_type)


async def test_trash_decrements_restore_increments_purge_does_nothing(db, order_type, settings):
    """The three lifecycle transitions, in the order they happen to one record.

    A trashed record is **not** counted — unlike a map index row, which stays
    in place because every query joins back to the record where the framework
    hides it. A reduce row has no record to join back to, so a trashed record
    left counted would be counted forever.
    """
    spec = state_spec()
    register_reduce_provider(spec)
    record = await make(db, order_type, settings, "CA", 10)
    await make(db, order_type, settings, "CA", 2)

    await record_service.soft_delete_record(db, order_type, record, settings=settings)
    assert await stored(db, order_type) == {"CA": (1, Decimal("2.00000"))}
    await assert_matches_recompute(db, order_type, spec)

    await record_service.restore_record(db, order_type, record, settings=settings)
    assert await stored(db, order_type) == {"CA": (2, Decimal("12.00000"))}
    await assert_matches_recompute(db, order_type, spec)

    await record_service.soft_delete_record(db, order_type, record, settings=settings)
    await record_service.hard_delete_record(db, order_type, record)
    # Purge of a trashed row: already decremented, so nothing moves.
    assert await stored(db, order_type) == {"CA": (1, Decimal("2.00000"))}
    await assert_matches_recompute(db, order_type, spec)


async def test_a_spec_with_no_value_stores_a_null_sum(db, order_type, settings):
    spec = state_spec(with_value=False)
    register_reduce_provider(spec)
    await make(db, order_type, settings, "CA", 10)
    assert await stored(db, order_type) == {"CA": (1, None)}
    assert await verify_type(db, order_type, batch_size=50) == []


async def test_deleting_the_type_removes_its_groups(db, order_type, settings):
    spec = state_spec()
    register_reduce_provider(spec)
    await make(db, order_type, settings, "CA", 10)
    await record_service.purge_type_records(db, order_type)
    assert await stored(db, order_type) == {}


async def test_the_write_path_is_unchanged_with_no_spec_registered(
    db_state, db, order_type, settings
):
    """**The inert-when-unused test.** Phase 5 §0 makes one promise about every
    feature built ahead of its threshold: a host that never opts in runs
    exactly the Phase 4 code paths. For the reduce index that is a statement
    count, which is a property of the code and the same on any backend.

    Measured rather than reasoned about, because the failure mode is a
    ``SELECT`` or an ``UPDATE`` added to every write of every install in the
    world for a table none of them has a row in.
    """
    from tests.perf._bench import capture

    with capture(db_state.engine) as baseline:
        await make(db, order_type, settings, "CA", 1, name="a")
    register_reduce_provider(state_spec())
    # Into the group the baseline write just made, so this is the ordinary
    # increment and not a group's first sight (which costs the insert as well).
    with capture(db_state.engine) as first:
        await make(db, order_type, settings, "CA", 2, name="b")
    with capture(db_state.engine) as later:
        await make(db, order_type, settings, "CA", 3, name="c")

    assert later.count == baseline.count + 1, (
        f"a registered spec costs {later.count - baseline.count} statements per write, not 1"
    )
    # A group's *first* sight costs four, once ever: the ``UPDATE`` that
    # matches nothing, the savepoint that lets a racing insert be recovered
    # from, the insert, and its release. Pinned so the ordinary-write number
    # above cannot quietly become this one.
    assert first.count == baseline.count + 4


async def test_an_edit_that_moves_nothing_costs_nothing(db_state, db, order_type, settings):
    """A spec whose contribution is unchanged issues no statement at all — the
    delta is computed in Python and the database is simply not told."""
    from tests.perf._bench import capture

    register_reduce_provider(state_spec())
    record = await make(db, order_type, settings, "CA", 10)
    with capture(db_state.engine) as box:
        await record_service.update_record(
            db,
            order_type,
            record,
            expected_version=record.version,
            data={"state": "CA", "total": "10", "name": "changed"},
            settings=settings,
        )
    assert box.matching("records_index_reduce") == []
