"""HTTP tests for the Inertia view endpoints (``/admin/records``).

Asserted as Inertia JSON (``X-Inertia: true``) rather than parsed HTML — the
protocol's whole point is that a page navigation and a client-side refetch
return the same ``{"component": ..., "props": ...}`` shape, and that shape is
what a page component actually keys on.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_VIEWER, roles, seed_record, seed_type

_INERTIA_HEADERS = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}

_TENANCY_PROPS = ("tenant", "tenancy_mode")
"""On every records screen: which tenant it reads and whether the host has
several (tenancy design §J). ``test_tenancy_binding.py`` checks the values."""

_NOW = "2026-09-19T10:00:00+00:00"
"""``reindex_pending`` maps a field key to when its rebuild was enqueued
(design doc §8.5/§8.9); the instant only matters to the health check."""


def _field(key: str, type_: str, **overrides) -> dict:
    base = {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": False,
        "unique": False,
        "indexed": True,
        "default": None,
        "help": None,
        "constraints": {},
        "options": {},
    }
    base.update(overrides)
    return base


async def test_type_list_view(client, records_app):
    _, db_state = records_app
    await seed_type(db_state, "product", [_field("price", "number")])

    resp = await client.get("/admin/records/", headers={**roles(ADMIN), **_INERTIA_HEADERS})
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "Records/Types"
    # Missing-item ("per-type public URL surface"): the hub is where most
    # visits to a type start (UX-R13.1), so it needs the same
    # ``public_route_prefix`` the schema editor and the per-type list
    # already carry (design §11 — DB-backed, not derivable in the browser).
    assert set(body["props"]) == {"types", "public_route_prefix", *_TENANCY_PROPS}
    assert [item["key"] for item in body["props"]["types"]] == ["product"]
    assert body["props"]["public_route_prefix"] == "/api/records/public"


async def test_record_list_view(client, records_app):
    _, db_state = records_app
    rtype = await seed_type(db_state, "product", [_field("price", "number")])
    await seed_record(db_state, rtype, {"price": "1"})

    resp = await client.get("/admin/records/product", headers={**roles(ADMIN), **_INERTIA_HEADERS})
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "Records/RecordList"
    # ``content_locales``/``default_locale`` are configuration the browser
    # cannot see (Phase 5 §4.2), and the list's locale selector needs both.
    # Note what is *not* here: any default locale filter. The admin list shows
    # every language, because an editor's question is "what exists" (§4.4).
    assert set(body["props"]) == {
        *_TENANCY_PROPS,
        "type",
        "records",
        "errors",
        "trashed",
        "content_locales",
        "default_locale",
        # The import menu refuses an over-size file before uploading it
        # (review R9/M13); the limit is a DB-backed setting the browser has
        # no other way to know.
        "max_import_bytes",
        # U14/Missing-15: a public type's public URL used to be visible
        # nowhere but the type editor — an admin landing on the list first
        # (the more common path) had no way to verify it from there.
        "public_route_prefix",
        # Where a ``media`` column resolves its thumbnails — ``None`` in this
        # harness, which mounts no media library (``tests/test_media.py``).
        "media_api",
    }
    assert body["props"]["type"]["key"] == "product"
    assert body["props"]["records"]["total"] == 1
    # Always present, so a partial reload after a bad filter clears the notice.
    assert body["props"]["errors"] == {}
    assert body["props"]["max_import_bytes"] > 0
    assert body["props"]["public_route_prefix"] == "/api/records/public"


async def test_record_new_view(client, records_app):
    _, db_state = records_app
    await seed_type(db_state, "product", [_field("price", "number")])

    resp = await client.get(
        "/admin/records/product/new", headers={**roles(ADMIN), **_INERTIA_HEADERS}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "Records/RecordEditor"
    assert set(body["props"]) == {
        *_TENANCY_PROPS,
        "type",
        "record",
        "translations",
        "content_locales",
        "default_locale",
        "media_api",
    }
    assert body["props"]["media_api"] is None
    # Empty rather than absent: the record does not exist yet, so it has no
    # group — but the Languages panel reads one prop shape on both editor
    # screens, and an absent key would leave the previous page's on screen.
    assert body["props"]["translations"] == []
    assert body["props"]["record"] is None
    assert body["props"]["type"]["key"] == "product"


async def test_record_edit_view(client, records_app):
    _, db_state = records_app
    rtype = await seed_type(db_state, "product", [_field("price", "number")])
    record = await seed_record(db_state, rtype, {"price": "1"})

    resp = await client.get(
        f"/admin/records/product/{record.uuid}", headers={**roles(ADMIN), **_INERTIA_HEADERS}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "Records/RecordEditor"
    assert body["props"]["record"]["uuid"] == record.uuid
    assert body["props"]["type"]["key"] == "product"


async def test_new_route_is_not_shadowed_by_uuid_route(client, records_app):
    """Route order: ``/{key}/new`` must win over ``/{key}/{uuid}`` — a type
    with no record literally named ``new`` still has to reach the editor's
    "create" screen rather than a 404 from ``get_record``."""
    _, db_state = records_app
    await seed_type(db_state, "product", [_field("price", "number")])

    resp = await client.get(
        "/admin/records/product/new", headers={**roles(ADMIN), **_INERTIA_HEADERS}
    )
    assert resp.status_code == 200
    assert resp.json()["props"]["record"] is None


async def test_unknown_type_is_404(client):
    resp = await client.get(
        "/admin/records/does-not-exist", headers={**roles(ADMIN), **_INERTIA_HEADERS}
    )
    assert resp.status_code == 404


async def test_unauthenticated_view_request_is_401(client):
    resp = await client.get("/admin/records/", headers=_INERTIA_HEADERS)
    assert resp.status_code == 401


async def test_viewer_role_can_view(client, records_app):
    """``records.view`` is enough for every screen — none of them writes."""
    _, db_state = records_app
    await seed_type(db_state, "product", [_field("price", "number")])
    resp = await client.get("/admin/records/", headers={**roles(ROLE_VIEWER), **_INERTIA_HEADERS})
    assert resp.status_code == 200


async def test_record_list_view_reports_reindexing_filter_inline(client, records_app):
    """A filter on a field mid-reindex must not become a 409 on a page visit —
    Inertia would show a modal. The view renders an empty page and puts the
    reason in Inertia's ``errors`` bag, which the screen reads."""
    _, db_state = records_app
    await seed_type(
        db_state, "product", [_field("price", "number")], reindex_pending={"price": _NOW}
    )
    resp = await client.get(
        "/admin/records/product?filter=price:gt:1",
        headers={**roles(ADMIN), **_INERTIA_HEADERS},
    )
    assert resp.status_code == 200
    props = resp.json()["props"]
    assert props["errors"] == {"filter": "reindexing"}
    assert props["records"]["items"] == []
    assert props["records"]["total"] == 0


