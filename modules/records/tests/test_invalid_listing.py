"""``invalid`` in the filter grammar — the worklist, as a URL.

The mark is a column so a *list* can be narrowed to it. That makes ``invalid``
a fixed column like ``status`` or ``locale``, with one difference worth its
own file: the grammar name is not the column name. The row stores
``invalid_since``, a nullable timestamp, and the filter is the boolean view of
it (``index/_fixed.py``) — so the operators it accepts, the ones it refuses,
and what a sort on it orders by are all decisions rather than consequences.

The public grammar is the other half. ``PUBLIC_FIXED_COLUMNS`` is derived by
intersection, so ``invalid`` is excluded by construction; that is worth a test
because "derived, therefore safe" is exactly the claim that stops being true
quietly.
"""

from __future__ import annotations

from sm_records.index._fixed import (
    FIXED_COLUMNS,
    NOT_NULL_FIXED_COLUMNS,
    PUBLIC_FIXED_COLUMNS,
)

from tests.app_harness import ADMIN, roles
from tests.invalid_support import TYPES, force_required_sku, type_with

LIST = f"{TYPES}/product/records"


def test_invalid_is_a_fixed_column_and_is_not_a_public_one():
    assert "invalid" in FIXED_COLUMNS
    assert "invalid" not in PUBLIC_FIXED_COLUMNS
    # The column behind it is nullable, so a sort on it wears NULLS LAST —
    # which is what puts the unmarked records last rather than first.
    assert "invalid" not in NOT_NULL_FIXED_COLUMNS


async def _two(client) -> dict:
    """One marked record and one clean one, of the same type."""
    state = await type_with(client, {"name": "Widget"}, {"name": "Gadget", "sku": "G-1"})
    await force_required_sku(client, state["type"])
    return {"marked": state["uuids"][0], "clean": state["uuids"][1]}


async def _uuids(client, query: str) -> list[str]:
    resp = await client.get(f"{LIST}?{query}", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return [item["uuid"] for item in resp.json()["items"]]


async def test_eq_true_lists_the_marked_records(client):
    """The link behind "Check records" and behind the hub's count."""
    state = await _two(client)
    assert await _uuids(client, "filter=invalid:eq:true") == [state["marked"]]


async def test_eq_false_and_ne_true_and_is_null_are_the_same_question(client):
    """An unmarked record is one with no ``invalid_since``, so all three
    spellings select it. Offering only one would make the other two silently
    wrong for a caller arriving from another fixed column."""
    state = await _two(client)
    for query in (
        "filter=invalid:eq:false",
        "filter=invalid:ne:true",
        "filter=invalid:is_null:true",
    ):
        assert await _uuids(client, query) == [state["clean"]], query


async def test_is_null_false_is_the_marked_ones(client):
    state = await _two(client)
    assert await _uuids(client, "filter=invalid:is_null:false") == [state["marked"]]


async def test_a_sort_puts_the_marked_records_first(client):
    """Ascending by the timestamp under ``NULLS LAST``: marked first, oldest
    mark first, unmarked after them."""
    state = await _two(client)
    assert await _uuids(client, "sort=invalid") == [state["marked"], state["clean"]]
    assert await _uuids(client, "sort=-invalid") == [state["marked"], state["clean"]]


async def test_an_ordered_operator_is_refused(client):
    """``invalid:lt:...`` would compare against the timestamp under a name
    that does not mention one. "Invalid since before Tuesday" is a reasonable
    question; this is not the spelling that should be trusted to be asking
    it."""
    await _two(client)
    resp = await client.get(f"{LIST}?filter=invalid:gt:2020-01-01", headers=roles(ADMIN))
    assert resp.status_code == 400, resp.text
    assert "invalid" in resp.json()["detail"]


async def test_a_value_that_is_not_a_boolean_is_refused(client):
    await _two(client)
    resp = await client.get(f"{LIST}?filter=invalid:eq:perhaps", headers=roles(ADMIN))
    assert resp.status_code == 400, resp.text


async def test_a_cursor_resumes_an_invalid_sort(client):
    """The cursor carries the sort term's value, which for this column is the
    timestamp — and ``_cursor._FIXED_DECODE`` has to know that, or every
    ``?after=`` over this sort is a 400."""
    state = await _two(client)
    first = await client.get(f"{LIST}?sort=invalid&page_size=1", headers=roles(ADMIN))
    assert first.status_code == 200, first.text
    body = first.json()
    assert [item["uuid"] for item in body["items"]] == [state["marked"]]
    resumed = await client.get(
        f"{LIST}?sort=invalid&page_size=1&after={body['next_cursor']}", headers=roles(ADMIN)
    )
    assert resumed.status_code == 200, resumed.text
    assert [item["uuid"] for item in resumed.json()["items"]] == [state["clean"]]


async def test_the_public_api_does_not_answer_about_it(client):
    """Public reads are published records, and whether one of them is behind
    its schema is the admin's problem — not a fact an anonymous caller can
    binary-search a type's health out of."""
    state = await _two(client)
    published = await client.put(
        f"{TYPES}/product/records/{state['clean']}",
        json={
            "expected_version": 1,
            "data": {"name": "Gadget", "sku": "G-1"},
            "status": "published",
        },
        headers=roles(ADMIN),
    )
    assert published.status_code == 200, published.text
    public = await client.put(
        f"{TYPES}/product",
        json={"expected_version": 2, "is_public": True},
        headers=roles(ADMIN),
    )
    assert public.status_code == 200, public.text
    # The public router is mounted from the module's own ``on_startup``
    # (``boot.py``), which the harness does not run for every test.
    await client.app.state.records_module.on_startup(client.app)

    listed = await client.get("/api/records/public/product")
    assert listed.status_code == 200, listed.text
    assert "invalid_since" not in listed.json()["items"][0]

    refused = await client.get("/api/records/public/product?filter=invalid:eq:true")
    assert refused.status_code == 400, refused.text
    sorted_ = await client.get("/api/records/public/product?sort=invalid")
    assert sorted_.status_code == 400, sorted_.text


async def test_an_aggregate_groups_by_the_boolean_not_the_instant(client):
    """Two groups, whatever the timestamps: the group expression is the
    boolean the grammar names (``_fixed.fixed_expression``)."""
    await _two(client)
    resp = await client.get(
        f"{TYPES}/product/records/aggregate?group_by=invalid", headers=roles(ADMIN)
    )
    assert resp.status_code == 200, resp.text
    groups = {str(row["value"]).lower(): row["count"] for row in resp.json()["groups"]}
    assert groups == {"true": 1, "false": 1}
