"""The one 404: pagebuilder's when it is mounted, events' own page otherwise."""

from __future__ import annotations

from fastapi import Response
from sm_events.integrations import pagebuilder
from sqlalchemy import event

from tests.support.public import INERTIA


async def test_without_pagebuilder(public_client):
    got = await public_client.get("/events/nope", headers=INERTIA)
    assert got.status_code == 404
    body = got.json()
    assert body["component"] == "Events/PublicNotFound"
    assert body["props"]["locale"] == "en"
    assert body["props"]["index_url"] == "/events/"
    assert body["props"]["suggestions"] == []
    assert got.headers["cache-control"] == "no-store"
    assert "etag" not in got.headers


async def test_html_visit_renders_the_page(public_client):
    got = await public_client.get("/events/nope")
    assert got.status_code == 404
    assert got.headers["content-type"].startswith("text/html")
    assert "Events/PublicNotFound" in got.text
    assert got.headers["cache-control"] == "no-store"


async def test_other_language_gets_its_own_index_link(public_locales_client):
    got = await public_locales_client.get("/de/events/nope", headers=INERTIA)
    assert got.status_code == 404
    assert got.json()["props"]["locale"] == "de"
    assert got.json()["props"]["index_url"] == "/de/events/"


async def test_with_pagebuilder_contract(public_client, monkeypatch):
    seen: dict = {}

    async def site_404(request, inertia, db, *, locale, tenant_id, detail):
        seen.update(locale=locale, tenant_id=tenant_id, detail=detail)
        return Response("the site's 404", status_code=404)

    monkeypatch.setattr(pagebuilder, "render_not_found", site_404)
    got = await public_client.get("/events/nope")
    assert (got.status_code, got.text) == (404, "the site's 404")
    assert seen == {"locale": "en", "tenant_id": "default", "detail": "Not found"}
    assert got.headers["cache-control"] == "no-store"  # whoever rendered it


async def test_pagebuilder_not_installed_is_ours(public_client, monkeypatch):
    monkeypatch.setattr(pagebuilder, "available", lambda: False)
    got = await public_client.get("/events/nope", headers=INERTIA)
    assert got.json()["component"] == "Events/PublicNotFound"


async def test_pagebuilder_without_the_contract_is_ours(public_client, monkeypatch):
    monkeypatch.setattr(pagebuilder, "_public", lambda: None)
    got = await public_client.get("/events/nope", headers=INERTIA)
    assert got.json()["component"] == "Events/PublicNotFound"


def _forbid_statements(client) -> list[str]:
    ran: list[str] = []

    def record(conn, cursor, statement, *_):
        ran.append(statement)

    event.listen(client.db_state.engine.sync_engine, "before_cursor_execute", record)
    return ran


async def test_the_statement_recorder_sees_a_query(public_client):
    """Control for the next test: the recorder does record when something runs."""
    from sqlalchemy import text

    ran = _forbid_statements(public_client)
    async with public_client.db_state.session_factory() as session:
        await session.execute(text("SELECT 1"))
    assert ran


async def test_no_tenant_no_query(public_multi_client):
    ran = _forbid_statements(public_multi_client)
    for path in ("/de/events/nope", "/events/nope", "/events/", "/events/c/x"):
        got = await public_multi_client.get(path, headers=INERTIA)
        assert got.status_code == 404, path
        assert got.json()["component"] == "Events/PublicNotFound"
        assert got.json()["props"]["suggestions"] == []
    assert ran == []


async def test_with_a_tenant_the_page_is_the_same_404(public_multi_client):
    none = await public_multi_client.get("/events/nope", headers=INERTIA)
    acme = await public_multi_client.get(
        "/events/nope", headers=INERTIA | {"X-Test-Tenant": "acme"}
    )
    assert acme.status_code == none.status_code == 404
    assert acme.json()["props"] == none.json()["props"]
    assert acme.headers["cache-control"] == none.headers["cache-control"] == "no-store"
