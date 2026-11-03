"""HTTP tests for record access control and the delete lifecycle
(``/api/records/types/{key}/records``).

Split from ``test_api_records.py`` (CRUD, concurrency, filtering) for the
300-line cap. Covers ``allowed_roles`` narrowing, soft delete → restore →
purge, revisions, and the unauthenticated/unpermitted cases.
"""

from __future__ import annotations

from tests.support.api_records_lifecycle_cases import _make_product_type
from tests.support.app_harness import (
    ADMIN,
    ROLE_EDITOR,
    ROLE_EDITOR_TWO,
    ROLE_VIEWER,
    roles,
)


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
