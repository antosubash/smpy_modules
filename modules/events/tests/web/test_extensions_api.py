"""``/api/events/sources`` and ``PUT /api/events/calendars/{id}/sources``."""

from __future__ import annotations

import pytest
from sm_events.calendar import registry

from tests.support.access import grant
from tests.support.app import as_user
from tests.support.calendars import BASE, MANAGER, OWNER, SE, SV, VIEWER, M, V, make
from tests.support.events_http import run
from tests.support.sources import FakeSource, SettingsSource, install

SOURCES = "/api/events/sources"


@pytest.fixture(autouse=True)
def plugins(monkeypatch):
    install(monkeypatch, SettingsSource(), FakeSource("acme:plain", public=True))
    yield
    registry.reset_registry()


def put(client, cid, sources, headers=OWNER):
    return client.put(f"{BASE}/{cid}/sources", json={"sources": sources}, headers=headers)


async def test_list_sources_excludes_builtin(client):
    got = await client.get(SOURCES, headers=VIEWER)
    assert got.status_code == 200
    rows = got.json()
    assert [r["id"] for r in rows] == ["acme:desk", "acme:plain"]
    desk, plain = rows
    assert (desk["has_settings"], desk["public"]) == (True, False)
    assert desk["settings_schema"]["properties"]["field"]
    assert (plain["has_settings"], plain["public"], plain["settings_schema"]) == (False, True, None)
    assert (await client.get(SOURCES)).status_code == 401


async def test_put_needs_visibility_right(client):
    cid = (await make(client))["id"]
    await grant(client, cid, "sv", "view")
    await grant(client, cid, "se", "edit")
    body = [{"id": "acme:plain"}]
    got = await put(client, cid, body, SE)  # an edit share is not the visibility right
    assert (got.status_code, got.json()["code"]) == (403, "owner_required")
    assert (await put(client, cid, body, SV)).status_code == 403
    stranger = await put(client, cid, body, VIEWER)
    assert (stranger.status_code, stranger.json()["code"]) == (404, "not_found")
    assert (await put(client, cid, body, OWNER)).status_code == 200
    assert (await put(client, cid, body, MANAGER)).status_code == 200
    assert (await put(client, cid, body, {})).status_code == 401


async def test_put_round_trip_and_calendar_out(client):
    cid = (await make(client))["id"]
    got = await put(client, cid, [{"id": "acme:desk", "settings": {"field": "x", "count": "2"}}])
    assert got.status_code == 200, got.text
    (entry,) = got.json()["sources"]
    assert entry == {
        "id": "acme:desk",
        "settings": {"field": "x", "count": 2},
        "installed": True,
        "label_key": "acme.fake",
    }
    again = await client.get(f"{BASE}/{cid}", headers=OWNER)
    assert again.json()["sources"] == [entry]
    cleared = await put(client, cid, [])
    assert cleared.json()["sources"] == []


async def test_settings_visible_only_to_those_who_manage(client):
    cid = (await make(client))["id"]
    await put(client, cid, [{"id": "acme:desk", "settings": {"field": "private-ish"}}])
    await grant(client, cid, "sv", "view")
    seen = (await client.get(f"{BASE}/{cid}", headers=SV)).json()["sources"][0]
    assert (seen["id"], seen["settings"], seen["installed"]) == ("acme:desk", {}, True)
    listed = (await client.get(BASE, headers=SV)).json()[0]["sources"][0]
    assert listed["settings"] == {}
    mine = (await client.get(BASE, headers=OWNER)).json()[0]["sources"][0]
    assert mine["settings"]["field"] == "private-ish"


async def test_validation_errors_are_422_lists(client):
    cid = (await make(client))["id"]
    bad = await put(client, cid, [{"id": "acme:desk", "settings": {"count": "x"}}])
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["loc"] == ["body", "sources", 0, "settings", "count"]
    refused = await put(client, cid, [{"id": "acme:desk", "settings": {"field": "bad"}}])
    assert refused.json()["detail"][0]["loc"] == ["body", "sources", 0, "settings", "field"]
    for sources, code in (
        ([{"id": "events"}], "builtin_source"),
        ([{"id": "nope:x"}], "unknown_source"),
        ([{"id": "acme:plain"}, {"id": "acme:plain"}], "duplicate_source"),
        ([{"id": f"x:s{i}"} for i in range(9)], "too_many_sources"),
    ):
        got = await put(client, cid, sources)
        assert (got.status_code, got.json()["code"]) == (422, code)
    unavailable = await put(client, cid, [{"id": "acme:desk", "settings": {"field": "boom"}}])
    assert (unavailable.status_code, unavailable.json()["code"]) == (503, "source_unavailable")
    assert "leaked" not in unavailable.text
    assert (await put(client, cid, [{"id": "acme:plain", "extra": 1}])).status_code == 200
    assert (await put(client, cid, "nope")).status_code == 422  # type: ignore[arg-type]


async def test_not_installed_entry_shown_and_kept(client):
    cid = (await make(client))["id"]
    import uuid

    from sm_events.models import Calendar
    from sqlalchemy import select

    async def seed(s):
        cal = (await s.execute(select(Calendar).where(Calendar.id == uuid.UUID(cid)))).scalar_one()
        cal.sources = ["gone:thing"]

    await run(client, seed)
    shown = (await client.get(f"{BASE}/{cid}", headers=OWNER)).json()["sources"]
    assert shown == [{"id": "gone:thing", "settings": {}, "installed": False, "label_key": None}]
    kept = await put(client, cid, [{"id": "gone:thing"}, {"id": "acme:plain"}])
    assert [s["id"] for s in kept.json()["sources"]] == ["gone:thing", "acme:plain"]
    assert (await put(client, cid, [{"id": "gone:thing", "settings": {"a": 1}}])).status_code == 422


async def test_put_needs_csrf(csrf_client):
    token = (await csrf_client.get("/token")).json()["token"]
    made = await csrf_client.post(
        BASE, json={"name": "T"}, headers={**OWNER, "X-CSRF-Token": token}
    )
    url = f"{BASE}/{made.json()['id']}/sources"
    body = {"sources": [{"id": "acme:plain"}]}
    refused = await csrf_client.put(url, json=body, headers=OWNER)
    assert refused.status_code == 403 and "CSRF" in refused.json()["detail"]
    ok = await csrf_client.put(url, json=body, headers={**OWNER, "X-CSRF-Token": token})
    assert ok.status_code == 200


@pytest.mark.unbound_tenant
async def test_tenant_isolation(multi_client):
    a = as_user("o", V, "events.edit", tenant="a")
    b = as_user("o", V, "events.edit", M, tenant="b")
    cid = (await multi_client.post(BASE, json={"name": "A's"}, headers=a)).json()["id"]
    got = await multi_client.put(
        f"{BASE}/{cid}/sources", json={"sources": [{"id": "acme:plain"}]}, headers=b
    )
    assert got.status_code == 404
    ok = await multi_client.put(
        f"{BASE}/{cid}/sources", json={"sources": [{"id": "acme:plain"}]}, headers=a
    )
    assert ok.status_code == 200
    assert (await multi_client.get(f"{BASE}/{cid}", headers=b)).status_code == 404
