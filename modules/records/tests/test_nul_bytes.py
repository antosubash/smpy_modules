"""BLOCKER 2: a NUL byte is refused on the way in, never a 500 on the way out.

Postgres cannot hold ``\\x00`` in ``text``, ``varchar`` or ``jsonb``, and the
refusal comes from the driver while it binds the parameter — so every string
this module lets through to a statement used to be a 500 rather than a 4xx.
Five surfaces reproduced, one of them (``?filter=name:eq:a%00b`` on the
anonymous read API) needing no session at all, and one of them — an import
cell — taking the other 9,999 rows of the file with it under ``on_error=skip``.

Each test here is one of those surfaces. The status codes follow the existing
error table: ``400`` for the query-string grammar, ``422`` for a body, a
per-row ``ImportRowError`` for a file, and a ``404`` for a path segment (no
stored key or uuid can contain one, so "no such thing" is exact).
"""

from __future__ import annotations

import json

from sm_records._text import NUL

from tests.app_harness import ADMIN, api_type, roles

_API = "/api/records/types"
_PUBLIC = "/api/records/public"
_FIELDS = [
    {"key": "name", "type": "text", "label": "Name", "indexed": True},
    {"key": "uniq", "type": "text", "label": "Uniq", "indexed": True, "unique": True},
    {"key": "blob", "type": "json", "label": "Blob", "indexed": False},
    {
        "key": "pick",
        "type": "select",
        "label": "Pick",
        "indexed": True,
        "options": {"choices": [{"value": "a", "label": "A"}]},
    },
]


async def _type(client, key: str, **cols) -> dict:
    return await api_type(client, key, _FIELDS, display_field="name", slug_field="name", **cols)


# --- the payload -----------------------------------------------------------


