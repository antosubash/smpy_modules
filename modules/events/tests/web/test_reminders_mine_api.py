"""Reminders API, part two: "my reminders", the route table, rate limits and tenancy."""

from __future__ import annotations

import pytest
from simple_module_core.mail import reset_mail_sender
from sm_events.core.constants import reminders_limits as limits
from sm_events.core.tenancy import tenant_scope
from sm_events.module import EventsModule
from sm_events.web.endpoints import reminders_api
from sqlalchemy import select

from tests.reminders.support import drop_share, make_ready, seed_http
from tests.support.app import as_user

V, M = "events.view", "events.manage"
BASE = "/api/events"
U, Z, MGR, SV = as_user("u", V), as_user("z", V), as_user("m", V, M), as_user("sv", V)


@pytest.fixture(autouse=True)
def _clean_mail():
    reset_mail_sender()
    yield
    reset_mail_sender()


@pytest.fixture
async def world(client, monkeypatch):
    make_ready(client.app, monkeypatch)
    return client, await seed_http(client)


def follow_url(event_id: str) -> str:
    return f"{BASE}/events/{event_id}/follow"


async def _count(client, user: str | None = None) -> int:
    from sm_events.models import EventFollow
    from sqlalchemy import func

    async with client.db_state.session_factory() as db:
        stmt = select(func.count()).select_from(EventFollow)
        if user:
            stmt = stmt.where(EventFollow.user_id == user)
        return (await db.execute(stmt)).scalar_one()


async def test_mine_lists_only_the_callers_own_visible_follows(world):
    client, ids = world
    await client.put(follow_url(ids["pub"]["U"]), json={"leads": [60, 15]}, headers=U)
    await client.put(follow_url(ids["pub"]["P"]), json={"leads": [60]}, headers=SV)
    await client.put(follow_url(ids["pub"]["U"]), json={"leads": [1440]}, headers=Z)
    got = (await client.get(f"{BASE}/reminders/mine", headers=U)).json()
    assert (got["total"], got["hidden"], got["page"], got["page_size"]) == (1, 0, 1, 50)
    (item,) = got["items"]
    assert item["event_id"] == ids["pub"]["U"] and item["leads"] == [15, 60]
    assert item["title"] == "Pub U" and item["lang"] == "en"
    assert set(item["calendar"]) == {"id", "name", "color"}
    assert "user_id" not in str(got) and item["hidden"] is False and item["follow_id"]
    # A manager sees their own follows only: someone else's are neither listed nor counted.
    manager = (await client.get(f"{BASE}/reminders/mine", headers=MGR)).json()
    assert (manager["total"], manager["hidden"], manager["items"]) == (0, 0, [])
    # The share goes: counted, never named.
    async with client.db_state.session_factory() as db:
        from sm_events.models import Calendar

        cal = (await db.execute(select(Calendar).where(Calendar.slug == "private"))).scalar_one()
        await drop_share(db, cal, "sv")
        await db.commit()
    hidden = (await client.get(f"{BASE}/reminders/mine", headers=SV)).json()
    assert (hidden["total"], hidden["hidden"]) == (1, 1)
    (opaque,) = hidden["items"]
    assert opaque["hidden"] is True and opaque["follow_id"]
    assert {k for k, v in opaque.items() if v not in (None, [], False)} == {"follow_id", "hidden"}
    assert "Pub P" not in str(hidden) and ids["pub"]["P"] not in str(hidden)
    # The handle removes it, once, and only for its owner.
    gone = f"{BASE}/reminders/follows/{opaque['follow_id']}"
    assert (await client.delete(gone, headers=U)).status_code == 404  # not u's follow
    assert (await client.delete(gone, headers=SV)).status_code == 204
    assert (await client.delete(gone, headers=SV)).status_code == 404
    assert (await client.get(f"{BASE}/reminders/mine", headers=SV)).json()["total"] == 0


