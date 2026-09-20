"""The bounded count, the keyset cursor, the prefix search and the deferred
preview — F4, F9, F10, F11, measured through the real endpoints.

Everything here is a *pair*: the old shape and the new one against the same
seeded file, in one process, so a row of the table in ``docs/performance.md``
is one code path against another and nothing else. The assertions are shapes
as everywhere in this directory — a statement count, a status code, a plan —
never a wall clock.
"""

from __future__ import annotations

import pytest
from sm_records.index.query import Filter, FilterOp, bounded_count_query, count_query
from sm_records.settings import RecordsSettings

from tests.perf._bench import Results, capture, explain, repeat
from tests.perf._http import API, get_ok, measure, plan_label
from tests.perf.conftest import REPS, load_type, type_counts

pytestmark = pytest.mark.perf

_CAP_FRACTION = 3
"""The F4 measurements cap at a *third* of the type rather than at
``max_count``'s default. The bound has to bite for the pair to mean anything,
and the dataset size is a parameter (``RECORDS_PERF_N``) — a fixed 1,000
would be above the whole type at the default size and below it at 20,000, so
the two runs would not be measuring the same thing."""


def _cap_for(n: int) -> int:
    return max(n // _CAP_FRACTION, 1)


async def test_count_bounded_against_unbounded(perf_db, perf_session):
    """The ``total`` half of a list page, with and without the bound (F4)."""
    counts = await type_counts(perf_session)
    rtype = await load_type(perf_session, "order")
    fields = list(rtype.fields or [])
    filters = [Filter("ship_state", FilterOp.EQ, "CA")]
    n = counts.get("order", 0)
    cap = _cap_for(n)
    above = max(n * 2, 1)
    cases = [
        ("count_query(order) unbounded", count_query(rtype, fields)),
        (f"bounded_count_query(order, cap={cap})", bounded_count_query(rtype, fields, cap=cap)),
        # What the bound costs when it never bites — the price every list page
        # below ``max_count`` pays for the one above it.
        (
            f"bounded_count_query(order, cap={above} — above the type)",
            bounded_count_query(rtype, fields, cap=above),
        ),
        ("count_query(order, ship_state=CA) unbounded", count_query(rtype, fields, filters)),
        (
            f"bounded_count_query(order, ship_state=CA, cap={cap})",
            bounded_count_query(rtype, fields, filters, cap=cap),
        ),
    ]
    for label, stmt in cases:

        async def run(stmt=stmt):
            await perf_session.execute(stmt)

        timing = await repeat(run, reps=REPS, warmup=3)
        with capture(perf_db.engine) as box:
            await run()
        plan = await explain(perf_session, *box.last())
        Results.add(
            label,
            counts.get("order", 0),
            timing,
            statements=box.count,
            plan=plan_label(plan),
            plan_lines=plan,
        )


async def test_list_with_and_without_the_total(perf_client, perf_db, perf_session):
    """``?total=false`` drops the count statement entirely (F4)."""
    counts = await type_counts(perf_session)
    with_total, _ = await measure(
        perf_client,
        "GET order list, with total",
        f"{API}/order/records",
        counts.get("order", 0),
        perf_db.engine,
        perf_session,
    )
    without, _ = await measure(
        perf_client,
        "GET order list, total=false",
        f"{API}/order/records?total=false",
        counts.get("order", 0),
        perf_db.engine,
        perf_session,
    )
    assert without.count == with_total.count - 1, "total=false should cost one statement less"


async def test_capped_total_reports_the_ceiling(perf_client, perf_db, perf_session):
    """A type bigger than ``max_count`` answers with the cap and the flag."""
    counts = await type_counts(perf_session)
    cap = _cap_for(counts.get("order", 0))
    perf_client.app.state.sm_records.settings = RecordsSettings(max_count=cap)
    try:
        box, _plan = await measure(
            perf_client,
            f"GET order list, total capped at {cap}",
            f"{API}/order/records",
            counts.get("order", 0),
            perf_db.engine,
            perf_session,
        )
        body = (await get_ok(perf_client, f"{API}/order/records")).json()
        assert (body["total"], body["total_capped"]) == (cap, True)
        assert box.count <= 8
    finally:
        perf_client.app.state.sm_records.settings = RecordsSettings()


async def test_deep_page_by_offset_against_cursor(perf_client, perf_db, perf_session):
    """Page 200 the two ways — ``OFFSET 4975`` and ``?after=`` (F11)."""
    counts = await type_counts(perf_session)
    n = counts.get("order", 0)
    if n < 200 * 25:
        Results.note(f"cursor comparison skipped: only {n} order record(s)")
        return
    # The cursor for the start of page 200, taken from page 199 — one request,
    # not a walk: what is being measured is the page *after* it.
    previous = (await get_ok(perf_client, f"{API}/order/records?page=199&sort=-placed_at")).json()
    cursor = previous["next_cursor"]
    assert cursor, "page 199 should carry a cursor"
    for label, query in [
        ("offset", "page=200&sort=-placed_at"),
        ("cursor", f"after={cursor}&sort=-placed_at&total=false"),
    ]:
        await measure(
            perf_client,
            f"GET order list page 200 by {label}",
            f"{API}/order/records?{query}",
            n,
            perf_db.engine,
            perf_session,
        )
    by_offset = (await get_ok(perf_client, f"{API}/order/records?page=200&sort=-placed_at")).json()
    by_cursor = (
        await get_ok(perf_client, f"{API}/order/records?after={cursor}&sort=-placed_at")
    ).json()
    assert [i["uuid"] for i in by_offset["items"]] == [i["uuid"] for i in by_cursor["items"]]


async def test_deep_page_by_cursor_on_a_non_nullable_column(perf_client, perf_db, perf_session):
    """Page 200 by ``?after=`` on a sort the keyset predicate can seek — S3.

    ``created_at`` is ``NOT NULL``, so its sort drops ``NULLS LAST`` and the
    cursor predicate becomes the row-value comparison ``(created_at, id) <
    (:v, :id)`` instead of an ``OR`` of three. That is the form a planner can
    push into ``(type_id, created_at, id)``: on Postgres the ``OR`` landed in
    the join's ``Filter``, after the join, and on SQLite the plan gains the
    index constraint ``((created_at,id)<(?,?))`` rather than a filter.

    Measured beside ``-placed_at`` above, which is an *indexed* field reached
    by ``LEFT OUTER JOIN`` and therefore nullable — that one keeps the ``OR``
    form by design, and its plan is expected not to move.

    The pages are compared against ``?page=`` as well, because a keyset
    rewrite that is fast and wrong is the failure mode worth guarding.
    """
    counts = await type_counts(perf_session)
    n = counts.get("order", 0)
    if n < 200 * 25:
        Results.note(f"row-value cursor comparison skipped: only {n} order record(s)")
        return
    for sort in ("created_at", "-created_at"):
        previous = (await get_ok(perf_client, f"{API}/order/records?page=199&sort={sort}")).json()
        cursor = previous["next_cursor"]
        assert cursor, f"page 199 sorted by {sort} should carry a cursor"
        box, plan = await measure(
            perf_client,
            f"GET order list page 200 by cursor, sort={sort} (row value)",
            f"{API}/order/records?after={cursor}&sort={sort}&total=false",
            n,
            perf_db.engine,
            perf_session,
        )
        assert box.count == 2, f"a cursor page costs {box.count} statements"
        Results.note(f"row-value cursor, sort={sort}: plan = {plan_label(plan)}")
        by_offset = (await get_ok(perf_client, f"{API}/order/records?page=200&sort={sort}")).json()
        by_cursor = (
            await get_ok(perf_client, f"{API}/order/records?after={cursor}&sort={sort}")
        ).json()
        assert [item["uuid"] for item in by_offset["items"]] == [
            item["uuid"] for item in by_cursor["items"]
        ], f"the row-value cursor disagrees with OFFSET on sort={sort}"


async def test_relation_picker_prefix_against_contains(perf_client, perf_db, perf_session):
    """What the picker sends now, against what it sent before (F9)."""
    counts = await type_counts(perf_session)
    for op in ("contains", "starts_with"):
        box, plan = await measure(
            perf_client,
            f"GET contact list, picker search (display_title {op})",
            f"{API}/contact/records?page_size=10&total=false&filter=display_title:{op}:Smith",
            counts.get("contact", 0),
            perf_db.engine,
            perf_session,
        )
        Results.note(f"picker {op}: plan = {plan_label(plan)}")
        assert box.count <= 8


async def test_the_bound_at_the_cap(perf_db, perf_session):
    """``bounded_count_query`` with the cap *at* the type's own size (F4).

    The three interesting places for the bound are below the type, exactly at
    it and above it, and only the middle one is the state a host actually
    tunes ``max_count`` to: the ceiling is meant to sit where the count stops
    being worth paying for. It is also the boundary the ``total_capped`` flag
    flips on, so a row that is wrong here is a UI that says "9,000+" about
    exactly 9,000 records.
    """
    counts = await type_counts(perf_session)
    rtype = await load_type(perf_session, "order")
    fields = list(rtype.fields or [])
    n = counts.get("order", 0)
    for label, cap in (("at the cap", n), ("one below the cap", max(n - 1, 1))):
        stmt = bounded_count_query(rtype, fields, cap=cap)

        async def run(stmt=stmt):
            await perf_session.execute(stmt)

        timing = await repeat(run, reps=REPS, warmup=3)
        with capture(perf_db.engine) as box:
            await run()
        plan = await explain(perf_session, *box.last())
        Results.add(
            f"bounded_count_query(order, cap={cap} — {label})",
            n,
            timing,
            statements=box.count,
            plan=plan_label(plan),
            plan_lines=plan,
        )
        got = int((await perf_session.execute(stmt)).scalar_one())
        assert got == min(n, cap + 1), f"cap {cap}: counted {got} of {n}"
    Results.note(
        "the bound reads cap+1 rows: at the cap it is the whole type plus the "
        "probe row that tells the caller there is more"
    )
