"""HTTP tests for record CRUD, concurrency and the filter/sort grammar
(``/api/records/types/{key}/records``).

Split from ``test_api_records_lifecycle.py`` (permissions, soft delete,
revisions) for the 300-line cap — CRUD-and-querying and lifecycle-and-access
are two different concerns that happen to share one router.

Builds its own field definitions rather than using ``conftest``'s
``field_def`` fixture: that fixture bakes ``required=False`` in and routes
any extra keyword into ``options`` — right for the index-layer tests it was
written for, wrong here where a "name is required" field is the point of
more than one test.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles, seed_type
from tests.app_harness import field as _field

_NOW = "2026-09-19T10:00:00+00:00"
"""``reindex_pending`` maps a field key to when its rebuild was enqueued
(design doc §8.5/§8.9); the instant only matters to the health check."""


async def _make_product_type(client, **type_cols):
    body = {
        "key": "product",
        "label": "Product",
        "fields": [_field("name", "text", required=True), _field("price", "number")],
        **type_cols,
    }
    resp = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert resp.status_code == 201
    return resp.json()


async def test_create_get_update_round_trip(client):
    await _make_product_type(client)

    created = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget", "price": 9.99}},
        headers=roles(ADMIN),
    )
    assert created.status_code == 201
    record = created.json()
    assert record["data"] == {"name": "Widget", "price": "9.99"}
    assert record["status"] == "draft"
    assert record["version"] == 1

    got = await client.get(
        f"/api/records/types/product/records/{record['uuid']}", headers=roles(ADMIN)
    )
    assert got.status_code == 200
    # ``created_at`` round-trips through SQLite without its offset suffix —
    # a storage-layer quirk, not a contract this test is about.
    assert {k: v for k, v in got.json().items() if k != "created_at"} == {
        k: v for k, v in record.items() if k != "created_at"
    }

    updated = await client.put(
        f"/api/records/types/product/records/{record['uuid']}",
        json={
            "expected_version": record["version"],
            "data": {"name": "Widget v2", "price": 12.5},
            "status": "published",
        },
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["data"]["name"] == "Widget v2"
    assert body["status"] == "published"
    assert body["published_at"] is not None
    assert body["version"] == record["version"] + 1


async def test_missing_required_field_is_422(client):
    await _make_product_type(client)
    resp = await client.post(
        "/api/records/types/product/records",
        json={"data": {"price": 9.99}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422
    assert resp.json()["errors"]


async def test_update_with_stale_version_is_409_with_current(client):
    await _make_product_type(client)
    created = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget", "price": 1}},
        headers=roles(ADMIN),
    )
    record = created.json()

    winner = await client.put(
        f"/api/records/types/product/records/{record['uuid']}",
        json={"expected_version": record["version"], "data": {"name": "Winner", "price": 2}},
        headers=roles(ADMIN),
    )
    assert winner.status_code == 200

    loser = await client.put(
        f"/api/records/types/product/records/{record['uuid']}",
        json={"expected_version": record["version"], "data": {"name": "Loser", "price": 3}},
        headers=roles(ADMIN),
    )
    assert loser.status_code == 409
    body = loser.json()
    assert body["current"]["data"]["name"] == "Winner"
    assert body["current"]["uuid"] == record["uuid"]


async def test_list_pagination_and_total(client):
    await _make_product_type(client)
    for i in range(3):
        resp = await client.post(
            "/api/records/types/product/records",
            json={"data": {"name": f"Item {i}", "price": i}},
            headers=roles(ADMIN),
        )
        assert resp.status_code == 201

    page = await client.get(
        "/api/records/types/product/records",
        params={"page": 1, "page_size": 2},
        headers=roles(ADMIN),
    )
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 3
    assert body["page_size"] == 2
    assert len(body["items"]) == 2


async def test_filter_gt_and_sort_desc(client):
    await _make_product_type(client)
    for price in (5, 50, 500):
        await client.post(
            "/api/records/types/product/records",
            json={"data": {"name": f"Item {price}", "price": price}},
            headers=roles(ADMIN),
        )

    resp = await client.get(
        "/api/records/types/product/records",
        params=[("filter", "price:gt:10"), ("sort", "-price")],
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [item["data"]["price"] for item in items] == ["500", "50"]


async def test_filter_in(client):
    await _make_product_type(client)
    for price in (1, 2, 3):
        await client.post(
            "/api/records/types/product/records",
            json={"data": {"name": f"Item {price}", "price": price}},
            headers=roles(ADMIN),
        )
    resp = await client.get(
        "/api/records/types/product/records",
        params=[("filter", "price:in:1,3")],
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200
    prices = {item["data"]["price"] for item in resp.json()["items"]}
    assert prices == {"1", "3"}


async def test_filter_is_null(client):
    await _make_product_type(client)
    await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "No price"}},
        headers=roles(ADMIN),
    )
    await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Has price", "price": 1}},
        headers=roles(ADMIN),
    )
    resp = await client.get(
        "/api/records/types/product/records",
        params=[("filter", "price:is_null:true")],
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["data"]["name"] == "No price"


async def test_filter_bad_op_is_400(client):
    await _make_product_type(client)
    resp = await client.get(
        "/api/records/types/product/records",
        params=[("filter", "price:nope:1")],
        headers=roles(ADMIN),
    )
    assert resp.status_code == 400


async def test_filter_on_reindexing_field_is_409(client, records_app):
    _, db_state = records_app
    await seed_type(
        db_state, "product", [_field("price", "number")], reindex_pending={"price": _NOW}
    )
    resp = await client.get(
        "/api/records/types/product/records",
        params=[("filter", "price:gt:1")],
        headers=roles(ADMIN),
    )
    assert resp.status_code == 409
    assert resp.json()["field"] == "price"
    assert resp.json()["reason"] == "reindexing"
