"""The live ``GROUP BY`` and the maintained aggregate — Phase 5 §5, measured.

Both readings of ``GET /types/{key}/records/aggregate`` go through the real
endpoint, so the numbers carry FastAPI's dependency resolution and the
contract's serialisation the way every other row in this directory does.

What is asserted is shape, never a wall clock: an aggregate is a **constant**
number of statements whatever the type holds, its ``GROUP BY`` reads the index
table through the lookup index rather than scanning ``records_record``, and
``?reduce=`` — the maintained reading — is one indexed read of
``records_index_reduce`` no matter how many records folded into it. That last
pair is the whole argument for a reduce index: the live aggregate is
proportional to the rows it folds, the stored one is proportional to the
*groups*.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sm_records.index.reduce import (
    ReduceSpec,
    clear_reduce_providers,
    register_reduce_provider,
)
from sm_records.index.reduce_rebuild import rebuild_type

from tests.perf._bench import Results, capture, explain, plan_scans_records, repeat
from tests.perf._http import API, get_ok, measure, plan_label
from tests.perf.conftest import REPS, load_type, type_counts

pytestmark = pytest.mark.perf

STATE_KEY = "orders_per_state"


def state_spec() -> ReduceSpec:
    """The README's example: orders grouped by ship state, totals folded."""
    return ReduceSpec(
        key=STATE_KEY,
        group_by=lambda record, rtype: (record.data or {}).get("ship_state"),
        value=lambda record, rtype: Decimal((record.data or {}).get("total") or 0),
    )


@pytest.fixture
def one_reduce_spec():
    """One registered spec, gone again before the next measurement.

    The registry is process-global — which is right for a host and wrong for a
    suite whose next file measures the write path's statement count and would
    silently measure it with a reduce index attached."""
    clear_reduce_providers()
    register_reduce_provider(state_spec())
    try:
        yield state_spec()
    finally:
        clear_reduce_providers()


async def test_live_aggregate_by_kind(perf_client, perf_db, perf_session):
    """One ``group_by`` of every interesting kind, through the endpoint.

    ``ship_state`` is a select (one index row per record), ``customer`` a
    relation (one row, reached by ``target_uuid``), ``tags`` a multiselect
    (several rows per record, so the group counts sum to more than the type
    holds — the honest reading, see §5.1) and ``status`` a fixed column, which
    needs no join at all.
    """
    counts = await type_counts(perf_session)
    cases = [
        ("order", "ship_state (select)", "group_by=ship_state"),
        ("order", "ship_state, sum:total", "group_by=ship_state&metric=sum:total"),
        ("order", "ship_state, min/max placed_at", "group_by=ship_state&metric=max:placed_at"),
        ("order", "customer (ref)", "group_by=customer"),
        ("order", "status (fixed column)", "group_by=status"),
        ("product", "tags (multiselect)", "group_by=tags"),
        (
            "order",
            "ship_state, filtered",
            "group_by=ship_state&filter=placed_at:gte:2024-01-01T00:00:00Z",
        ),
    ]
    for key, label, query in cases:
        box, plan = await measure(
            perf_client,
            f"GET {key} aggregate, {label}",
            f"{API}/{key}/records/aggregate?{query}",
            counts.get(key, 0),
            perf_db.engine,
            perf_session,
            plan_of="GROUP BY",
        )
        assert box.count <= 4, f"{label}: {box.count} statements"
        assert not plan_scans_records(plan), plan


async def test_aggregate_statement_count_is_flat(perf_client, perf_db, perf_session):
    """The same aggregate over the two biggest types in the dataset.

    ``order`` holds three times what ``product`` does and the statement count
    must not notice — the fold happens in the database, in one statement.
    """
    seen = set()
    for key, group_by in (("order", "ship_state"), ("product", "category")):
        with capture(perf_db.engine) as box:
            await get_ok(perf_client, f"{API}/{key}/records/aggregate?group_by={group_by}")
        seen.add(box.count)
    assert len(seen) == 1, f"aggregate statement count varies by type: {sorted(seen)}"
    Results.note(f"aggregate costs {seen.pop()} statements on any type")


