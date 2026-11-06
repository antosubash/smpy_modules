"""``/segments`` and ``/lists/{key}/fields`` over HTTP."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.records_seed import TAGS, restrict_list, seed_list, seed_subscriber

API = constants.ROUTE_PREFIX_API
BASE = f"{API}/segments"
VIEW = {"x-perms": constants.PERM_VIEW}
EDIT = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT}"}
RULES = [{"field": "tags", "op": "any", "value": ["vip"]}]


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_list(state, "default", fields=[TAGS])
    await seed_subscriber(state, "default", "a@example.org", "confirmed", data={"tags": ["vip"]})
    await seed_subscriber(state, "default", "b@example.org", "confirmed", data={"tags": []})
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _create(client, name="VIPs") -> dict:
    res = await client.post(
        BASE, json={"name": name, "list_type_key": "news", "rules": RULES}, headers=EDIT
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_crud_round_trip(client):
    created = await _create(client)
    sid = created["id"]
    assert created["rules"] == RULES
    assert (await client.get(BASE, headers=VIEW)).json()[0]["id"] == sid
    assert (await client.get(f"{BASE}?list_type_key=other", headers=VIEW)).json() == []
    prev = await client.post(
        f"{BASE}/preview", json={"list_type_key": "news", "rules": RULES}, headers=VIEW
    )
    assert prev.json() == {"count": 1}
    res = await client.patch(f"{BASE}/{sid}", json={"name": "Everyone", "rules": []}, headers=EDIT)
    assert res.status_code == 200, res.text
    assert (res.json()["name"], res.json()["rules"]) == ("Everyone", [])
    got = (await client.get(f"{BASE}/{sid}", headers=VIEW)).json()
    assert got["name"] == "Everyone"
    dup = await client.post(
        BASE, json={"name": "x", "list_type_key": "news", "rules": []}, headers=EDIT
    )
    assert dup.status_code == 201
    clash = await client.patch(f"{BASE}/{sid}", json={"name": "x"}, headers=EDIT)
    assert (clash.status_code, clash.json()["code"]) == (409, "segment_name_taken")
    assert (await client.delete(f"{BASE}/{sid}", headers=EDIT)).status_code == 204
    assert (await client.get(f"{BASE}/{sid}", headers=VIEW)).status_code == 404


async def test_a_new_segment_reports_its_creation_as_last_change(client):
    """The audit listener stamps ``updated_at`` on update only; the Segments table's
    "Updated" column was blank for a segment nobody had edited yet."""
    created = await _create(client)
    assert created["updated_at"] is not None
    assert "created_at" not in created
    listed = (await client.get(BASE, headers=VIEW)).json()[0]
    assert listed["updated_at"] == created["updated_at"]


async def test_permissions(client):
    sid = (await _create(client))["id"]
    body = {"name": "n", "list_type_key": "news", "rules": []}
    assert (await client.post(BASE, json=body, headers=VIEW)).status_code == 403
    assert (
        await client.patch(f"{BASE}/{sid}", json={"name": "z"}, headers=VIEW)
    ).status_code == 403
    assert (await client.delete(f"{BASE}/{sid}", headers=VIEW)).status_code == 403
    assert (await client.get(BASE)).status_code == 403


async def test_422_never_echoes_values(client):
    bad = {
        "name": "n",
        "list_type_key": "news",
        "rules": [{"field": "tags", "op": "any", "value": ["SECRET-VALUE"]}],
    }
    res = await client.post(BASE, json=bad, headers=EDIT)
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_segment"
    assert "SECRET-VALUE" not in res.text
    odd = {
        "name": "n",
        "list_type_key": "news",
        "rules": [{"field": "tags", "op": "nonsense", "value": "SECRET-VALUE"}],
    }
    res = await client.post(BASE, json=odd, headers=EDIT)
    assert res.status_code == 422 and "SECRET-VALUE" not in res.text


async def test_list_fields_includes_ops_and_signup(client):
    res = await client.get(f"{API}/lists/news/fields", headers=VIEW)
    assert res.status_code == 200, res.text
    by_key = {f["key"]: f for f in res.json()}
    assert by_key["tags"]["ops"] == ["any", "all", "none"]
    assert "created_at" in by_key
    assert "sm_status" not in by_key


async def test_list_fields_unreadable_list_404(built, client):
    _, state = built
    await restrict_list(state, "default", "news", ["editor"])
    assert (await client.get(f"{API}/lists/news/fields", headers=VIEW)).status_code == 404
    assert (await client.get(f"{API}/lists/nope/fields", headers=VIEW)).status_code == 404
    ok = await client.get(f"{API}/lists/news/fields", headers={**VIEW, "x-roles": "editor"})
    assert ok.status_code == 200


async def test_records_refusal_never_echoes_the_value(built, client):
    """A number records cannot quantize passes newsletter's own check and is
    refused by records; the 422 names records' reason only, never the value."""
    _, state = built
    score = {"key": "score", "type": "number", "label": "Score", "indexed": True}
    await seed_list(state, "default", "scored", fields=[score])
    body = {"list_type_key": "scored", "rules": [{"field": "score", "op": "gt", "value": "1e30"}]}
    res = await client.post(f"{BASE}/preview", json=body, headers=VIEW)
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "invalid_segment"
    assert "1e30" not in res.text
    assert "score" not in res.json()["detail"].removeprefix("filter: ")
    created = await client.post(BASE, json={"name": "n", **body}, headers=EDIT)
    assert created.status_code == 422 and "1e30" not in created.text
