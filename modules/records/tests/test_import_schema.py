"""Exporting and importing a *type definition*, and the §8 pipeline under it.

The point of the update path is that it has no pipeline of its own. A schema
import onto a populated type is ``services.types.update_type`` — the same call
the schema editor makes — so it classifies, dry-runs and refuses the same way,
and answers a refusal with the same ``force``. A second code path here would
be a way to make a destructive schema change that §8 never saw.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_MANAGER, ROLE_VIEWER, roles
from tests.io_helpers import PRODUCT, catalogue, field, make_record, make_type, product_fields


async def _export_type(client, key: str = PRODUCT, actor: str = ADMIN):
    return await client.get(f"/api/records/types/{key}/export", headers=roles(actor))


async def test_type_export_is_importable_shaped(client):
    await catalogue(client, products=1)
    resp = await _export_type(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert set(body) == {
        "key",
        "label",
        "label_plural",
        "description",
        "icon",
        "fields",
        "display_field",
        "slug_field",
        "is_public",
        # Carried so a type that had its own sidebar entry where it was
        # exported still has one where it is imported.
        "show_in_menu",
        # Carried so a definition exported from a multilingual install arrives
        # at the next one still able to hold translations (Phase 5 §4.1).
        "translatable",
        "allowed_roles",
    }
    # Facts about *this* install's copy, deliberately absent — see
    # ``contracts/io.py``.
    for absent in ("record_count", "version", "schema_version", "reindex_pending"):
        assert absent not in body
    assert [f["key"] for f in body["fields"]] == [f["key"] for f in product_fields()]


async def test_a_type_export_creates_the_same_type_under_a_new_key(client):
    await catalogue(client, products=1)
    definition = (await _export_type(client)).json()

    resp = await client.post(
        "/api/records/types/import",
        json={**definition, "key": "product_copy"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["key"] == "product_copy"
    assert created["fields"] == definition["fields"]
    assert created["record_count"] == 0
    assert created["slug_field"] == "name"


async def test_update_mode_needs_an_expected_version(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    definition = (await _export_type(client)).json()

    resp = await client.post(
        "/api/records/types/import", json={**definition, "mode": "update"}, headers=roles(ADMIN)
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "expected_version"


async def test_a_restrictive_import_on_a_populated_type_is_refused_then_forced(client):
    created = await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    record = await make_record(client, PRODUCT, {"name": "Widget"})
    definition = (await _export_type(client)).json()
    definition["fields"] = [
        *definition["fields"],
        {**field("sku", "text"), "required": True},
    ]

    refused = await client.post(
        "/api/records/types/import",
        json={**definition, "mode": "update", "expected_version": created["version"]},
        headers=roles(ADMIN),
    )
    assert refused.status_code == 409, refused.text
    report = refused.json()["report"]
    assert report["failing"] == 1
    assert report["sample"][0]["uuid"] == record["uuid"]
    assert report["sample"][0]["errors"][0]["field"] == "sku"

    forced = await client.post(
        "/api/records/types/import",
        json={
            **definition,
            "mode": "update",
            "expected_version": created["version"],
            "force": True,
        },
        headers=roles(ADMIN),
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["schema_version"] == created["schema_version"] + 1

    got = await client.get(
        f"/api/records/types/{PRODUCT}/records/{record['uuid']}", headers=roles(ADMIN)
    )
    assert [item["field"] for item in got.json()["invalid"]] == ["sku"]


async def test_a_stale_expected_version_is_a_409(client):
    created = await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    definition = (await _export_type(client)).json()

    resp = await client.post(
        "/api/records/types/import",
        json={**definition, "mode": "update", "expected_version": created["version"] + 5},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 409, resp.text


async def test_type_import_costs_manage_types(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    definition = (await _export_type(client)).json()
    body = {**definition, "key": "product_copy"}

    assert (await client.post("/api/records/types/import", json=body)).status_code == 401
    assert (
        await client.post("/api/records/types/import", json=body, headers=roles(ROLE_VIEWER))
    ).status_code == 403
    assert (
        await client.post("/api/records/types/import", json=body, headers=roles(ROLE_MANAGER))
    ).status_code == 200


async def test_reading_a_type_definition_costs_view(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    assert (await _export_type(client, actor=ROLE_VIEWER)).status_code == 200
    assert (await client.get(f"/api/records/types/{PRODUCT}/export")).status_code == 401
