"""Regressions for the small, user-visible spec gaps the QA pass named.

Each one was undefined rather than wrong, and each was reachable from the
admin UI or an obvious guess at the API: a body ``key`` silently ignored on a
rename, a pointer aimed at a field type that cannot stringify into a title or
an address, ``required`` satisfied by an empty string, a malformed ``filter=``
answered with a bare 400 on a *page navigation*, the schema editor screen open
to anyone with ``records.view``, and no way at all to enumerate the trash.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_MANAGER, ROLE_VIEWER, roles

_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


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
# S3 — a body ``key`` that disagrees with the path
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
# S6 — what ``display_field`` and ``slug_field`` may point at
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


# --------------------------------------------------------------------------
# S5 — ``required`` is not satisfied by whitespace
# --------------------------------------------------------------------------


async def test_required_text_refuses_empty_and_blank(client):
    await _make(client, "req", [_field("a", "text", required=True)])
    for value in ("", "   ", "\t\n"):
        resp = await client.post(
            "/api/records/types/req/records",
            json={"data": {"a": value}},
            headers=roles(ADMIN),
        )
        assert resp.status_code == 422, repr(value)
        assert resp.json()["errors"][0]["field"] == "a"
    ok = await client.post(
        "/api/records/types/req/records", json={"data": {"a": "x"}}, headers=roles(ADMIN)
    )
    assert ok.status_code == 201


async def test_required_blank_rule_covers_every_string_shaped_type(client):
    choices = {"choices": [{"value": "a", "label": "A"}]}
    cases = {
        "longtext": {},
        "email": {},
        "url": {},
        "select": choices,
    }
    for kind, options in cases.items():
        await _make(
            client,
            f"rq_{kind}",
            [_field("a", kind, required=True, indexed=False, options=options)],
        )
        resp = await client.post(
            f"/api/records/types/rq_{kind}/records",
            json={"data": {"a": "  "}},
            headers=roles(ADMIN),
        )
        assert resp.status_code == 422, kind


async def test_an_optional_text_field_still_accepts_an_empty_string(client):
    """The rule is about ``required``, not about empty strings: an optional
    field may legitimately hold one, and so may an existing stored payload."""
    await _make(client, "opt", [_field("a", "text")])
    resp = await client.post(
        "/api/records/types/opt/records", json={"data": {"a": ""}}, headers=roles(ADMIN)
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["a"] == ""


# --------------------------------------------------------------------------
# S10 — a malformed ``filter=`` on a page navigation
# --------------------------------------------------------------------------


async def test_a_malformed_filter_on_the_list_view_lands_in_errors(client):
    await _make(client, "product", [_field("price", "number")])
    resp = await client.get(
        "/admin/records/product?filter=nonsense", headers={**roles(ADMIN), **_INERTIA}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "Records/RecordList"
    assert body["props"]["errors"] == {"filter": "malformed"}
    assert body["props"]["records"]["total"] == 0


async def test_a_well_formed_but_refused_filter_still_reports_its_own_reason(client):
    await _make(client, "product", [_field("price", "number")])
    resp = await client.get(
        "/admin/records/product?filter=ghost:eq:1", headers={**roles(ADMIN), **_INERTIA}
    )
    assert resp.json()["props"]["errors"] == {"filter": "unknown"}


async def test_the_json_api_still_refuses_a_malformed_filter_with_a_400(client):
    """Unchanged: an API caller wants the status code, and has no ``errors``
    bag to read."""
    await _make(client, "product", [_field("price", "number")])
    resp = await client.get(
        "/api/records/types/product/records?filter=nonsense", headers=roles(ADMIN)
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# S11 — the schema editor screens need ``records.manage_types``
# --------------------------------------------------------------------------


async def test_type_editor_views_require_manage_types(client):
    await _make(client, "product", [_field("price", "number")])
    for url in ("/admin/records/types/new", "/admin/records/types/product"):
        refused = await client.get(url, headers={**roles(ROLE_VIEWER), **_INERTIA})
        assert refused.status_code == 403, url
        allowed = await client.get(url, headers={**roles(ROLE_MANAGER), **_INERTIA})
        assert allowed.status_code == 200, url
        assert allowed.json()["component"] == "Records/TypeEditor"


async def test_the_record_screens_still_need_only_view(client):
    await _make(client, "product", [_field("price", "number")])
    resp = await client.get("/admin/records/product", headers={**roles(ROLE_VIEWER), **_INERTIA})
    assert resp.status_code == 200


# --------------------------------------------------------------------------
# S1 — enumerating the trash
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
