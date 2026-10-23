"""What a type update's body ``key`` and its ``display_field``/``slug_field`` may say.

A body ``key`` that disagrees with the path is refused rather than silently
ignored as a rename, and a pointer may only name a field type that can
stringify into a title (or, for a slug, into an address).
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles


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
# a body ``key`` that disagrees with the path
# --------------------------------------------------------------------------


async def test_put_with_a_different_key_is_422(client):
    created = await _make(client, "product", [_field("name", "text")])
    resp = await client.put(
        "/api/records/types/product",
        json={"expected_version": created.json()["version"], "key": "renamed"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "key"
    assert (await client.get("/api/records/types/renamed", headers=roles(ADMIN))).status_code == 404


async def test_put_echoing_the_path_key_is_accepted(client):
    """Clients send back the type they just read; the echo is a no-op, not a
    rename attempt."""
    created = await _make(client, "product", [_field("name", "text")])
    resp = await client.put(
        "/api/records/types/product",
        json={"expected_version": created.json()["version"], "key": "product", "label": "P"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "P"


# --------------------------------------------------------------------------
# what ``display_field`` and ``slug_field`` may point at
# --------------------------------------------------------------------------


async def test_display_field_refuses_a_type_it_cannot_stringify(client):
    for kind in ("json", "media", "multiselect", "longtext", "boolean"):
        options = {"choices": [{"value": "a", "label": "A"}]} if kind == "multiselect" else {}
        resp = await _make(
            client,
            f"d_{kind}",
            [_field("v", kind, indexed=False, options=options)],
            display_field="v",
        )
        assert resp.status_code == 422, kind
        assert resp.json()["errors"][0]["field"] == "display_field"


async def test_display_field_accepts_every_stringifiable_type(client):
    for kind in ("text", "email", "url", "integer", "number", "date", "datetime"):
        resp = await _make(client, f"ok_{kind}", [_field("v", kind)], display_field="v")
        assert resp.status_code == 201, kind


async def test_slug_field_is_narrower_than_display_field(client):
    """A slug is an address: a boolean slug field gives every record the slug
    ``true`` and the second write 409s."""
    for kind in ("boolean", "integer", "number", "date", "datetime"):
        resp = await _make(client, f"s_{kind}", [_field("v", kind)], slug_field="v")
        assert resp.status_code == 422, kind
        assert resp.json()["errors"][0]["field"] == "slug_field"
    ok = await _make(client, "s_text", [_field("v", "text")], slug_field="v")
    assert ok.status_code == 201


async def test_a_pointer_at_a_field_that_does_not_exist_is_still_refused(client):
    resp = await _make(client, "p", [_field("v", "text")], display_field="ghost")
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "display_field"