async def test_a_nul_in_a_text_value_is_a_422_naming_the_field(client):
    await _type(client, "nultext")
    resp = await client.post(
        f"{_API}/nultext/records",
        json={"data": {"name": f"a{NUL}b"}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "name"
    assert "NUL" in resp.json()["errors"][0]["message"]


async def test_a_nul_in_a_unique_value_is_a_422_not_a_500(client):
    await _type(client, "nuluniq")
    resp = await client.post(
        f"{_API}/nuluniq/records",
        json={"data": {"name": "ok", "uniq": f"a{NUL}b"}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "uniq"


async def test_a_nul_nested_in_a_json_value_is_refused(client):
    await _type(client, "nuljson")
    for blob in ({"deep": {"deeper": [f"a{NUL}b"]}}, {f"k{NUL}": 1}):
        resp = await client.post(
            f"{_API}/nuljson/records",
            json={"data": {"name": "ok", "blob": blob}},
            headers=roles(ADMIN),
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["errors"][0]["field"] == "blob"


async def test_a_nul_in_a_select_value_is_refused(client):
    await _type(client, "nulsel")
    resp = await client.post(
        f"{_API}/nulsel/records",
        json={"data": {"name": "ok", "pick": f"a{NUL}"}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "pick"


async def test_a_nul_in_an_explicit_slug_never_reaches_the_column(client):
    await _type(client, "nulslug")
    resp = await client.post(
        f"{_API}/nulslug/records",
        json={"data": {"name": "ok"}, "slug": f"hello{NUL}world"},
        headers=roles(ADMIN),
    )
    # The slugifier strips everything outside ``[a-z0-9]``, so this is a 201
    # with a clean slug rather than a refusal — but it must never be a 500,
    # and the stored value must not carry the byte.
    assert resp.status_code == 201, resp.text
    assert NUL not in resp.json()["slug"]


# --- the grammar, authenticated and anonymous ------------------------------


async def test_a_nul_in_a_filter_is_a_400_on_the_admin_listing(client):
    await _type(client, "nulfilter")
    resp = await client.get(f"{_API}/nulfilter/records?filter=name:eq:a%00b", headers=roles(ADMIN))
    assert resp.status_code == 400, resp.text
    assert "NUL" in resp.json()["detail"]


async def test_a_nul_in_a_filter_is_a_400_on_the_anonymous_public_listing(client):
    await client.app.state.records_module.on_startup(client.app)
    await _type(client, "nulpub", is_public=True)
    resp = await client.get(f"{_PUBLIC}/nulpub?filter=name:eq:a%00b")
    assert resp.status_code == 400, resp.text
    assert "NUL" in resp.json()["detail"]


async def test_a_nul_in_a_public_type_key_is_the_shared_404(client):
    await client.app.state.records_module.on_startup(client.app)
    await _type(client, "nulkeypub", is_public=True)
    resp = await client.get(f"{_PUBLIC}/nulkeypub%00x")
    assert resp.status_code == 404, resp.text
    assert resp.json() == {"detail": "not found"}


# --- path segments on the admin API ---------------------------------------


async def test_a_nul_in_a_type_key_or_uuid_path_segment_is_a_404(client):
    await _type(client, "nulpath")
    unknown_type = await client.get(f"{_API}/nulpath%00x/records", headers=roles(ADMIN))
    assert unknown_type.status_code == 404, unknown_type.text
    unknown_uuid = await client.get(f"{_API}/nulpath/records/%00", headers=roles(ADMIN))
    assert unknown_uuid.status_code == 404, unknown_uuid.text


# --- the type definition ---------------------------------------------------


async def test_a_nul_in_a_type_label_or_field_label_is_a_422(client):
    bad_label = await client.post(
        _API,
        json={"key": "nullabel", "label": f"Bad{NUL}", "fields": []},
        headers=roles(ADMIN),
    )
    assert bad_label.status_code == 422, bad_label.text
    assert bad_label.json()["errors"][0]["field"] == "label"

    bad_field = await client.post(
        _API,
        json={
            "key": "nulfieldlabel",
            "label": "Ok",
            "fields": [{"key": "name", "type": "text", "label": f"N{NUL}", "indexed": True}],
        },
        headers=roles(ADMIN),
    )
    assert bad_field.status_code == 422, bad_field.text
    assert bad_field.json()["errors"][0]["field"] == "name"


async def test_a_nul_in_a_type_update_is_a_422(client):
    created = await _type(client, "nulupdate")
    resp = await client.put(
        f"{_API}/nulupdate",
        json={"label": f"New{NUL}", "expected_version": created["version"]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "label"


# --- the importer ----------------------------------------------------------


async def test_a_nul_cell_is_one_row_error_and_skip_writes_the_rest(client):
    await _type(client, "nulcsv")
    csv = (
        "uuid,slug,locale,translation_group,status,position,name,uniq,blob,pick\r\n"
        ",,,,draft,0,first,,,\r\n"
        f",,,,draft,0,bad{NUL}cell,,,\r\n"
        ",,,,draft,0,third,,,\r\n"
    )
    resp = await client.post(
        f"{_API}/nulcsv/records/import?dry_run=false&format=csv&on_error=skip",
        content=csv.encode(),
        headers={**roles(ADMIN), "Content-Type": "text/csv"},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["created"] == 2
    assert report["failed"] == 1
    assert report["errors"][0]["row"] == 2
    assert report["errors"][0]["field"] == "name"


async def test_a_nul_in_a_json_import_envelope_is_one_row_error(client):
    await _type(client, "nuljsonimp")
    document = {
        "records": [
            {"data": {"name": "fine"}},
            {"data": {"name": "grouped"}, "translation_group": f"g{NUL}"},
        ]
    }
    resp = await client.post(
        f"{_API}/nuljsonimp/records/import?dry_run=false&format=json&on_error=skip",
        content=json.dumps(document),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["created"] == 1
    assert report["failed"] == 1
    assert report["errors"][0]["field"] == "translation_group"


async def test_a_nul_cell_under_abort_is_a_422_with_the_report(client):
    await _type(client, "nulabort")
    document = {"records": [{"data": {"name": f"bad{NUL}"}}]}
    resp = await client.post(
        f"{_API}/nulabort/records/import?dry_run=false&format=json&on_error=abort",
        content=json.dumps(document),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["report"]["failed"] == 1
