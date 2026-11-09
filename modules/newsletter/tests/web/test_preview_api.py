"""``GET /campaigns/{id}/preview`` and ``POST /preview`` over HTTP."""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.context import render_context, test_unsubscribe_url
from sm_newsletter.content.render import RenderInput, personalise, render
from sm_newsletter.core import constants

from tests.support.app import build_app
from tests.support.records_seed import restrict_list, seed_list

API = constants.ROUTE_PREFIX_API
VIEW = {"x-perms": constants.PERM_VIEW}
EDIT = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT}"}
BODY = [{"type": "Divider", "props": {"id": "a"}}]


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


async def _draft(client) -> int:
    res = await client.post(
        f"{API}/campaigns",
        json={"name": "n", "list_type_key": "news", "subject": "Hi", "preheader": "pre"},
        headers=EDIT,
    )
    cid = res.json()["id"]
    patch = {"expected_revision": 1, "body": BODY}
    assert (
        await client.patch(f"{API}/campaigns/{cid}", json=patch, headers=EDIT)
    ).status_code == 200
    return cid


async def test_preview_saved_matches_render(client, built):
    app, _ = built
    app.state.sm.settings.public_base_url = "https://news.example.org"
    cid = await _draft(client)
    res = await client.get(f"{API}/campaigns/{cid}/preview", headers=VIEW)
    assert res.status_code == 200, res.text
    ctx = await render_context(app, tenant_id="default")
    tpl = render(RenderInput("Hi", "pre", parse_body(BODY)), ctx)
    mail = personalise(tpl, first_name=None, unsubscribe_url=test_unsubscribe_url(ctx.public_base))
    assert res.json() == {
        "subject": mail.subject,
        "html": mail.html,
        "text": mail.text,
        "warnings": list(tpl.warnings),
    }
    unsub = "https://news.example.org/newsletter/u/test"
    for part in (res.json()["html"], res.json()["text"]):
        assert unsub in part
        # Every occurrence of the test path is the absolute one, never relative.
        assert part.count("/newsletter/u/test") == part.count(unsub)


async def test_preview_unsaved_validates_body(client):
    bad = await client.post(f"{API}/preview", json={"body": [{"type": "Nope"}]}, headers=EDIT)
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_body")
    ok = await client.post(
        f"{API}/preview", json={"subject": "S", "preheader": "p", "body": BODY}, headers=EDIT
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["subject"] == "S"
    hdr = await client.post(f"{API}/preview", json={"subject": "a\nb"}, headers=EDIT)
    assert hdr.status_code == 422
    assert "a\nb" not in hdr.text
    for field in ("subject", "preheader"):
        merge = await client.post(f"{API}/preview", json={field: "{{firstname}}"}, headers=EDIT)
        assert merge.status_code == 422
        assert field in merge.json()["detail"] and "firstname" not in merge.text


async def test_preview_warns_relative_without_base(client):
    res = await client.post(f"{API}/preview", json={"body": BODY}, headers=EDIT)
    assert "relative_urls" in res.json()["warnings"]


async def test_preview_permission(client):
    cid = await _draft(client)
    assert (await client.get(f"{API}/campaigns/{cid}/preview", headers=VIEW)).status_code == 200
    assert (await client.post(f"{API}/preview", json={}, headers=VIEW)).status_code == 403
    assert (await client.get(f"{API}/campaigns/{cid}/preview")).status_code in (401, 403)


async def test_restricted_list_preview_is_404(client, built):
    _, state = built
    cid = await _draft(client)
    await restrict_list(state, "default", "news", ["x"])
    assert (await client.get(f"{API}/campaigns/{cid}/preview", headers=VIEW)).status_code == 404
    allowed = {**VIEW, "x-roles": "x"}
    assert (await client.get(f"{API}/campaigns/{cid}/preview", headers=allowed)).status_code == 200
