"""HTTP tests for record access control and the delete lifecycle
(``/api/records/types/{key}/records``).

Split from ``test_api_records.py`` (CRUD, concurrency, filtering) for the
300-line cap. Covers ``allowed_roles`` narrowing, soft delete → restore →
purge, revisions, and the unauthenticated/unpermitted cases.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, ROLE_VIEWER, roles


def _field(
    key: str, type_: str, *, required: bool = False, indexed: bool = True, **options
) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": required,
        "unique": False,
        "indexed": indexed,
        "default": None,
        "help": None,
        "constraints": {},
        "options": options,
    }


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


async def test_allowed_roles_narrows_write_access(client):
    await _make_product_type(client, allowed_roles=[ROLE_EDITOR])

    allowed = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget", "price": 1}},
        headers=roles(ROLE_EDITOR),
    )
    assert allowed.status_code == 201

    refused = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget", "price": 1}},
        headers=roles(ROLE_EDITOR_TWO),
    )
    assert refused.status_code == 403


async def test_empty_allowed_roles_lets_any_editor_write(client):
    await _make_product_type(client)  # allowed_roles defaults to []

    for role in (ROLE_EDITOR, ROLE_EDITOR_TWO):
        resp = await client.post(
            "/api/records/types/product/records",
            json={"data": {"name": "Widget", "price": 1}},
            headers=roles(role),
        )
        assert resp.status_code == 201


async def test_viewer_cannot_write(client):
    await _make_product_type(client)
    resp = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget", "price": 1}},
        headers=roles(ROLE_VIEWER),
    )
    assert resp.status_code == 403


async def test_soft_delete_restore_purge_sequence(client):
    await _make_product_type(client)
    created = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget", "price": 1}},
        headers=roles(ADMIN),
    )
    uuid = created.json()["uuid"]

    deleted = await client.delete(
        f"/api/records/types/product/records/{uuid}", headers=roles(ADMIN)
    )
    assert deleted.status_code == 204

    gone = await client.get(f"/api/records/types/product/records/{uuid}", headers=roles(ADMIN))
    assert gone.status_code == 404

    restored = await client.post(
        f"/api/records/types/product/records/{uuid}/restore", headers=roles(ADMIN)
    )
    assert restored.status_code == 200
    assert restored.json()["is_deleted"] is False

    back = await client.get(f"/api/records/types/product/records/{uuid}", headers=roles(ADMIN))
    assert back.status_code == 200

    deleted_again = await client.delete(
        f"/api/records/types/product/records/{uuid}", headers=roles(ADMIN)
    )
    assert deleted_again.status_code == 204

    purged = await client.delete(
        f"/api/records/types/product/records/{uuid}/purge", headers=roles(ADMIN)
    )
    assert purged.status_code == 204

    still_gone = await client.get(
        f"/api/records/types/product/records/{uuid}", headers=roles(ADMIN)
    )
    assert still_gone.status_code == 404


async def test_purge_requires_a_prior_soft_delete(client):
    await _make_product_type(client)
    created = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget", "price": 1}},
        headers=roles(ADMIN),
    )
    uuid = created.json()["uuid"]
    resp = await client.delete(
        f"/api/records/types/product/records/{uuid}/purge", headers=roles(ADMIN)
    )
    # ``get_deleted_record`` finds it (include_deleted doesn't *require*
    # deleted); ``hard_delete_record`` is what refuses a live row.
    assert resp.status_code == 409


async def test_revisions_listing(client):
    await _make_product_type(client)
    created = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "Widget", "price": 1}},
        headers=roles(ADMIN),
    )
    uuid = created.json()["uuid"]
    await client.put(
        f"/api/records/types/product/records/{uuid}",
        json={"expected_version": 1, "data": {"name": "Widget v2", "price": 2}},
        headers=roles(ADMIN),
    )

    resp = await client.get(
        f"/api/records/types/product/records/{uuid}/revisions", headers=roles(ADMIN)
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [item["event"] for item in items] == ["update", "create"]


async def test_unauthenticated_and_unpermitted_requests_are_refused(client):
    await _make_product_type(client)

    anon = await client.get("/api/records/types/product/records")
    assert anon.status_code == 401

    viewer_write = await client.post(
        "/api/records/types/product/records",
        json={"data": {"name": "x", "price": 1}},
        headers=roles(ROLE_VIEWER),
    )
    assert viewer_write.status_code == 403
