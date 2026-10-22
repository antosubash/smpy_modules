"""The admin record screens: a malformed ``filter=`` and who may open the editor.

A malformed filter on a *page navigation* lands in the screen's errors bag
instead of a bare 400, and the schema editor screens need
``records.manage_types`` rather than ``records.view``.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_MANAGER, ROLE_VIEWER, roles

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
# a malformed ``filter=`` on a page navigation
# --------------------------------------------------------------------------


async def test_a_malformed_filter_on_the_list_view_lands_in_errors(client):
    await _make(client, "product", [_field("price", "number")])
    resp = await client.get(
        "/admin/records/product?filter=nonsense", headers={**roles(ADMIN), **_INERTIA}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "Records/RecordList"
    assert body["props"]["list_errors"] == {"filter": "malformed"}
    assert body["props"]["records"]["total"] == 0


async def test_a_well_formed_but_refused_filter_still_reports_its_own_reason(client):
    await _make(client, "product", [_field("price", "number")])
    resp = await client.get(
        "/admin/records/product?filter=ghost:eq:1", headers={**roles(ADMIN), **_INERTIA}
    )
    assert resp.json()["props"]["list_errors"] == {"filter": "unknown"}


async def test_the_json_api_still_refuses_a_malformed_filter_with_a_400(client):
    """Unchanged: an API caller wants the status code, and has no ``errors``
    bag to read."""
    await _make(client, "product", [_field("price", "number")])
    resp = await client.get(
        "/api/records/types/product/records?filter=nonsense", headers=roles(ADMIN)
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# the schema editor screens need ``records.manage_types``
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
