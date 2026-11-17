"""``/api/events/categories``."""

from __future__ import annotations

import pytest

from tests.support.app import as_user

V, E, M = "events.view", "events.edit", "events.manage"
BASE = "/api/events/categories"
VIEWER = as_user("v", V)
MANAGER = as_user("m", V, M)


async def test_view_can_list_manage_writes(client):
    assert (await client.get(BASE, headers=VIEWER)).status_code == 200
    assert (
        await client.post(BASE, json={"names": {"en": "Music"}}, headers=VIEWER)
    ).status_code == 403
    made = await client.post(
        BASE, json={"names": {"en": "Music"}, "color": "#AA0000"}, headers=MANAGER
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert (body["slug"], body["names"], body["color"]) == ("music", {"en": "Music"}, "#aa0000")
    assert set(body) == {"id", "slug", "names", "color"}
    assert [c["slug"] for c in (await client.get(BASE, headers=VIEWER)).json()] == ["music"]
    assert (await client.get(BASE)).status_code == 401


async def test_unknown_locale_is_422(client):
    client.app.state.sm_events.settings.content_locales = ("en", "de")
    got = await client.post(BASE, json={"names": {"en": "A", "fr": "B"}}, headers=MANAGER)
    assert (got.status_code, got.json()["code"]) == (422, "unknown_locale")
    assert (
        await client.post(BASE, json={"names": {"de": "Nur"}}, headers=MANAGER)
    ).status_code == 422
    ok = await client.post(BASE, json={"names": {"en": "A", "de": "B"}}, headers=MANAGER)
    assert ok.status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"names": {}},
        {"names": {"en": ""}},
        {"names": {"en": "x" * 101}},
        {"names": {"en": "A"}, "color": "red"},
    ],
)
async def test_bad_bodies_are_422(client, body):
    assert (await client.post(BASE, json=body, headers=MANAGER)).status_code == 422


async def test_slug_taken_409(client):
    await client.post(BASE, json={"slug": "music", "names": {"en": "Music"}}, headers=MANAGER)
    got = await client.post(BASE, json={"slug": "music", "names": {"en": "Other"}}, headers=MANAGER)
    assert (got.status_code, got.json()["code"]) == (409, "slug_taken")


async def test_patch_and_delete(client):
    cid = (await client.post(BASE, json={"names": {"en": "Music"}}, headers=MANAGER)).json()["id"]
    assert (
        await client.patch(f"{BASE}/{cid}", json={"color": None}, headers=VIEWER)
    ).status_code == 403
    patched = await client.patch(
        f"{BASE}/{cid}", json={"names": {"en": "Sound"}, "color": None}, headers=MANAGER
    )
    assert (patched.status_code, patched.json()["names"], patched.json()["color"]) == (
        200,
        {"en": "Sound"},
        None,
    )
    assert (await client.delete(f"{BASE}/{cid}", headers=VIEWER)).status_code == 403
    assert (await client.delete(f"{BASE}/{cid}", headers=MANAGER)).status_code == 204
    assert (await client.get(BASE, headers=VIEWER)).json() == []
    gone = await client.delete(f"{BASE}/{cid}", headers=MANAGER)
    assert (gone.status_code, gone.json()["code"]) == (404, "not_found")


@pytest.mark.unbound_tenant
async def test_tenant_isolation(multi_client):
    client = multi_client
    a = as_user("m", V, M, tenant="a")
    b = as_user("m", V, M, tenant="b")
    cid = (await client.post(BASE, json={"names": {"en": "Music"}}, headers=a)).json()["id"]
    assert (await client.get(BASE, headers=b)).json() == []
    assert (
        await client.patch(f"{BASE}/{cid}", json={"color": "#112233"}, headers=b)
    ).status_code == 404
    assert (await client.delete(f"{BASE}/{cid}", headers=b)).status_code == 404
    assert [c["id"] for c in (await client.get(BASE, headers=a)).json()] == [cid]
    # The same slug in another tenant is a different category.
    assert (await client.post(BASE, json={"names": {"en": "Music"}}, headers=b)).status_code == 201
