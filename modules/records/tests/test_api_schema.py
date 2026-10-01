"""HTTP tests for the Phase 3 schema-change endpoints: preview, the ``force``/
``orphaned`` retries on ``PUT``, the manual reindex trigger, and type
revisions/rollback.

Split from ``test_api_types.py`` for the 300-line cap. ``test_schema_change.py``
covers the service layer directly (and the two small edits to ``preview``'s
report); everything here is about the HTTP shapes ``utils/api.ts`` was built
against — status codes, body keys, and the out-of-request reindex actually
finishing within the harness's in-process ASGI call.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, api_type, roles, seed_type
from tests.app_harness import field as _field


async def _make_product_type(client, **type_cols) -> dict:
    default = [_field("name", "text", required=True), _field("sku", "text")]
    return await api_type(client, "product", type_cols.pop("fields", default), **type_cols)


async def test_preview_returns_the_classification_and_report_and_writes_nothing(client):
    created = await _make_product_type(client)

    resp = await client.post(
        "/api/records/types/product/schema/preview",
        json={"fields": [*created["fields"], _field("stock", "integer", indexed=False)]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "additive"
    assert [c["field_key"] for c in body["changes"]] == ["stock"]
    assert body["report"] == {
        "checked": 0,
        "failing": 0,
        "sample": [],
        "orphaned_conflicts": {},
        "duplicates": {},
        "clean": True,
    }

    # Writes nothing: the type on disk is exactly what was created.
    after = await client.get("/api/records/types/product", headers=roles(ADMIN))
    assert after.json()["fields"] == created["fields"]
    assert after.json()["version"] == created["version"]


async def test_a_restrictive_put_is_409_then_force_applies_it_and_marks_the_record(client):
    created = await _make_product_type(client)
    record = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget"}},
        headers=roles(ADMIN),
    )
    assert record.status_code == 201
    uuid = record.json()["uuid"]

    required_sku = {**_field("sku", "text"), "required": True}
    refused = await client.put(
        "/api/records/types/product",
        json={
            "expected_version": created["version"],
            "fields": [created["fields"][0], required_sku],
        },
        headers=roles(ADMIN),
    )
    assert refused.status_code == 409
    report = refused.json()["report"]
    assert report["failing"] == 1
    assert report["sample"][0]["uuid"] == uuid
    assert report["sample"][0]["errors"][0]["field"] == "sku"

    forced = await client.put(
        "/api/records/types/product",
        json={
            "expected_version": created["version"],
            "fields": [created["fields"][0], required_sku],
            "force": True,
        },
        headers=roles(ADMIN),
    )
    assert forced.status_code == 200
    assert forced.json()["schema_version"] == created["schema_version"] + 1

    got = await client.get(f"/api/records/types/product/records/{uuid}", headers=roles(ADMIN))
    assert [item["field"] for item in got.json()["invalid"]] == ["sku"]


async def test_readding_an_orphaned_key_is_409_then_restore_reads_the_value_back(client):
    created = await _make_product_type(client)
    record = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget", "sku": "ABC"}},
        headers=roles(ADMIN),
    )
    uuid = record.json()["uuid"]

    dropped = await client.put(
        "/api/records/types/product",
        json={"expected_version": created["version"], "fields": [created["fields"][0]]},
        headers=roles(ADMIN),
    )
    assert dropped.status_code == 200
    dropped_version = dropped.json()["version"]

    # Migrate ``sku`` into ``_orphaned`` by writing the record again under the
    # schema that no longer declares it (§8.3's lazy migration) — otherwise
    # the value is still a top-level key nobody has moved yet.
    rewritten = await client.put(
        f"/api/records/types/product/records/{uuid}",
        json={"expected_version": 1, "data": {"name": "Widget"}},
        headers=roles(ADMIN),
    )
    assert rewritten.status_code == 200

    conflict = await client.put(
        "/api/records/types/product",
        json={
            "expected_version": dropped_version,
            "fields": [created["fields"][0], _field("sku", "text")],
        },
        headers=roles(ADMIN),
    )
    assert conflict.status_code == 409
    assert conflict.json()["conflicts"] == {"sku": 1}

    restored = await client.put(
        "/api/records/types/product",
        json={
            "expected_version": dropped_version,
            "fields": [created["fields"][0], _field("sku", "text")],
            "orphaned": "restore",
        },
        headers=roles(ADMIN),
    )
    assert restored.status_code == 200

    got = await client.get(f"/api/records/types/product/records/{uuid}", headers=roles(ADMIN))
    assert got.json()["data"]["sku"] == "ABC"


async def test_an_index_affecting_put_reindexes_within_the_same_request(client):
    """§8.5/§8.9: the schema write is synchronous, the reindex is a
    ``BackgroundTasks`` entry that Starlette runs after the response but
    still inside one ASGI call — which ``httpx.ASGITransport`` awaits in
    full, so by the time this ``PUT`` returns to the test the rebuild has
    already finished."""
    body = {
        "key": "widget",
        "label": "Widget",
        "fields": [_field("price", "text")],
    }
    created = (await client.post("/api/records/types", json=body, headers=roles(ADMIN))).json()
    await client.post(
        "/api/records/types/widget/records",
        json={"data": {"price": "12"}},
        headers=roles(ADMIN),
    )

    resp = await client.put(
        "/api/records/types/widget",
        json={
            "expected_version": created["version"],
            "fields": [_field("price", "number")],
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200
    assert set(resp.json()["reindex_pending"]) == {"price"}

    after = await client.get("/api/records/types/widget", headers=roles(ADMIN))
    assert after.json()["reindex_pending"] == {}

    filtered = await client.get(
        "/api/records/types/widget/records",
        params=[("filter", "price:gt:1")],
        headers=roles(ADMIN),
    )
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1


async def test_reindex_endpoint_schedules_and_returns_202(client):
    await _make_product_type(client)
    resp = await client.post("/api/records/types/product/reindex", headers=roles(ADMIN))
    assert resp.status_code == 202
    assert resp.json() == {"scheduled": True}


async def test_type_revisions_list_and_restore_round_trip(client):
    created = await _make_product_type(client, fields=[_field("name", "text", required=True)])

    added = await client.put(
        "/api/records/types/product",
        json={
            "expected_version": created["version"],
            "fields": [created["fields"][0], _field("sku", "text")],
        },
        headers=roles(ADMIN),
    )
    assert added.status_code == 200

    listed = await client.get("/api/records/types/product/revisions", headers=roles(ADMIN))
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["version"] for item in items] == [2, 1]
    assert [f["key"] for f in items[1]["fields"]] == ["name"]

    restored = await client.post(
        "/api/records/types/product/revisions/1/restore",
        json={"expected_version": added.json()["version"]},
        headers=roles(ADMIN),
    )
    assert restored.status_code == 200
    body = restored.json()
    assert [f["key"] for f in body["fields"]] == ["name"]
    assert body["schema_version"] == added.json()["schema_version"] + 1

    after = await client.get("/api/records/types/product/revisions", headers=roles(ADMIN))
    assert len(after.json()["items"]) == 3


async def test_preview_reindex_and_type_restore_require_manage_types(client):
    created = await _make_product_type(client)

    preview = await client.post(
        "/api/records/types/product/schema/preview",
        json={"fields": created["fields"]},
        headers=roles(ROLE_EDITOR),
    )
    assert preview.status_code == 403

    reindex = await client.post("/api/records/types/product/reindex", headers=roles(ROLE_EDITOR))
    assert reindex.status_code == 403

    restore = await client.post(
        "/api/records/types/product/revisions/1/restore",
        json={"expected_version": created["version"]},
        headers=roles(ROLE_EDITOR),
    )
    assert restore.status_code == 403


async def test_preview_is_view_only_for_reading_but_writing_needs_manage_types(client, records_app):
    """``GET .../revisions`` only needs ``records.view`` — history is read-only
    — while every mutating schema endpoint above needs ``records.manage_types``."""
    _, db_state = records_app
    await seed_type(db_state, "product", [_field("name", "text")])
    resp = await client.get("/api/records/types/product/revisions", headers=roles(ROLE_EDITOR))
    assert resp.status_code == 200
