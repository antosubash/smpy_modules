"""Enumerating the trash: ``?trashed=true`` on the record list."""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, roles


def _field(key: str, type_: str, **overrides) -> dict:
    base = {"key": key, "type": type_, "label": key.title(), "indexed": True}
    base.update(overrides)
    return base


async def _make(client, key: str, fields: list[dict], **cols):
    return await client.post(
        "/api/records/types",
        json={"key": key, "label": key.title(), "fields": fields, **cols},
        headers=roles(ADMIN),
    )


# --------------------------------------------------------------------------
# enumerating the trash
# --------------------------------------------------------------------------


async def _seeded_trash(client) -> tuple[str, str]:
    """Two records of ``product``; the first is trashed. Returns both uuids."""
    await _make(client, "product", [_field("price", "number")])
    gone = await client.post(
        "/api/records/types/product/records",
        json={"data": {"price": "1"}},
        headers=roles(ADMIN),
    )
    live = await client.post(
        "/api/records/types/product/records",
        json={"data": {"price": "2"}},
        headers=roles(ADMIN),
    )
    uuid = gone.json()["uuid"]
    assert (
        await client.delete(f"/api/records/types/product/records/{uuid}", headers=roles(ADMIN))
    ).status_code == 204
    return uuid, live.json()["uuid"]


async def test_trashed_true_returns_only_the_trash(client):
    trashed, live = await _seeded_trash(client)
    resp = await client.get("/api/records/types/product/records?trashed=true", headers=roles(ADMIN))
    assert resp.status_code == 200
    body = resp.json()
    assert [item["uuid"] for item in body["items"]] == [trashed]
    assert body["total"] == 1
    assert body["items"][0]["is_deleted"] is True
    # And the default list is unchanged — no trash, and a matching total.
    plain = (await client.get("/api/records/types/product/records", headers=roles(ADMIN))).json()
    assert [item["uuid"] for item in plain["items"]] == [live]
    assert plain["total"] == 1


async def test_trashed_applies_filters_and_sorts_as_usual(client):
    trashed, _ = await _seeded_trash(client)
    hit = await client.get(
        "/api/records/types/product/records?trashed=true&filter=price:eq:1&sort=-price",
        headers=roles(ADMIN),
    )
    assert [item["uuid"] for item in hit.json()["items"]] == [trashed]
    miss = await client.get(
        "/api/records/types/product/records?trashed=true&filter=price:eq:2",
        headers=roles(ADMIN),
    )
    assert miss.json() == {
        "items": [],
        "total": 0,
        "total_capped": False,
        "next_cursor": None,
        "page": 1,
        "page_size": 25,
    }


async def test_trashed_costs_edit_not_merely_view(client):
    await _seeded_trash(client)
    refused = await client.get(
        "/api/records/types/product/records?trashed=true", headers=roles(ROLE_VIEWER)
    )
    assert refused.status_code == 403
    allowed = await client.get(
        "/api/records/types/product/records?trashed=true", headers=roles(ROLE_EDITOR)
    )
    assert allowed.status_code == 200
    # A plain list is still a ``records.view`` read.
    plain = await client.get("/api/records/types/product/records", headers=roles(ROLE_VIEWER))
    assert plain.status_code == 200


async def test_an_empty_trash_lists_as_empty(client):
    await _make(client, "product", [_field("price", "number")])
    await client.post(
        "/api/records/types/product/records",
        json={"data": {"price": "1"}},
        headers=roles(ADMIN),
    )
    resp = await client.get("/api/records/types/product/records?trashed=true", headers=roles(ADMIN))
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0
