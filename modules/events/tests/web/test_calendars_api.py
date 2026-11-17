"""``/api/events/calendars`` end to end: access, envelope, tenancy, CSRF, ownership."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_events.web.schemas.calendars import CalendarCreate, CalendarPatch, OwnerIn

from tests.support.access import grant
from tests.support.app import Directory, as_user
from tests.support.calendars import (
    BASE,
    EDITOR,
    MANAGER,
    OWNER,
    OWNER_P,
    SE,
    SV,
    VIEWER,
    E,
    M,
    V,
    make,
)


async def test_create_needs_events_edit(client):
    got = await client.post(BASE, json={"name": "T"}, headers=VIEWER)
    assert got.status_code == 403
    made = await client.post(BASE, json={"name": "T"}, headers=EDITOR)
    assert made.status_code == 201
    body = made.json()
    assert body["owner_id"] == "e" and body["visibility"] == "private"
    assert (body["can_edit"], body["can_own"], body["can_write_events"]) == (True, True, True)


async def test_anonymous_is_401(client):
    assert (await client.get(BASE)).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"name": "T", "default_timezone": "Mars/Base"},
        {"name": "T", "color": "red"},
        {"name": " "},
        {"name": "T", "slug": "Bad Slug"},
    ],
)
async def test_bad_values_are_422(client, body):
    assert (await client.post(BASE, json=body, headers=OWNER)).status_code == 422


async def test_color_is_lowercased_and_slug_derived(client):
    made = await make(client, color="#AABBCC", name="Ärger")
    assert (made["color"], made["slug"]) == ("#aabbcc", "arger")


async def test_explicit_taken_slug_is_409_even_in_the_trash(client):
    first = await make(client, slug="team")
    again = await client.post(BASE, json={"name": "X", "slug": "team"}, headers=OWNER)
    assert (again.status_code, again.json()["code"]) == (409, "slug_taken")
    assert (await client.delete(f"{BASE}/{first['id']}", headers=OWNER)).status_code == 204
    again = await client.post(BASE, json={"name": "X", "slug": "team"}, headers=OWNER)
    assert (again.status_code, again.json()["code"]) == (409, "slug_taken")


async def test_stranger_sees_404_everywhere(client):
    cid = (await make(client))["id"]
    url = f"{BASE}/{cid}"
    for call in (
        client.get(url, headers=VIEWER),
        client.patch(url, json={"name": "x"}, headers=VIEWER),
        client.put(f"{url}/visibility", json={"visibility": "public"}, headers=VIEWER),
        client.delete(url, headers=VIEWER),
        client.post(f"{url}/restore", headers=VIEWER),
    ):
        got = await call
        assert (got.status_code, got.json()) == (404, {"detail": "Not found", "code": "not_found"})
    assert (await client.get(BASE, headers=VIEWER)).json() == []
    # Not even a manager-only action leaks the calendar to a stranger.
    assert (
        await client.put(f"{url}/owner", json={"owner_id": "v"}, headers=VIEWER)
    ).status_code == 403


async def test_share_holder_403s(client):
    cid = (await make(client))["id"]
    await grant(client, cid, "sv", "view")
    await grant(client, cid, "se", "edit")
    url = f"{BASE}/{cid}"
    assert (await client.get(url, headers=SV)).status_code == 200
    got = await client.patch(url, json={"name": "x"}, headers=SV)
    assert (got.status_code, got.json()["code"]) == (403, "forbidden")
    assert (await client.patch(url, json={"name": "Renamed"}, headers=SE)).json()[
        "name"
    ] == "Renamed"
    for call in (
        client.put(f"{url}/visibility", json={"visibility": "public"}, headers=SE),
        client.delete(url, headers=SE),
    ):
        got = await call
        assert (got.status_code, got.json()["code"]) == (403, "owner_required")


async def test_manage_bypasses(client):
    cid = (await make(client))["id"]
    url = f"{BASE}/{cid}"
    assert (await client.get(url, headers=MANAGER)).status_code == 200
    assert (
        await client.patch(url, json={"name": "By manager"}, headers=MANAGER)
    ).status_code == 200
    vis = await client.put(f"{url}/visibility", json={"visibility": "internal"}, headers=MANAGER)
    assert vis.json()["visibility"] == "internal"
    assert (await client.delete(url, headers=MANAGER)).status_code == 204
    listed = await client.get(BASE, params={"trashed": "true"}, headers=MANAGER)
    assert [c["id"] for c in listed.json()] == [cid]
    restored = await client.post(f"{url}/restore", headers=MANAGER)
    assert (restored.status_code, restored.json()["deleted_at"]) == (200, None)


async def test_visibility_internal_is_seen_by_members(client):
    cid = (await make(client))["id"]
    assert (await client.get(f"{BASE}/{cid}", headers=VIEWER)).status_code == 404
    got = await client.put(
        f"{BASE}/{cid}/visibility", json={"visibility": "internal"}, headers=OWNER
    )
    assert got.status_code == 200
    seen = await client.get(f"{BASE}/{cid}", headers=VIEWER)
    assert seen.status_code == 200
    assert (seen.json()["can_edit"], seen.json()["can_write_events"]) == (False, False)
    # events.edit holders write events in an internal calendar but never edit its metadata.
    mine = await client.get(f"{BASE}/{cid}", headers=EDITOR)
    assert (mine.json()["can_edit"], mine.json()["can_write_events"]) == (False, True)
    assert (
        await client.patch(f"{BASE}/{cid}", json={"name": "x"}, headers=EDITOR)
    ).status_code == 403
    bad = await client.put(f"{BASE}/{cid}/visibility", json={"visibility": "nope"}, headers=OWNER)
    assert bad.status_code == 422


async def test_error_envelope(client):
    """Every error the module raises. The framework's own permission gate
    (``RequiresPermission``) keeps its ``{"detail"}`` body, as everywhere."""
    cid = (await make(client))["id"]
    await grant(client, cid, "sv", "view")
    responses = [
        await client.get(f"{BASE}/{cid}", headers=VIEWER),
        await client.patch(f"{BASE}/{cid}", json={"name": "x"}, headers=SV),
        await client.post(BASE, json={"name": "X", "slug": "team"}, headers=OWNER),
        await client.delete(f"{BASE}/{cid}", headers=SV),
    ]
    for got in responses:
        assert got.status_code >= 400
        if got.status_code != 422:
            assert set(got.json()) == {"detail", "code"}, got.text


async def test_rights_in_out(client):
    cid = (await make(client, OWNER))["id"]
    url = f"{BASE}/{cid}"
    assert (await client.get(url, headers=OWNER)).json()["can_publish"] is False
    assert (await client.get(url, headers=OWNER_P)).json()["can_publish"] is True


async def test_unknown_id_and_bad_id(client):
    assert (
        await client.get(f"{BASE}/00000000-0000-0000-0000-000000000001", headers=OWNER)
    ).status_code == 404
    assert (await client.get(f"{BASE}/not-a-uuid", headers=OWNER)).status_code == 422


async def test_patch_null_name_is_422(client):
    cid = (await make(client))["id"]
    assert (
        await client.patch(f"{BASE}/{cid}", json={"name": None}, headers=OWNER)
    ).status_code == 422


@pytest.mark.unbound_tenant
async def test_tenant_isolation(multi_client):
    client = multi_client
    a = as_user("o", V, E, tenant="a")
    b = as_user("o", V, E, M, tenant="b")
    made = await client.post(BASE, json={"name": "A's"}, headers=a)
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    assert (await client.get(f"{BASE}/{cid}", headers=b)).status_code == 404
    assert (await client.get(BASE, headers=b)).json() == []
    assert (await client.get(BASE, headers=a)).json()[0]["id"] == cid
    # The same name and slug in another tenant is a different calendar.
    other = await client.post(BASE, json={"name": "A's"}, headers=b)
    assert (other.status_code, other.json()["slug"]) == (201, made.json()["slug"])


@pytest.mark.unbound_tenant
async def test_multi_without_tenant_is_403_tenant_required(multi_client):
    got = await multi_client.get(BASE, headers=as_user("o", V, E))
    assert (got.status_code, got.json()["code"]) == (403, "tenant_required")


async def test_writes_need_csrf(csrf_client):
    got = await csrf_client.post(BASE, json={"name": "T"}, headers=OWNER)
    assert got.status_code == 403
    assert "CSRF" in got.json()["detail"]
    token = (await csrf_client.get("/token")).json()["token"]
    ok = await csrf_client.post(BASE, json={"name": "T"}, headers={**OWNER, "X-CSRF-Token": token})
    assert ok.status_code == 201


async def test_ownership_transfer(client):
    client.app.state.user_directory = Directory(
        {"n": ("n@x", "New Owner", True), "gone": ("g@x", "Gone", False)}
    )
    cid = (await make(client))["id"]
    url = f"{BASE}/{cid}/owner"
    # Only events.manage: the owner is refused.
    assert (await client.put(url, json={"owner_id": "n"}, headers=OWNER)).status_code == 403
    moved = await client.put(url, json={"owner_id": "n"}, headers=MANAGER)
    assert (moved.status_code, moved.json()["owner_id"]) == (200, "n")
    for who in ("gone", "nobody"):
        bad = await client.put(url, json={"owner_id": who}, headers=MANAGER)
        assert (bad.status_code, bad.json()["code"]) == (422, "owner_not_allowed")
    # The former owner has lost the calendar.
    assert (await client.get(f"{BASE}/{cid}", headers=OWNER)).status_code == 404


async def test_ownership_transfer_without_a_directory_is_503(client):
    cid = (await make(client))["id"]
    from simple_module_core.user_directory import NullUserDirectory

    client.app.state.user_directory = NullUserDirectory()
    got = await client.put(f"{BASE}/{cid}/owner", json={"owner_id": "n"}, headers=MANAGER)
    assert (got.status_code, got.json()["code"]) == (503, "user_directory_unavailable")


@pytest.mark.unbound_tenant
async def test_ownership_transfer_only_to_members_of_the_tenant(multi_client, monkeypatch):
    client = multi_client
    client.app.state.user_directory = Directory(
        {"in": ("in@x", "In", True), "out": ("out@x", "Out", True)}
    )

    async def members(db, tenant_id, user_ids):
        return {u for u in user_ids if u == "in"}

    client.app.state.tenant_members = members
    a = as_user("o", V, E, tenant="a")
    boss = as_user("m", V, M, tenant="a")
    cid = (await client.post(BASE, json={"name": "T"}, headers=a)).json()["id"]
    url = f"{BASE}/{cid}/owner"
    bad = await client.put(url, json={"owner_id": "out"}, headers=boss)
    assert (bad.status_code, bad.json()["code"]) == (422, "owner_not_allowed")
    assert (await client.put(url, json={"owner_id": "in"}, headers=boss)).status_code == 200


@pytest.mark.parametrize("field,limit", [("name", 200), ("slug", 80), ("description", 2000)])
@pytest.mark.parametrize("schema", [CalendarCreate, CalendarPatch])
def test_calendar_string_limits(field, limit, schema):
    assert getattr(schema(**{"name": "Team", field: "x" * limit}), field) == "x" * limit
    with pytest.raises(ValidationError):
        schema(**{"name": "Team", field: "x" * (limit + 1)})


def test_owner_id_length_limit():
    assert OwnerIn(owner_id="x" * 64).owner_id == "x" * 64
    with pytest.raises(ValidationError):
        OwnerIn(owner_id="x" * 65)


def test_timezone_width_limit(monkeypatch):
    from sm_events.core import timezones

    monkeypatch.setattr(timezones, "is_known", lambda _name: True)  # Isolate width from tzdata.
    for schema in (CalendarCreate, CalendarPatch):
        assert schema(name="Team", default_timezone="x" * 64).default_timezone == "x" * 64
        with pytest.raises(ValidationError):
            schema(name="Team", default_timezone="x" * 65)
