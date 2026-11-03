"""Count, detail and Inertia read-path measurements."""

from __future__ import annotations

import pytest
from sm_records.records.index.query import Filter, FilterOp, build_query

from tests.perf._bench import Results, capture, explain, plan_uses, repeat
from tests.perf._http import API, HEADERS, measure, plan_label
from tests.perf.conftest import REPS, load_type, type_counts

pytestmark = pytest.mark.perf

async def test_count_query_alone(perf_db, perf_session):
    """The ``total`` half of a list page, measured without the page read."""
    from sm_records.records.index.query import count_query

    counts = await type_counts(perf_session)
    rtype = await load_type(perf_session, "order")
    stmt = count_query(rtype, list(rtype.fields or []), [Filter("ship_state", FilterOp.EQ, "CA")])

    async def run():
        await perf_session.execute(stmt)

    timing = await repeat(run, reps=REPS, warmup=3)
    with capture(perf_db.engine) as box:
        await run()
    plan = await explain(perf_session, *box.last())
    Results.add(
        "count_query(order, ship_state=CA)",
        counts.get("order", 0),
        timing,
        statements=box.count,
        plan=plan_label(plan),
        plan_lines=plan,
    )


async def test_get_single_record_by_uuid(perf_client, perf_db, perf_session):
    counts = await type_counts(perf_session)
    order_type = await load_type(perf_session, "order")
    record = (await perf_session.execute(build_query(order_type, []).limit(1))).scalars().first()
    _box, plan = await measure(
        perf_client,
        "GET one order by uuid",
        f"{API}/order/records/{record.uuid}",
        counts.get("order", 0),
        perf_db.engine,
        perf_session,
    )
    assert plan_uses(plan, "records_record"), plan


async def test_inertia_list_view(perf_client, perf_db, perf_session):
    """``GET /admin/records/{key}`` with ``X-Inertia``.

    The view does more than the API list: two ``record_count`` queries for the
    type header on top of the page and its total, and — since Phase 4 — the
    expansion every relation column it renders always asks for (§9): one
    lookup for the target types plus **one per relation field**, which for
    ``order`` (a contact and a to-many product list) is three.

    The budget is a ceiling on a sum that scales with the *schema*, never with
    the page: the Phase 3 review found a per-row validation here
    (``record_list_read`` is the fix) and a per-row expansion would be the
    same mistake with a different name. Ten statements is 200 records read in
    a fixed number of round trips; the assertion fails the moment either of
    those turns into "once per row".
    """
    counts = await type_counts(perf_session)
    headers = {**HEADERS, "X-Inertia": "true", "X-Inertia-Version": "1.0"}

    async def call():
        response = await perf_client.get("/admin/records/order", headers=headers)
        assert response.status_code == 200, response.text[:300]

    timing = await repeat(call, reps=REPS, warmup=3)
    with capture(perf_db.engine) as box:
        await call()
    plan = await explain(perf_session, *box.longest())
    Results.add(
        "GET /admin/records/order (Inertia)",
        counts.get("order", 0),
        timing,
        statements=box.count,
        plan=plan_label(plan),
        plan_lines=plan,
    )
    assert box.count <= 10, f"Inertia list view issued {box.count} statements"
