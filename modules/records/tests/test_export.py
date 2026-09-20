"""Export: what the file says, and what a round trip through it preserves.

The round-trip tests delete the source type between the export and the import
(``io_helpers.drop_type``). That is not tidying up — ``Record.uuid`` is unique
across the whole database, and design §5 makes the round trip depend on it
rather than on autoincrement, so importing a file *beside* the records it came
from is the one thing a real round trip never does. Purging first is the
local stand-in for the second install.
"""

from __future__ import annotations

import csv
import io
import json

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, roles
from tests.io_helpers import (
    BRAND,
    PRODUCT,
    catalogue,
    data_by_uuid,
    drop_type,
    export_text,
    field,
    make_record,
    make_type,
    post_import,
    product_fields,
)


async def test_json_export_shape(client):
    await catalogue(client, products=2)
    document = json.loads(await export_text(client, PRODUCT))

    assert document["type"]["key"] == PRODUCT
    assert document["type"]["schema_version"] == 1
    assert [f["key"] for f in document["type"]["fields"]] == [f["key"] for f in product_fields()]
    assert len(document["records"]) == 2
    row = document["records"][0]
    assert set(row) == {"uuid", "slug", "status", "position", "published_at", "data"}
    # Relations travel exactly as they are stored (§9), not expanded.
    assert set(row["data"]["brand"]) == {"type", "uuid"}
    assert row["data"]["price"] == "0.25"
    assert "_orphaned" not in row["data"]


async def test_json_round_trip_keeps_uuid_data_and_relations(client):
    _, rows = await catalogue(client, products=3)
    before = await data_by_uuid(client, PRODUCT)
    document = await export_text(client, PRODUCT)

    await drop_type(client, PRODUCT, len(rows))
    await make_type(client, PRODUCT, product_fields(), display_field="name", slug_field="name")
    report = await post_import(client, PRODUCT, document, dry_run="false", mode="create")
    assert report.status_code == 200, report.text
    assert report.json()["created"] == 3

    after = await data_by_uuid(client, PRODUCT)
    assert set(after) == set(before)
    for uuid, item in after.items():
        assert item["data"] == before[uuid]["data"]
        assert item["slug"] == before[uuid]["slug"]
        assert item["status"] == before[uuid]["status"]
        assert item["data"]["brand"]["type"] == BRAND


async def test_csv_round_trip_keeps_uuid_data_and_relations(client):
    _, rows = await catalogue(client, products=3)
    before = await data_by_uuid(client, PRODUCT)
    table = await export_text(client, PRODUCT, "csv")

    assert table.endswith("\r\n")
    assert not table.startswith("﻿")
    header = table.split("\r\n")[0].split(",")
    assert header[:5] == ["uuid", "slug", "status", "position", "published_at"]
    assert header[5:] == [f["key"] for f in product_fields()]

    await drop_type(client, PRODUCT, len(rows))
    await make_type(client, PRODUCT, product_fields(), display_field="name", slug_field="name")
    report = await post_import(client, PRODUCT, table, fmt="csv", dry_run="false", mode="create")
    assert report.status_code == 200, report.text
    assert report.json()["created"] == 3

    after = await data_by_uuid(client, PRODUCT)
    for uuid, item in after.items():
        assert item["data"] == before[uuid]["data"], uuid


async def test_csv_escaping_and_no_formula_mitigation(client):
    """Commas, quotes, newlines and unicode survive; a leading ``=`` is left
    alone on purpose.

    No apostrophe is prefixed to a cell starting ``=``/``+``/``-``/``@``. The
    mitigation is not lossless — the importer cannot tell it from a value that
    genuinely begins with one — and this file's whole contract is that it
    round-trips. The README says so where it documents the export.
    """
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    hostile = '=SUM(A1:A2), "quoted", line\nbreak, naïve — ünïcode'
    created = await make_record(client, PRODUCT, {"name": hostile})

    table = await export_text(client, PRODUCT, "csv")
    parsed = list(csv.reader(io.StringIO(table, newline="")))
    assert parsed[1][parsed[0].index("name")] == hostile
    assert '"=SUM(A1:A2)' in table

    await drop_type(client, PRODUCT, 1)
    await make_type(client, PRODUCT, [field("name", "text", indexed=True)])
    resp = await post_import(client, PRODUCT, table, fmt="csv", dry_run="false", mode="create")
    assert resp.status_code == 200, resp.text
    back = await data_by_uuid(client, PRODUCT)
    assert back[created["uuid"]]["data"]["name"] == hostile


async def test_csv_headers_and_filename(client):
    await catalogue(client, products=1)
    resp = await client.get(
        f"/api/records/types/{PRODUCT}/records/export?format=csv", headers=roles(ADMIN)
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith(f'attachment; filename="{PRODUCT}-')
    assert disposition.endswith('.csv"')


async def test_export_honours_filters(client):
    await catalogue(client, products=3)
    document = json.loads(await export_text(client, PRODUCT, query="&filter=name:eq:Widget 1"))
    assert [row["data"]["name"] for row in document["records"]] == ["Widget 1"]


async def test_viewer_may_export_but_needs_edit_for_the_trash(client):
    _, rows = await catalogue(client, products=2)
    assert (
        await client.get(f"/api/records/types/{PRODUCT}/records/export", headers=roles(ROLE_VIEWER))
    ).status_code == 200

    await client.delete(
        f"/api/records/types/{PRODUCT}/records/{rows[0]['uuid']}", headers=roles(ADMIN)
    )
    refused = await client.get(
        f"/api/records/types/{PRODUCT}/records/export?trashed=true", headers=roles(ROLE_VIEWER)
    )
    assert refused.status_code == 403
    allowed = await client.get(
        f"/api/records/types/{PRODUCT}/records/export?trashed=true", headers=roles(ROLE_EDITOR)
    )
    assert allowed.status_code == 200
    assert len(json.loads(allowed.text)["records"]) == 1


async def test_allowed_roles_narrow_the_export(client):
    await make_type(
        client,
        PRODUCT,
        [field("name", "text", indexed=True)],
        allowed_roles=[ROLE_EDITOR],
    )
    await make_record(client, PRODUCT, {"name": "Widget"}, actor=ROLE_EDITOR)
    refused = await client.get(
        f"/api/records/types/{PRODUCT}/records/export", headers=roles(ROLE_VIEWER)
    )
    assert refused.status_code == 403
    allowed = await client.get(
        f"/api/records/types/{PRODUCT}/records/export", headers=roles(ROLE_EDITOR)
    )
    assert allowed.status_code == 200


async def test_anonymous_cannot_export(client):
    await catalogue(client, products=1)
    resp = await client.get(f"/api/records/types/{PRODUCT}/records/export")
    assert resp.status_code == 401