async def test_type_editor_views_render_with_targets_and_roles(client, records_app):
    _, db_state = records_app
    await seed_type(db_state, "person", [_field("name", "text")])

    resp = await client.get(
        "/admin/records/types/new", headers={**roles(ADMIN), **_INERTIA_HEADERS}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "Records/TypeEditor"
    assert body["props"]["type"] is None
    assert body["props"]["target_types"] == [{"key": "person", "label": "Person"}]
    assert isinstance(body["props"]["roles"], list)
    assert body["props"]["public_route_prefix"] == "/api/records/public"

    resp = await client.get(
        "/admin/records/types/person", headers={**roles(ADMIN), **_INERTIA_HEADERS}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "Records/TypeEditor"
    assert body["props"]["type"]["key"] == "person"
    assert set(body["props"]) == {
        *_TENANCY_PROPS,
        "type",
        "target_types",
        "roles",
        "public_route_prefix",
        # The "Translatable" toggle has to be able to say which languages it
        # would be turning on, and that list is configuration (§4.2).
        "content_locales",
        "default_locale",
        # Which collections the host declared, which is a fact about the host's
        # Python and nothing the browser can derive (§6.1).
        "collections",
    }


async def test_reserved_type_keys_are_refused(client, records_app):
    """``types`` as a type key would put its record list at the schema
    editor's address; the API refuses it before the routes can collide."""
    for key in ("types", "new"):
        resp = await client.post(
            "/api/records/types", json={"key": key, "label": "X"}, headers=roles(ADMIN)
        )
        assert resp.status_code == 422, key
        assert resp.json()["errors"][0]["field"] == "key"
