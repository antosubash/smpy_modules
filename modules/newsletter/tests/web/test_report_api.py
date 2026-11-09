"""``GET /campaigns/{id}/report`` over HTTP (T14, C4)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants
from sm_newsletter.web.schemas.report import ReportOut

from tests.support.app import build_app
from tests.support.campaign_world import seed_campaign
from tests.support.records_seed import restrict_list, seed_list
from tests.support.sending import NOW
from tests.support.tracking_world import sent_campaign

API = f"{constants.ROUTE_PREFIX_API}/campaigns"
VIEW = {"x-perms": constants.PERM_VIEW}
T = "default"


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_list(state, T)
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_report_200_with_the_schema_keys(client, built):
    _, state = built
    cid, _ = await sent_campaign(state, links=("https://e.org/a", "https://e.org/b"))
    res = await client.get(f"{API}/{cid}/report", headers=VIEW)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == set(ReportOut.model_fields)
    assert [link["position"] for link in body["links"]] == [1, 2]
    assert body["campaign_id"] == cid and body["timeline"] == []


async def test_report_needs_view_permission(client, built):
    _, state = built
    cid, _ = await sent_campaign(state)
    assert (await client.get(f"{API}/{cid}/report")).status_code == 403


async def test_report_unknown_id_404(client):
    res = await client.get(f"{API}/9999/report", headers=VIEW)
    assert (res.status_code, res.json()["code"]) == (404, "not_found")


async def test_report_on_a_restricted_list_404(client, built):
    _, state = built
    cid, _ = await sent_campaign(state)
    await restrict_list(state, T, "news", ["x"])
    assert (await client.get(f"{API}/{cid}/report", headers=VIEW)).status_code == 404
    allowed = {**VIEW, "x-roles": "x"}
    assert (await client.get(f"{API}/{cid}/report", headers=allowed)).status_code == 200


async def test_report_tracking_flags_follow_settings():
    app, state = await build_app(settings={"tracking_opens": False})
    try:
        await seed_list(state, T)
        cid = await seed_campaign(state, T, status="sent", started_at=NOW)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            body = (await c.get(f"{API}/{cid}/report", headers=VIEW)).json()
    finally:
        await state.engine.dispose()
    assert (body["tracking_opens"], body["tracking_clicks"]) == (False, True)


@pytest.mark.unbound_tenant
async def test_report_of_another_tenant_404():
    app, state = await build_app(multi=True)
    try:
        await seed_list(state, "a")
        await seed_list(state, "b")
        cid, _ = await sent_campaign(state, "b")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            in_a = await c.get(f"{API}/{cid}/report", headers={**VIEW, "x-tenant": "a"})
            in_b = await c.get(f"{API}/{cid}/report", headers={**VIEW, "x-tenant": "b"})
    finally:
        await state.engine.dispose()
    assert in_a.status_code == 404
    assert in_b.status_code == 200
