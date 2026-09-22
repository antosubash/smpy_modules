"""BLOCKER 1: a ``json`` value deep enough to break the serializer is refused.

The failure this proves gone was *persistent*, which is what made it a
blocker rather than a bad request: a 300-deep value accepted through
``POST …/records/import`` was written and committed, and from then on every
read of that type — the admin list, the record editor and the anonymous
public listing — was a 500, because pydantic's serializer gives up at roughly
250 levels and nothing in the read path could get past it. The row could not
be purged through the API either: purging needs a uuid, and the listing that
would show it was the thing that failed.

So each test here asserts two things, not one: the write is refused with the
module's own 422, **and** a listing taken afterwards is still 200.
"""

from __future__ import annotations

import json

from sm_records.schema._scalars import MAX_JSON_DEPTH, MAX_JSON_NODES

from tests.app_harness import ADMIN, roles

_API = "/api/records/types"
_FIELDS = [
    {"key": "name", "type": "text", "label": "Name", "indexed": True},
    {"key": "blob", "type": "json", "label": "Blob", "indexed": False},
]


def _nested(depth: int) -> list:
    """``[[[…]]]`` — ``depth`` containers, built iteratively so the *test* is
    not the thing that hits a recursion limit."""
    value: list = []
    for _ in range(depth - 1):
        value = [value]
    return value


async def _type(client, key: str) -> dict:
    resp = await client.post(
        _API,
        json={"key": key, "label": key.title(), "fields": _FIELDS, "display_field": "name"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _listings_are_healthy(client, key: str) -> None:
    resp = await client.get(f"{_API}/{key}/records", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text


async def test_a_deep_json_value_is_refused_on_create(client):
    await _type(client, "deep")
    resp = await client.post(
        f"{_API}/deep/records",
        json={"data": {"name": "a", "blob": _nested(300)}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["errors"][0]["field"] == "blob"
    assert "nested more than" in body["errors"][0]["message"]
    await _listings_are_healthy(client, "deep")


async def test_a_deep_json_value_is_refused_on_update(client):
    await _type(client, "deepup")
    created = await client.post(
        f"{_API}/deepup/records",
        json={"data": {"name": "a", "blob": {"ok": 1}}},
        headers=roles(ADMIN),
    )
    assert created.status_code == 201, created.text
    uuid = created.json()["uuid"]
    resp = await client.put(
        f"{_API}/deepup/records/{uuid}",
        json={"data": {"name": "a", "blob": _nested(300)}, "expected_version": 1},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "blob"
    await _listings_are_healthy(client, "deepup")


async def test_a_deep_json_value_is_one_row_error_on_import(client):
    await _type(client, "deepimp")
    document = {
        "records": [
            {"data": {"name": "fine", "blob": {"ok": 1}}},
            {"data": {"name": "deep", "blob": _nested(300)}},
        ]
    }
    resp = await client.post(
        f"{_API}/deepimp/records/import?dry_run=false&format=json&on_error=skip",
        content=json.dumps(document),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["created"] == 1
    assert report["failed"] == 1
    assert report["errors"][0]["row"] == 2
    assert report["errors"][0]["field"] == "blob"
    await _listings_are_healthy(client, "deepimp")


async def test_on_error_abort_refuses_the_whole_file(client):
    await _type(client, "deepabort")
    document = {"records": [{"data": {"name": "deep", "blob": _nested(300)}}]}
    resp = await client.post(
        f"{_API}/deepabort/records/import?dry_run=false&format=json&on_error=abort",
        content=json.dumps(document),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["report"]["failed"] == 1
    await _listings_are_healthy(client, "deepabort")


async def test_the_boundary_is_exact(client):
    await _type(client, "deepedge")
    accepted = await client.post(
        f"{_API}/deepedge/records",
        json={"data": {"name": "at-the-limit", "blob": _nested(MAX_JSON_DEPTH)}},
        headers=roles(ADMIN),
    )
    assert accepted.status_code == 201, accepted.text
    refused = await client.post(
        f"{_API}/deepedge/records",
        json={"data": {"name": "one-over", "blob": _nested(MAX_JSON_DEPTH + 1)}},
        headers=roles(ADMIN),
    )
    assert refused.status_code == 422, refused.text


async def test_a_wide_json_value_is_refused_by_the_node_count(client):
    await _type(client, "wide")
    resp = await client.post(
        f"{_API}/wide/records",
        json={"data": {"name": "wide", "blob": list(range(MAX_JSON_NODES + 5))}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert "more than" in resp.json()["errors"][0]["message"]
    await _listings_are_healthy(client, "wide")
