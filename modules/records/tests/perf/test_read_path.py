"""The read path, through the real HTTP endpoints.

Every measurement here goes through ``perf_client`` — the module's routers
mounted at their production prefixes — so the numbers include FastAPI's
dependency resolution, the contracts layer's per-row read and Pydantic's
serialisation, not only the SQL.

Two shapes are asserted, both properties of the code rather than of the
machine: a filter on an indexed field must not full-scan ``records_record``,
and one page must cost a statement count that does not grow with the number
of rows the type holds. A case whose field the dataset does not declare is
skipped with a note — the suite is an instrument, not a schema test.
"""

from __future__ import annotations

import pytest
from sm_records.index.query import Filter, FilterOp, build_query

from tests.perf._bench import Results, capture, explain, plan_scans_records, plan_uses, repeat
from tests.perf._http import API, HEADERS, measure, plan_label
from tests.perf.conftest import REPS, indexed_fields, load_type, type_counts

pytestmark = pytest.mark.perf


async def test_list_unfiltered_pages(perf_client, perf_db, perf_session):
    """Page 1 against page 200 — the OFFSET cost of deep pagination."""
    counts = await type_counts(perf_session)
    n = counts.get("order", 0)
    for page in (1, 200):
        if page > 1 and n < page * 25:
            Results.note(f"page {page} skipped: only {n} order record(s)")
            continue
        box, _plan = await measure(
            perf_client,
            f"GET order list page {page} (unfiltered)",
            f"{API}/order/records?page={page}",
            n,
            perf_db.engine,
            perf_session,
        )
        assert box.count <= 8, f"page {page} issued {box.count} statements"


async def test_list_filtered_by_kind(perf_client, perf_db, perf_session):
    """One filter of every index kind, each through the endpoint."""
    counts = await type_counts(perf_session)
    cases = [
        ("text eq", "company", "city", "filter=city:eq:Palo Alto"),
        ("text contains", "company", "name", "filter=name:contains:Holdings"),
        ("select eq", "order", "ship_state", "filter=ship_state:eq:CA"),
        ("number range gte", "product", "price", "filter=price:gte:100"),
        ("bool eq", "product", "in_stock", "filter=in_stock:eq:true"),
        ("date range gte", "company", "founded", "filter=founded:gte:1990-01-01"),
        ("datetime range gte", "order", "placed_at", "filter=placed_at:gte:2024-01-01T00:00:00Z"),
        ("multiselect eq", "product", "tags", "filter=tags:eq:sale"),
    ]
    declared = {
        key: await indexed_fields(perf_session, key) for key in ("company", "order", "product")
    }
    for label, key, field, query in cases:
        if field not in declared.get(key, {}):
            Results.note(f"skipped {label}: {key} declares no indexed {field!r}")
            continue
        box, _plan = await measure(
            perf_client,
            f"GET {key} list, {label} ({field})",
            f"{API}/{key}/records?{query}",
            counts.get(key, 0),
            perf_db.engine,
            perf_session,
        )
        assert box.count <= 8, f"{label}: {box.count} statements"
    # The fixed columns of design §7.2 are filterable with no index table at
    # all — measured beside the index kinds because a caller cannot tell the
    # two apart from the query string.
    await measure(
        perf_client,
        "GET order list, fixed-column eq (status)",
        f"{API}/order/records?filter=status:eq:published",
        counts.get("order", 0),
        perf_db.engine,
        perf_session,
    )


async def test_text_contains_over_long_value(perf_client, perf_db, perf_session):
    """``contains`` on a text field whose stored values can exceed 512
    characters — the ``value_full`` half of the §7.4 split, which no index
    covers by construction."""
    counts = await type_counts(perf_session)
    declared = await indexed_fields(perf_session, "company")
    if "name" not in declared:
        pytest.skip("company declares no indexed name")
    box, _plan = await measure(
        perf_client,
        "GET company list, contains over value+value_full",
        f"{API}/company/records?filter=name:contains:zzzz-no-such-substring",
        counts.get("company", 0),
        perf_db.engine,
        perf_session,
    )
    Results.note("contains scans records_index_text by design (LIKE '%x%' is not indexable)")
    assert box.count <= 8