async def test_stored_against_live_for_the_same_key(perf_db_copy, one_reduce_spec, tmp_path):
    """``?reduce=`` against the ``GROUP BY`` it maintains — §5.1's own claim.

    The two are asked on the same data for the same key, which is exactly what
    the endpoint exists to let a caller do; here it is also the measurement.
    The rebuild that fills the table is timed too, because it is what a host
    pays once per registered spec.
    """
    from httpx import ASGITransport, AsyncClient

    from tests.app_harness import build_app

    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "order")
        counts = await type_counts(session)
        n = counts.get("order", 0)
        import time

        began = time.perf_counter()
        written = await rebuild_type(session, rtype, batch_size=500)
        await session.commit()
        elapsed = (time.perf_counter() - began) * 1000.0
        from tests.perf._bench import Timing

        Results.add(
            f"reduce rebuild_type(order, {STATE_KEY})",
            n,
            Timing([elapsed]),
            statements="batched",
            plan=f"{written} group(s), {n / max(elapsed / 1000.0, 1e-9):.0f} rec/s",
        )

    app_dir = tmp_path / "aggregate_app"
    app_dir.mkdir()
    app, _ = await build_app(app_dir, perf_db_copy)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        async with perf_db_copy.session_factory() as session:
            live_box, live_plan = await measure(
                client,
                "GET order aggregate, live GROUP BY (ship_state)",
                f"{API}/order/records/aggregate?group_by=ship_state",
                n,
                perf_db_copy.engine,
                session,
                plan_of="GROUP BY",
            )
            stored_box, _ = await measure(
                client,
                f"GET order aggregate, stored ?reduce={STATE_KEY}",
                f"{API}/order/records/aggregate?reduce={STATE_KEY}",
                n,
                perf_db_copy.engine,
                session,
            )
            # ``measure`` explains the *longest* statement, which for the
            # stored reading is the type load: the aggregate itself is one
            # short indexed SELECT, and that is the one worth a plan.
            with capture(perf_db_copy.engine) as box:
                await get_ok(client, f"{API}/order/records/aggregate?reduce={STATE_KEY}")
            stored_plan = await explain(session, *box.matching("records_index_reduce")[0])
            live = (
                await get_ok(client, f"{API}/order/records/aggregate?group_by=ship_state")
            ).json()
            stored = (
                await get_ok(client, f"{API}/order/records/aggregate?reduce={STATE_KEY}")
            ).json()
    assert stored_box.count <= 4, f"the stored reading cost {stored_box.count} statements"
    assert not plan_scans_records(stored_plan), stored_plan
    assert any("records_index_reduce" in line for line in stored_plan), stored_plan
    # The reading is the finding: same groups, same counts, one folded on read
    # and one folded on write.
    assert {g["value"]: g["count"] for g in live["groups"]} == {
        g["value"]: g["count"] for g in stored["groups"]
    }
    Results.note(
        f"stored aggregate: {stored_box.count} statements, plan {plan_label(stored_plan)} "
        f"— O(groups); live: {live_box.count} statements, plan {plan_label(live_plan)} "
        "— O(rows folded)"
    )


async def test_aggregate_is_one_statement_over_the_index(perf_db, perf_session):
    """The ``GROUP BY`` itself, without the request around it."""
    from sm_records.index.query import Filter, FilterOp
    from sm_records.services import aggregate as aggregate_service
    from sm_records.settings import RecordsSettings

    counts = await type_counts(perf_session)
    rtype = await load_type(perf_session, "order")
    settings = RecordsSettings()
    from sm_records.index.aggregate import parse_metric

    for label, metric, filters in (
        ("count", "count", []),
        ("sum:total", "sum:total", []),
        ("count, 1 filter", "count", [Filter("ship_state", FilterOp.EQ, "CA")]),
    ):

        async def run(metric=metric, filters=filters):
            await aggregate_service.aggregate(
                perf_session,
                rtype,
                settings=settings,
                group_by="ship_state",
                metric=parse_metric(metric),
                filters=filters,
            )

        timing = await repeat(run, reps=REPS, warmup=3)
        with capture(perf_db.engine) as box:
            await run()
        plan = await explain(perf_session, *box.longest())
        Results.add(
            f"aggregate_query(order, ship_state, {label})",
            counts.get("order", 0),
            timing,
            statements=box.count,
            plan=plan_label(plan),
            plan_lines=plan,
        )
        assert box.count == 1, f"{label}: {box.count} statements for one aggregate"