@pytest.mark.parametrize("query", ["page=0", "page=-1", "page_size=0", "page_size=101", "page=x"])
async def test_mine_paging_bounds_are_422(world, query):
    client, _ = world
    assert (await client.get(f"{BASE}/reminders/mine?{query}", headers=U)).status_code == 422


async def test_mine_pages(world):
    client, ids = world
    for key in ("I", "U"):
        await client.put(follow_url(ids["pub"][key]), json={"leads": [60]}, headers=U)
    first = (await client.get(f"{BASE}/reminders/mine?page_size=1", headers=U)).json()
    second = (await client.get(f"{BASE}/reminders/mine?page_size=1&page=2", headers=U)).json()
    assert first["total"] == second["total"] == 2
    assert {first["items"][0]["event_id"], second["items"][0]["event_id"]} == {
        ids["pub"]["I"],
        ids["pub"]["U"],
    }


async def test_every_route_goes_through_the_one_ownership_dependency():
    """A new route that forgets it fails here: every handler acts as its own caller."""

    def calls_of(dependant) -> list:
        found = []
        for dep in dependant.dependencies:
            found.append(dep.call)
            found.extend(calls_of(dep))
        return found

    routes = reminders_api.router.routes
    assert routes
    missing = [r.name for r in routes if reminders_api.caller not in calls_of(r.dependant)]
    assert missing == []
    assert {r.name for r in routes} == {
        "reminders_status",
        "get_follow",
        "put_follow",
        "delete_follow",
        "my_reminders",
        "delete_follow_by_id",
        "delivery",
    }


def test_follow_writes_are_rate_limited_per_user():
    from simple_module_core.rate_limit import RateLimitRegistry

    rates = RateLimitRegistry()
    EventsModule().register_rate_limits(rates)
    path = follow_url("abc")
    for method in ("PUT", "DELETE"):
        rule = rates.match(method, path)
        assert rule is not None and rule.key == "user" and rule.rate == limits.FOLLOW_RATE
    by_id = f"{BASE}/reminders/follows/abc"
    rule = rates.match("DELETE", by_id)
    assert rule is not None and rule.key == "user" and rule.rate == limits.FOLLOW_RATE
    assert rates.match("GET", by_id) is None
    assert rates.match("GET", path) is None
    assert rates.match("PUT", f"{path}/x") is None


@pytest.mark.unbound_tenant
async def test_tenant_isolation(multi_client, monkeypatch):
    client = multi_client
    make_ready(client.app, monkeypatch)
    ids = await seed_http(client, "a")
    a, b = as_user("u", V, tenant="a"), as_user("u", V, tenant="b")
    url = follow_url(ids["pub"]["U"])
    assert (await client.put(url, json={"leads": [60]}, headers=a)).status_code == 200
    # The same user id in another tenant: the event is not there, and neither is the follow.
    assert (await client.get(url, headers=b)).status_code == 404
    assert (await client.put(url, json={"leads": [60]}, headers=b)).status_code == 404
    assert (await client.get(f"{BASE}/reminders/mine", headers=b)).json()["total"] == 0
    assert (await client.get(f"{BASE}/reminders/mine", headers=a)).json()["total"] == 1
    with tenant_scope("a"):
        assert await _count(client, "u") == 1


@pytest.mark.unbound_tenant
async def test_multi_without_tenant_is_403_tenant_required(multi_client, monkeypatch):
    make_ready(multi_client.app, monkeypatch)
    got = await multi_client.get(f"{BASE}/reminders/status", headers=as_user("u", V))
    assert (got.status_code, got.json()["code"]) == (403, "tenant_required")


def test_request_locale_is_shape_checked():
    from types import SimpleNamespace

    from sm_events.reminders.follows import request_locale

    def of(value):
        return request_locale(SimpleNamespace(state=SimpleNamespace(locale=value)), "en")

    assert of("de") == "de" and of("pt-BR") == "pt-BR"
    for bad in (None, "", "x", "../etc", "a" * 17, 7, "de;drop", "dé"):
        assert of(bad) == "en", bad