async def test_relation_picker_search(perf_client, perf_db, perf_session):
    """What the relation picker actually asks for.

    ``components/RelationPicker.tsx`` searches its target type with
    ``filter=display_title:contains:<term>``. ``display_title`` is a fixed
    column (design §7.2), so this is ``ILIKE '%term%'`` against
    ``records_record`` — no index covers it, by construction. Measured
    because it is the one filter in the product a user types into.
    """
    counts = await type_counts(perf_session)
    box, plan = await measure(
        perf_client,
        "GET contact list, relation-picker search (display_title contains)",
        f"{API}/contact/records?page_size=20&filter=display_title:contains:smith",
        counts.get("contact", 0),
        perf_db.engine,
        perf_session,
    )
    Results.note(
        "relation-picker search is display_title ILIKE '%term%' on records_record: "
        f"plan = {plan_label(plan)}"
    )
    assert box.count <= 8


async def test_filter_ref_eq(perf_client, perf_db, perf_session):
    """``order.customer`` — a ``relation`` filter over ``records_index_ref``."""
    counts = await type_counts(perf_session)
    contact_type = await load_type(perf_session, "contact")
    contact = (await perf_session.execute(build_query(contact_type, []).limit(1))).scalars().first()
    assert contact is not None
    _box, plan = await measure(
        perf_client,
        "GET order list, ref eq (customer)",
        f"{API}/order/records?filter=customer:eq:{contact.uuid}",
        counts.get("order", 0),
        perf_db.engine,
        perf_session,
    )
    assert not plan_scans_records(plan), plan


async def test_filter_in_50_values(perf_client, perf_db, perf_session):
    """``in`` with up to 50 values — the grammar expands it to ORed equality
    clauses inside one EXISTS, so the statement count must stay flat."""
    counts = await type_counts(perf_session)
    contact_type = await load_type(perf_session, "contact")
    rows = (await perf_session.execute(build_query(contact_type, []).limit(50))).scalars().all()
    emails = ",".join(row.display_title for row in rows if row.display_title)
    if not emails:
        pytest.skip("no contact display titles to build an `in` filter from")
    box, _plan = await measure(
        perf_client,
        f"GET contact list, in with {len(rows)} values",
        f"{API}/contact/records?filter=email:in:{emails}",
        counts.get("contact", 0),
        perf_db.engine,
        perf_session,
    )
    assert box.count <= 8


async def test_combined_three_filters(perf_client, perf_db, perf_session):
    counts = await type_counts(perf_session)
    query = "filter=total:gte:50&filter=ship_state:eq:CA&filter=placed_at:gte:2020-01-01T00:00:00Z"
    _box, plan = await measure(
        perf_client,
        "GET order list, 3-filter AND",
        f"{API}/order/records?{query}",
        counts.get("order", 0),
        perf_db.engine,
        perf_session,
    )
    assert not plan_scans_records(plan), plan


async def test_sorted_by_each_kind(perf_client, perf_db, perf_session):
    """Every sortable kind, both directions. A sort on an index field adds an
    aggregate subquery and an outer join; the plan line to watch for is the
    temp B-tree it forces.

    The **descending** fixed-column rows are the ones S2 is about: a nullable
    column's sort wears ``NULLS LAST``, which is neither direction of the
    ascending ``(type_id, col, id)`` index, so on Postgres it was answered by
    sorting the whole type.
    """
    counts = await type_counts(perf_session)
    cases = [
        ("text", "company", "name"),
        ("number", "product", "price"),
        ("bool", "product", "in_stock"),
        ("date", "company", "founded"),
        ("datetime", "order", "placed_at"),
        ("ref", "order", "customer"),
        ("multiselect", "product", "tags"),
        ("fixed column", "order", "updated_at"),
        ("fixed column", "order", "position"),
        ("fixed column", "order", "published_at"),
    ]
    plans: dict[str, list[str]] = {}
    for kind, key, field in cases:
        for direction in ("", "-"):
            _box, plan = await measure(
                perf_client,
                f"GET {key} list, sort {direction}{field} ({kind})",
                f"{API}/{key}/records?sort={direction}{field}",
                counts.get(key, 0),
                perf_db.engine,
                perf_session,
            )
            if kind == "fixed column":
                plans[f"{direction}{field}"] = plan
    for field in ("published_at", "updated_at"):
        Results.note(f"sort -{field} (nullable, S2): {plan_label(plans['-' + field])}")


async def test_count_query_alone(perf_db, perf_session):
    """The ``total`` half of a list page, measured without the page read."""
    from sm_records.index.query import count_query

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
