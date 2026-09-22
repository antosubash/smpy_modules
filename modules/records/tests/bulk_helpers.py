"""One type, some records, and the two bulk calls — shared by the bulk suites.

Split out so ``test_api_bulk.py`` (the five actions and the refusal report)
and ``test_api_empty_trash.py`` (the set-based purge) each stay under the
300-line cap with one copy of the setup.
"""

from __future__ import annotations

from typing import Any

from tests.app_harness import ADMIN, roles

TYPES = "/api/records/types"
API = f"{TYPES}/product/records"
BULK = f"{API}/bulk"
EMPTY = f"{API}/trash/empty"


def field(key: str, type_: str, **options: Any) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": options.pop("required", False),
        "unique": options.pop("unique", False),
        "indexed": options.pop("indexed", True),
        "default": None,
        "help": None,
        "constraints": {},
        "options": options,
    }


async def make_product(client, **cols: Any) -> dict:
    """The type every bulk test acts on: a name and an indexed topic, so the
    filter grammar has something to narrow the trash by."""
    resp = await client.post(
        TYPES,
        json={
            "key": "product",
            "label": "Product",
            "fields": [field("name", "text"), field("topic", "text")],
            "display_field": "name",
            **cols,
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def make_records(client, count: int, *, topic: str = "news", actor: str = ADMIN) -> list[str]:
    """``count`` draft records, returned as uuids in creation order."""
    uuids = []
    for index in range(count):
        resp = await client.post(
            API,
            json={"data": {"name": f"Item {index}", "topic": topic}},
            headers=roles(actor),
        )
        assert resp.status_code == 201, resp.text
        uuids.append(resp.json()["uuid"])
    return uuids


async def bulk(client, action: str, uuids: list[str], *, actor: str = ADMIN, **body: Any):
    return await client.post(
        BULK, json={"action": action, "uuids": uuids, **body}, headers=roles(actor)
    )


async def read(client, uuid: str, *, actor: str = ADMIN):
    return await client.get(f"{API}/{uuid}", headers=roles(actor))


async def trash_listing(client, *, actor: str = ADMIN, params: str = ""):
    resp = await client.get(f"{API}?trashed=true{params}", headers=roles(actor))
    assert resp.status_code == 200, resp.text
    return resp.json()
