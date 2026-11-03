"""Shared setup for test_public_api."""

from __future__ import annotations

from tests.support.app_harness import ADMIN, roles

_PREFIX = "/api/records/public"


_PUBLIC_SHAPE = {
    "uuid",
    "slug",
    "locale",
    "translations",
    "display_title",
    "published_at",
    "data",
}


_UNKNOWN_UUID = "0" * 32


def _field(key: str, type_: str, *, indexed: bool = True, **options) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "indexed": indexed,
        "options": options,
    }


async def _make_type(client, key: str, *, is_public: bool, fields=None, **cols) -> dict:
    resp = await client.post(
        "/api/records/types",
        json={
            "key": key,
            "label": key.title(),
            "fields": fields or [_field("title", "text"), _field("body", "text", indexed=False)],
            "display_field": "title",
            "is_public": is_public,
            **cols,
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _make_record(client, key: str, data: dict, *, status: str = "published") -> dict:
    resp = await client.post(
        f"/api/records/types/{key}/records",
        json={"data": data, "status": status},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _article(public_client):
    await _make_type(public_client, "article", is_public=True)
    return await _make_record(public_client, "article", {"title": "Hello", "body": "World"})
