"""Which record a row is about — ``mode``, ``match_by`` — and who may say so.

Split from ``test_import.py`` for the 300-line cap. Everything here is about
identity and access; nothing here is about what a write does once the row has
been matched.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_EDITOR_TWO, ROLE_VIEWER, roles
from tests.io_helpers import (
    BRAND,
    PRODUCT,
    catalogue,
    data_by_uuid,
    export_text,
    field,
    make_record,
    make_type,
    parse_rows,
    post_import,
    to_document,
)


async def test_create_mode_refuses_a_row_that_already_exists(client):
    await catalogue(client, products=1)
    document = await export_text(client, PRODUCT)

    resp = await post_import(client, PRODUCT, document, mode="create")
    assert resp.status_code == 200, resp.text
    assert resp.json()["failed"] == 1
    assert "mode=create" in resp.json()["errors"][0]["message"]


async def test_update_mode_refuses_a_row_that_does_not_exist(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    resp = await post_import(
        client, PRODUCT, to_document([{"data": {"name": "Nobody"}}]), mode="update"
    )
    assert resp.json()["failed"] == 1
    assert "mode=update" in resp.json()["errors"][0]["message"]


async def test_match_by_slug(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)], slug_field="name")
    original = await make_record(client, PRODUCT, {"name": "Widget"})
    # No uuid at all: the file knows the record only by its slug.
    rows = [{"slug": original["slug"], "version": 1, "data": {"name": "Widget Two"}}]

    resp = await post_import(client, PRODUCT, to_document(rows), dry_run="false", match_by="slug")
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1
    assert (await data_by_uuid(client, PRODUCT))[original["uuid"]]["data"]["name"] == "Widget Two"


async def test_match_by_a_unique_field(client):
    await make_type(
        client, PRODUCT, [field("sku", "text", unique=True, indexed=True), field("name", "text")]
    )
    original = await make_record(client, PRODUCT, {"sku": "A-1", "name": "Widget"})
    rows = [{"version": 1, "data": {"sku": "A-1", "name": "Renamed"}}]

    resp = await post_import(client, PRODUCT, to_document(rows), dry_run="false", match_by="sku")
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1
    assert (await data_by_uuid(client, PRODUCT))[original["uuid"]]["data"]["name"] == "Renamed"


async def test_match_by_a_non_unique_field_is_refused(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    resp = await post_import(
        client, PRODUCT, to_document([{"data": {"name": "Widget"}}]), match_by="name"
    )
    assert resp.status_code == 422, resp.text
    assert "not unique" in resp.text


async def test_a_uuid_that_belongs_to_another_type_is_refused(client):
    brand, _ = await catalogue(client, products=1)
    rows = [{"uuid": brand["uuid"], "data": {"name": "Confused"}}]

    resp = await post_import(client, PRODUCT, to_document(rows))
    assert resp.json()["failed"] == 1
    assert "different record type" in resp.json()["errors"][0]["message"]


async def test_a_uuid_repeated_in_one_file_is_refused(client):
    await catalogue(client, products=1)
    rows = parse_rows(await export_text(client, PRODUCT))
    rows.append(dict(rows[0]))

    resp = await post_import(client, PRODUCT, to_document(rows))
    assert resp.json()["failed"] == 1
    assert "appears twice" in resp.json()["errors"][0]["message"]


async def test_a_trashed_match_is_refused_rather_than_duplicated(client):
    _, rows_created = await catalogue(client, products=1)
    document = await export_text(client, PRODUCT)
    await client.delete(
        f"/api/records/types/{PRODUCT}/records/{rows_created[0]['uuid']}", headers=roles(ADMIN)
    )

    resp = await post_import(client, PRODUCT, document)
    assert resp.json()["failed"] == 1
    assert "in the trash" in resp.json()["errors"][0]["message"]


async def test_a_relation_target_that_is_missing_is_refused(client):
    await catalogue(client, products=1)
    rows = parse_rows(await export_text(client, PRODUCT))
    rows[0]["data"]["brand"] = {"type": BRAND, "uuid": "0" * 32}

    resp = await post_import(client, PRODUCT, to_document(rows))
    assert resp.json()["failed"] == 1
    assert resp.json()["errors"][0]["field"] == "brand"


async def test_import_costs_edit_not_view(client):
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    body = to_document([{"data": {"name": "Widget"}}])

    anonymous = await client.post(
        f"/api/records/types/{PRODUCT}/records/import",
        content=body.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert anonymous.status_code == 401
    viewer = await post_import(client, PRODUCT, body, actor=ROLE_VIEWER)
    assert viewer.status_code == 403
    editor = await post_import(client, PRODUCT, body, actor=ROLE_EDITOR)
    assert editor.status_code == 200, editor.text


async def test_allowed_roles_narrow_the_import(client):
    await make_type(
        client, PRODUCT, [field("name", "text", indexed=True)], allowed_roles=[ROLE_EDITOR]
    )
    body = to_document([{"data": {"name": "Widget"}}])

    refused = await post_import(client, PRODUCT, body, actor=ROLE_EDITOR_TWO)
    assert refused.status_code == 403
    allowed = await post_import(client, PRODUCT, body, actor=ROLE_EDITOR)
    assert allowed.status_code == 200, allowed.text
