"""``/api/newsletter/cards/events``, the event kind of ``/cards/snapshot`` and its refresh."""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_events.core import clock
from sm_events.models import Visibility
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.events_seed import seed_event
from tests.support.news_seed import seed_article
from tests.support.records_seed import seed_list

API = constants.ROUTE_PREFIX_API
VIEW = {"x-perms": constants.PERM_VIEW}
EDIT = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT}"}
NOW = datetime(2026, 7, 1, 7, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: NOW)


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    app.state.sm_events = SimpleNamespace()
    await seed_list(state, "default")
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    async with AsyncClient(transport=ASGITransport(app=built[0]), base_url="http://t") as c:
        yield c


async def test_search_events_route(client, built):
    state = built[1]
    ok = await seed_event(state, "default", title="Open day", slug="open")
    await seed_event(state, "default", title="Open draft", slug="d", status="draft")
    await seed_event(
        state, "default", title="Open internal", slug="i", visibility=Visibility.INTERNAL
    )
    await seed_event(
        state, "default", title="Open past", slug="p", starts_at=datetime(2026, 6, 1, tzinfo=UTC)
    )
    hits = (await client.get(f"{API}/cards/events?q=open", headers=EDIT)).json()
    assert [(h["kind"], h["source_id"], h["title"]) for h in hits] == [
        ("event", str(ok), "Open day")
    ]
    assert hits[0]["url"] == "/events/open" and hits[0]["ics_url"] == "/events/open.ics"
    assert hits[0]["timezone"] == "Europe/Vienna"
    assert (await client.get(f"{API}/cards/events?q=autumn", headers=EDIT)).json() == []


async def test_snapshot_event_route(client, built):
    eid = await seed_event(built[1], "default")
    res = await client.post(
        f"{API}/cards/snapshot", json={"kind": "event", "source_id": str(eid)}, headers=EDIT
    )
    assert res.status_code == 200, res.text
    props = res.json()
    assert (props["source_id"], props["title"], props["ics_url"]) == (
        str(eid),
        "Open day",
        "/events/open-day.ics",
    )
    assert len(props["id"]) == 12 and props["starts_at"].startswith("2026-07-01T08:00")
    for body in (
        {"kind": "event", "source_id": 7},
        {"kind": "event", "source_id": "not-a-uuid"},
        {"kind": "article", "source_id": str(eid)},
        {"kind": "event", "source_id": str(eid), "extra": 1},
    ):
        bad = await client.post(f"{API}/cards/snapshot", json=body, headers=EDIT)
        assert bad.status_code == 422, body
    nobody = await client.post(
        f"{API}/cards/snapshot",
        json={"kind": "event", "source_id": str(uuid.uuid4())},
        headers=EDIT,
    )
    assert (nobody.status_code, nobody.json()["code"]) == (404, "not_found")


async def test_a_draft_or_internal_event_cannot_be_snapshotted(client, built):
    hidden = (("d", {"status": "draft"}), ("i", {"visibility": Visibility.INTERNAL}))
    for slug, fields in hidden:
        eid = await seed_event(built[1], "default", slug=slug, **fields)
        res = await client.post(
            f"{API}/cards/snapshot", json={"kind": "event", "source_id": str(eid)}, headers=EDIT
        )
        assert (res.status_code, res.json()["code"]) == (404, "not_found")


async def _campaign_with_event_card(client, props: dict) -> dict:
    res = await client.post(
        f"{API}/campaigns", json={"name": "S", "list_type_key": "news"}, headers=EDIT
    )
    cid = res.json()["id"]
    body = [{"type": "EventCard", "props": props}]
    res = await client.patch(
        f"{API}/campaigns/{cid}", json={"expected_revision": 1, "body": body}, headers=EDIT
    )
    assert res.status_code == 200, res.text
    return res.json()


async def test_refresh_event_card(client, built):
    eid = await seed_event(built[1], "default")
    snap = (
        await client.post(
            f"{API}/cards/snapshot", json={"kind": "event", "source_id": str(eid)}, headers=EDIT
        )
    ).json()
    detail = await _campaign_with_event_card(client, snap)
    res = await client.post(
        f"{API}/campaigns/{detail['id']}/cards/refresh",
        json={"block_id": snap["id"], "expected_revision": detail["revision"]},
        headers=EDIT,
    )
    assert res.status_code == 200, res.text
    assert res.json()["body"][0]["props"]["source_id"] == str(eid)


async def test_event_routes_unavailable(client, built, monkeypatch):
    """Events not mounted, or its contract not importable: 409 on every event route, while the
    article routes keep answering."""
    app, state = built
    eid = await seed_event(state, "default")
    snap = (
        await client.post(
            f"{API}/cards/snapshot", json={"kind": "event", "source_id": str(eid)}, headers=EDIT
        )
    ).json()
    detail = await _campaign_with_event_card(client, snap)
    app.state.news = SimpleNamespace()
    await seed_article(state, "default")
    calls = [
        ("GET", f"{API}/cards/events?q=a", None),
        ("POST", f"{API}/cards/snapshot", {"kind": "event", "source_id": str(eid)}),
        (
            "POST",
            f"{API}/campaigns/{detail['id']}/cards/refresh",
            {"block_id": snap["id"], "expected_revision": detail["revision"]},
        ),
    ]
    for how in ("not mounted", "import blocked"):
        if how == "not mounted":
            del app.state.sm_events
        else:
            app.state.sm_events = SimpleNamespace()
            monkeypatch.setitem(sys.modules, "sm_events.contracts.cards", None)
        for method, url, body in calls:
            res = await client.request(method, url, json=body, headers=EDIT)
            assert (res.status_code, res.json()["code"]) == (409, "integration_unavailable"), (
                how,
                url,
            )
        assert (await client.get(f"{API}/cards/articles?q=spring", headers=EDIT)).status_code == 200


async def test_needs_edit_permission(client):
    calls = [
        ("GET", f"{API}/cards/events", None),
        ("POST", f"{API}/cards/snapshot", {"kind": "event", "source_id": str(uuid.uuid4())}),
    ]
    for method, url, body in calls:
        res = await client.request(method, url, json=body, headers=VIEW)
        assert res.status_code == 403, url


@pytest.mark.unbound_tenant
async def test_multi_tenant_search_pins_bound_tenant():
    app, state = await build_app(multi=True)
    app.state.sm_events = SimpleNamespace()
    try:
        mine = await seed_event(state, "a", title="Open a", slug="a")
        theirs = await seed_event(state, "b", title="Open b", slug="b")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            as_a = {**EDIT, "x-tenant": "a"}
            hits = (await c.get(f"{API}/cards/events?q=open", headers=as_a)).json()
            assert [h["source_id"] for h in hits] == [str(mine)]
            res = await c.post(
                f"{API}/cards/snapshot",
                json={"kind": "event", "source_id": str(theirs)},
                headers=as_a,
            )
            assert res.status_code == 404
    finally:
        await state.engine.dispose()
