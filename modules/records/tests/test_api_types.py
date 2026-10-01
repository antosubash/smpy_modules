"""HTTP tests for the Record Type CRUD endpoints (``/api/records/types``)."""

from __future__ import annotations

from tests.app_harness import (
    ADMIN,
    ROLE_EDITOR,
    ROLE_MANAGER,
    ROLE_VIEWER,
    roles,
    seed_record,
    seed_type,
)


async def test_create_list_get_round_trip(client, field_def):
    body = {
        "key": "product",
        "label": "Product",
        "fields": [field_def("price", "number")],
    }
    created = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert created.status_code == 201
    payload = created.json()
    assert payload["key"] == "product"
    assert payload["record_count"] == 0
    assert payload["reindex_pending"] == {}
    assert payload["version"] == 1

    listed = await client.get("/api/records/types", headers=roles(ADMIN))
    assert listed.status_code == 200
    assert [item["key"] for item in listed.json()["items"]] == ["product"]

    got = await client.get("/api/records/types/product", headers=roles(ADMIN))
    assert got.status_code == 200
    # ``created_at`` round-trips through SQLite without its offset suffix —
    # a storage-layer quirk, not a contract this test is about.
    assert {k: v for k, v in got.json().items() if k != "created_at"} == {
        k: v for k, v in payload.items() if k != "created_at"
    }


async def test_create_duplicate_key_is_conflict(client, field_def):
    body = {"key": "product", "label": "Product", "fields": [field_def("price", "number")]}
    first = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert first.status_code == 201
    second = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert second.status_code == 409
    assert "current" not in second.json()


async def test_create_invalid_field_is_422_with_errors(client):
    body = {
        "key": "product",
        "label": "Product",
        "fields": [{"key": "bad key", "type": "text", "label": "x"}],
    }
    resp = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert resp.status_code == 422
    data = resp.json()
    assert data["errors"]
    assert data["errors"][0]["field"] == "bad key"


async def test_update_label_bumps_version_not_schema_version(client, field_def):
    created = await client.post(
        "/api/records/types",
        json={"key": "product", "label": "Product", "fields": [field_def("price", "number")]},
        headers=roles(ADMIN),
    )
    original = created.json()

    updated = await client.put(
        "/api/records/types/product",
        json={"expected_version": original["version"], "label": "Products"},
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["label"] == "Products"
    assert body["version"] == original["version"] + 1
    assert body["schema_version"] == original["schema_version"]


async def test_update_with_stale_version_is_409_with_current(client, field_def):
    created = await client.post(
        "/api/records/types",
        json={"key": "product", "label": "Product", "fields": [field_def("price", "number")]},
        headers=roles(ADMIN),
    )
    original = created.json()

    winner = await client.put(
        "/api/records/types/product",
        json={"expected_version": original["version"], "label": "Products"},
        headers=roles(ADMIN),
    )
    assert winner.status_code == 200

    loser = await client.put(
        "/api/records/types/product",
        json={"expected_version": original["version"], "label": "Should not land"},
        headers=roles(ADMIN),
    )
    assert loser.status_code == 409
    body = loser.json()
    assert body["current"]["label"] == "Products"
    assert body["current"]["key"] == "product"


async def test_an_additive_fields_change_applies_to_a_populated_type(
    client, records_app, field_def
):
    """The Phase 1 lock is gone (design §16 → §8): a populated type's
    ``fields`` are no longer flatly read-only — an additive edit goes
    through, classified rather than refused, exactly as an empty type's
    would."""
    _, db_state = records_app
    rtype = await seed_type(db_state, "product", [field_def("price", "number")])
    await seed_record(db_state, rtype, {"price": "1.00"})

    got = await client.get("/api/records/types/product", headers=roles(ADMIN))
    assert got.json()["record_count"] == 1

    resp = await client.put(
        "/api/records/types/product",
        json={
            "expected_version": got.json()["version"],
            "fields": [field_def("price", "number"), field_def("sku", "text")],
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    assert [f["key"] for f in resp.json()["fields"]] == ["price", "sku"]
    assert resp.json()["schema_version"] == 2


async def test_a_restrictive_fields_change_is_refused_on_a_populated_type(
    client, records_app, field_def
):
    """A newly required field with no default invalidates every record that
    predates it, so the write is refused with a 409 (§8.2) and nothing moves."""
    _, db_state = records_app
    rtype = await seed_type(db_state, "product", [field_def("price", "number")])
    await seed_record(db_state, rtype, {"price": "1.00"})
    version = (await client.get("/api/records/types/product", headers=roles(ADMIN))).json()[
        "version"
    ]

    resp = await client.put(
        "/api/records/types/product",
        json={
            "expected_version": version,
            "fields": [
                field_def("price", "number"),
                {**field_def("sku", "text"), "required": True},
            ],
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 409
    after = await client.get("/api/records/types/product", headers=roles(ADMIN))
    assert after.json()["schema_version"] == 1
    assert after.json()["version"] == version


async def test_delete_requires_matching_confirm_record_count(client, records_app, field_def):
    _, db_state = records_app
    rtype = await seed_type(db_state, "product", [field_def("price", "number")])
    await seed_record(db_state, rtype, {"price": "1.00"})

    wrong = await client.delete(
        "/api/records/types/product", params={"confirm_record_count": 0}, headers=roles(ADMIN)
    )
    assert wrong.status_code == 409

    right = await client.delete(
        "/api/records/types/product", params={"confirm_record_count": 1}, headers=roles(ADMIN)
    )
    assert right.status_code == 204

    missing = await client.get("/api/records/types/product", headers=roles(ADMIN))
    assert missing.status_code == 404


async def test_delete_blocked_by_a_referring_type(client, field_def):
    author = await client.post(
        "/api/records/types",
        json={"key": "author", "label": "Author", "fields": [field_def("name", "text")]},
        headers=roles(ADMIN),
    )
    assert author.status_code == 201
    book = await client.post(
        "/api/records/types",
        json={
            "key": "book",
            "label": "Book",
            "fields": [field_def("writer", "relation", indexed=True, target_type="author")],
        },
        headers=roles(ADMIN),
    )
    assert book.status_code == 201

    resp = await client.delete(
        "/api/records/types/author", params={"confirm_record_count": 0}, headers=roles(ADMIN)
    )
    assert resp.status_code == 409
    assert resp.json()["referrers"] == ["book"]


async def test_unauthenticated_request_is_401(client):
    resp = await client.get("/api/records/types")
    assert resp.status_code == 401


async def test_view_only_role_cannot_manage_types(client, field_def):
    resp = await client.post(
        "/api/records/types",
        json={"key": "product", "label": "Product", "fields": [field_def("price", "number")]},
        headers=roles(ROLE_VIEWER),
    )
    assert resp.status_code == 403

    resp = await client.post(
        "/api/records/types",
        json={"key": "product", "label": "Product", "fields": [field_def("price", "number")]},
        headers=roles(ROLE_EDITOR),
    )
    assert resp.status_code == 403


async def test_manager_role_can_manage_types(client, field_def):
    resp = await client.post(
        "/api/records/types",
        json={"key": "product", "label": "Product", "fields": [field_def("price", "number")]},
        headers=roles(ROLE_MANAGER),
    )
    assert resp.status_code == 201
