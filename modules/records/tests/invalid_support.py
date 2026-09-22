"""Helpers shared by the two ``invalid_since`` test files.

A module rather than a copy in each: they drive the same fixture — a
``product`` type whose ``sku`` is forced ``required`` over records that do not
have one — from opposite ends. ``test_invalid_flag`` is about what writes the
mark and what clears it; ``test_invalid_rescan`` is about re-deriving it.

Two of these reach past the API on purpose. A record the API can still write
is one the API can still *fix*, and a rescan exists for everything else: a
payload edited in ``psql``, a constraint relaxed by hand, a row nobody has
looked at since. ``client.db_state`` is that second window.
"""

from __future__ import annotations

from sm_records.models import Record
from sqlalchemy import select

from tests.app_harness import ADMIN, roles

# Imported for its import-time ``declare_collection`` calls: a collection has
# to be declared before the app is built (Phase 5 §6.1), and one test here
# creates a type in one.
from tests.collections_harness import COLLECTION_NAMES

assert "events" in COLLECTION_NAMES

TYPES = "/api/records/types"


def field(key: str, type_: str, *, required: bool = False) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": required,
        "unique": False,
        "indexed": True,
        "default": None,
        "help": None,
        "constraints": {},
        "options": {},
    }


async def type_with(client, *records: dict) -> dict:
    """A ``product`` type with ``name``/``sku``, plus one record per payload."""
    created = (
        await client.post(
            TYPES,
            json={
                "key": "product",
                "label": "Product",
                "fields": [field("name", "text"), field("sku", "text")],
                "display_field": "name",
            },
            headers=roles(ADMIN),
        )
    ).json()
    uuids = []
    for data in records:
        resp = await client.post(
            f"{TYPES}/product/records", json={"data": data}, headers=roles(ADMIN)
        )
        assert resp.status_code == 201, resp.text
        uuids.append(resp.json()["uuid"])
    return {"type": created, "uuids": uuids}


async def force_required_sku(client, created: dict) -> dict:
    resp = await client.put(
        f"{TYPES}/product",
        json={
            "expected_version": created["version"],
            "fields": [created["fields"][0], {**created["fields"][1], "required": True}],
            "force": True,
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def read(client, uuid: str) -> dict:
    resp = await client.get(f"{TYPES}/product/records/{uuid}", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def edit_payload(client, uuid: str, data: dict) -> None:
    """Rewrite a record's payload behind the API's back, on its own session."""
    async with client.db_state.session_factory() as session:
        record = (await session.execute(select(Record).where(Record.uuid == uuid))).scalar_one()
        record.data = data
        session.add(record)
        await session.commit()


async def clear_mark(client, uuid: str) -> None:
    """Erase a stored mark without writing the record, so a later scan is the
    only thing that could put one back."""
    async with client.db_state.session_factory() as session:
        record = (await session.execute(select(Record).where(Record.uuid == uuid))).scalar_one()
        record.invalid_since = None
        session.add(record)
        await session.commit()


async def rescan(client, fields: list[dict]) -> dict:
    resp = await client.post(
        f"{TYPES}/product/schema/preview",
        json={"fields": fields, "rescan": True},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["report"]
