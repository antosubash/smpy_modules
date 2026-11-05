"""``/api/newsletter/cards/*``, ``/media`` and the card refresh over HTTP."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.news_seed import change_article, seed_article
from tests.support.records_seed import restrict_list, seed_list

API = constants.ROUTE_PREFIX_API
VIEW = {"x-perms": constants.PERM_VIEW}
EDIT = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT}"}


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_list(state, "default")
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _mount(app, *names: str) -> None:
    for name in names:
        setattr(app.state, name, SimpleNamespace())


async def _campaign_with_card(client, props: dict) -> dict:
    res = await client.post(
        f"{API}/campaigns", json={"name": "S", "list_type_key": "news"}, headers=EDIT
    )
    cid = res.json()["id"]
    body = [{"type": "ArticleCard", "props": props}]
    res = await client.patch(
        f"{API}/campaigns/{cid}", json={"expected_revision": 1, "body": body}, headers=EDIT
    )
    assert res.status_code == 200, res.text
    return res.json()


def _card_props(source_id: int = 1) -> dict:
    return {
        "id": "card1",
        "source_id": source_id,
        "title": "Old",
        "url": "/news/old",
        "snapshot_at": "2026-11-01T00:00:00+00:00",
    }


async def test_routes_409_when_unavailable(client):
    detail = await _campaign_with_card(client, _card_props())
    calls = [
        ("GET", f"{API}/cards/articles?q=a", None),
        ("GET", f"{API}/cards/pages?q=a", None),
        ("GET", f"{API}/media?q=a", None),
        ("POST", f"{API}/cards/snapshot", {"kind": "article", "source_id": 1}),
        ("POST", f"{API}/cards/snapshot", {"kind": "page", "source_id": 1}),
        (
            "POST",
            f"{API}/campaigns/{detail['id']}/cards/refresh",
            {"block_id": "card1", "expected_revision": detail["revision"]},
        ),
    ]
    for method, url, body in calls:
        res = await client.request(method, url, json=body, headers=EDIT)
        assert (res.status_code, res.json()["code"]) == (409, "integration_unavailable"), url


async def test_view_only_403(client, built):
    _mount(built[0], "news", "pagebuilder")
    calls = [
        ("GET", f"{API}/cards/articles", None),
        ("GET", f"{API}/cards/pages", None),
        ("GET", f"{API}/media", None),
        ("POST", f"{API}/cards/snapshot", {"kind": "article", "source_id": 1}),
        ("POST", f"{API}/campaigns/1/cards/refresh", {"block_id": "x", "expected_revision": 1}),
    ]
    for method, url, body in calls:
        res = await client.request(method, url, json=body, headers=VIEW)
        assert res.status_code == 403, url


async def test_articles_snapshot_and_refresh(client, built):
    app, state = built
    _mount(app, "news")
    aid = await seed_article(state, "default")
    hits = (await client.get(f"{API}/cards/articles?q=spring", headers=EDIT)).json()
    assert [(h["kind"], h["source_id"], h["title"]) for h in hits] == [
        ("article", aid, "Spring update")
    ]
    assert (await client.get(f"{API}/cards/articles?q=autumn", headers=EDIT)).json() == []

    res = await client.post(
        f"{API}/cards/snapshot", json={"kind": "article", "source_id": aid}, headers=EDIT
    )
    assert res.status_code == 200, res.text
    props = res.json()
    assert len(props["id"]) == 12 and props["title"] == "Spring update"
    missing = await client.post(
        f"{API}/cards/snapshot", json={"kind": "article", "source_id": aid + 99}, headers=EDIT
    )
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")
    bad = await client.post(
        f"{API}/cards/snapshot", json={"kind": "event", "source_id": 1}, headers=EDIT
    )
    assert bad.status_code == 422

    detail = await _campaign_with_card(client, props)
    cid, rev = detail["id"], detail["revision"]
    refresh = f"{API}/campaigns/{cid}/cards/refresh"
    await change_article(state, "default", aid, title="Summer update")
    res = await client.post(
        refresh, json={"block_id": props["id"], "expected_revision": rev}, headers=EDIT
    )
    assert res.status_code == 200, res.text
    assert res.json()["revision"] == rev + 1
    assert res.json()["body"][0]["props"]["title"] == "Summer update"

    stale = await client.post(
        refresh, json={"block_id": props["id"], "expected_revision": rev}, headers=EDIT
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "stale")
    nope = await client.post(
        refresh, json={"block_id": "zzz", "expected_revision": rev + 1}, headers=EDIT
    )
    assert (nope.status_code, nope.json()["code"]) == (404, "block_not_found")

    await change_article(state, "default", aid, status="draft")
    gone = await client.post(
        refresh, json={"block_id": props["id"], "expected_revision": rev + 1}, headers=EDIT
    )
    assert (gone.status_code, gone.json()["code"]) == (409, "card_source_gone")
    got = (await client.get(f"{API}/campaigns/{cid}", headers=VIEW)).json()
    assert got["revision"] == rev + 1
    assert got["body"][0]["props"]["title"] == "Summer update"

    await restrict_list(state, "default", "news", ["x"])
    hidden = await client.post(
        refresh, json={"block_id": props["id"], "expected_revision": rev + 1}, headers=EDIT
    )
    assert hidden.status_code == 404


@pytest.mark.unbound_tenant
async def test_pages_via_contract(monkeypatch):
    import pagebuilder.contracts.cards as contract

    app, state = await build_app(multi=True)
    _mount(app, "pagebuilder")
    calls: list[tuple[str, dict]] = []

    async def fake_pages(app_, session, *, tenant_id, pattern, limit=20, locale=None):
        calls.append(("pages", {"tenant_id": tenant_id, "pattern": pattern, "locale": locale}))
        return [
            contract.PageCard(
                id=4, title="About", excerpt="", image_url="", path="/p/about", locale="de"
            )
        ]

    async def fake_media(app_, session, *, tenant_id, pattern, limit=20):
        calls.append(("media", {"tenant_id": tenant_id, "pattern": pattern}))
        return [
            contract.MediaCard(id=9, filename="a.png", content_type="image/png", path="/m/a.png")
        ]

    async def fake_get(app_, session, *, tenant_id, page_id):
        calls.append(("get", {"tenant_id": tenant_id, "page_id": page_id}))
        return contract.PageCard(
            id=page_id, title="About", excerpt="", image_url="", path="/p/about", locale="de"
        )

    monkeypatch.setattr(contract, "search_page_cards", fake_pages)
    monkeypatch.setattr(contract, "search_media_cards", fake_media)
    monkeypatch.setattr(contract, "get_page_card", fake_get)
    headers = {**EDIT, "x-tenant": "acme"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            pages = await client.get(f"{API}/cards/pages?q=ab_&locale=de", headers=headers)
            media = await client.get(f"{API}/media?q=a", headers=headers)
            snap = await client.post(
                f"{API}/cards/snapshot", json={"kind": "page", "source_id": 4}, headers=headers
            )
    finally:
        await state.engine.dispose()
    assert pages.json() == [
        {
            "kind": "page",
            "source_id": 4,
            "title": "About",
            "excerpt": "",
            "image_url": "",
            "url": "/p/about",
            "locale": "de",
        }
    ]
    assert media.json() == [{"id": 9, "filename": "a.png", "url": "/m/a.png"}]
    assert snap.status_code == 200 and snap.json()["url"] == "/p/about"
    assert calls == [
        ("pages", {"tenant_id": "acme", "pattern": "%ab\\_%", "locale": "de"}),
        ("media", {"tenant_id": "acme", "pattern": "%a%"}),
        ("get", {"tenant_id": "acme", "page_id": 4}),
    ]
