"""MINOR 2: ``collection`` travels with a type definition.

``TypeExport`` had no ``collection`` field and ``import_type`` passed none, so
a collection-backed type exported from one install landed on the next as a
shared-tables type with no warning anywhere — and an explicit ``collection`` in
an import body was *ignored* rather than refused, while the same value on
``POST /types`` was a clean 422 naming what the host declares.

It is a property of the definition, not of this install's copy of it, which is
the line ``record_count``/``version``/``schema_version`` sit on the other side
of. So it travels, and it takes the two refusals the direct routes already
give: the 422 for a name nobody declared, and the 409 for a *change* — a
collection is assigned at creation and never after.

``tests.collections_harness`` is imported for its module-scope
``declare_collection`` calls, which have to run before any app is built.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, api_type, roles
from tests.collections_harness import EVENTS  # noqa: F401 - declares the collections

_API = "/api/records/types"
_FIELDS = [{"key": "name", "type": "text", "label": "Name", "indexed": True}]


async def _type(client, key: str, **cols) -> dict:
    return await api_type(client, key, _FIELDS, display_field="name", **cols)


async def _export(client, key: str) -> dict:
    resp = await client.get(f"{_API}/{key}/export", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _import(client, body: dict):
    return await client.post(f"{_API}/import", json=body, headers=roles(ADMIN))


async def test_the_export_carries_the_collection(client):
    created = await _type(client, "colexp", collection="events")
    assert created["collection"] == "events"
    exported = await _export(client, "colexp")
    assert exported["collection"] == "events"


async def test_a_shared_tables_type_exports_a_null_collection(client):
    await _type(client, "colnone")
    assert (await _export(client, "colnone"))["collection"] is None


async def test_importing_the_export_lands_in_the_same_collection(client):
    await _type(client, "colsrc", collection="events")
    exported = await _export(client, "colsrc")
    resp = await _import(client, {**exported, "key": "coldst"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["collection"] == "events"


async def test_an_undeclared_collection_is_the_same_422_as_post_types(client):
    direct = await client.post(
        _API,
        json={"key": "coldirect", "label": "D", "fields": [], "collection": "nosuchset"},
        headers=roles(ADMIN),
    )
    assert direct.status_code == 422, direct.text

    imported = await _import(
        client, {"key": "colimp", "label": "I", "label_plural": "Is", "collection": "nosuchset"}
    )
    assert imported.status_code == 422, imported.text
    assert imported.json()["errors"][0]["field"] == "collection"


async def test_update_mode_refuses_a_changed_collection(client):
    created = await _type(client, "colupd", collection="events")
    exported = await _export(client, "colupd")
    resp = await _import(
        client,
        {
            **exported,
            "mode": "update",
            "expected_version": created["version"],
            "collection": "archive",
        },
    )
    assert resp.status_code == 409, resp.text
    still = await client.get(f"{_API}/colupd", headers=roles(ADMIN))
    assert still.json()["collection"] == "events"


async def test_update_mode_accepts_an_echo_of_the_current_collection(client):
    """Re-importing this install's own export must not be a 409."""
    created = await _type(client, "colecho", collection="events")
    exported = await _export(client, "colecho")
    resp = await _import(
        client, {**exported, "mode": "update", "expected_version": created["version"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["collection"] == "events"


async def test_update_mode_leaves_a_collection_the_file_does_not_mention(client):
    created = await _type(client, "colquiet", collection="events")
    resp = await _import(
        client,
        {
            "key": "colquiet",
            "label": "Renamed",
            "label_plural": "Renameds",
            "mode": "update",
            "expected_version": created["version"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["collection"] == "events"
    assert resp.json()["label"] == "Renamed"
