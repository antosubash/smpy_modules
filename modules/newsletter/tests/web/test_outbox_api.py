"""``GET /api/newsletter/outbox``: the console transport's capture, per tenant."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.core import constants
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.sending.transport.console import ConsoleTransport
from sm_newsletter.sending.transport.message import OutgoingMessage

from tests.support.app import build_app as _build

URL = f"{constants.ROUTE_PREFIX_API}/outbox"
HEAD = {"x-perms": constants.PERM_MANAGE}


@pytest_asyncio.fixture
async def built():
    app, state = await _build(multi=True, settings={"transport": "console"})
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _capture(tenant: str, subject: str) -> None:
    msg = OutgoingMessage(
        to="a@example.org",
        subject=subject,
        html="<p>hi</p>",
        text="hi",
        sender="N <news@example.org>",
        reply_to=None,
        headers={},
    )
    with tenant_scope(tenant):
        async with ConsoleTransport().session() as session:
            await session.send(msg)


@pytest.mark.unbound_tenant
async def test_404_on_smtp(built):
    app, _ = built
    app.state.sm_newsletter.settings.transport = "smtp"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get(URL, headers={**HEAD, "x-tenant": "t1"})
    assert res.status_code == 404


@pytest.mark.unbound_tenant
async def test_requires_manage(client):
    res = await client.get(URL, headers={"x-perms": "newsletter.view", "x-tenant": "t1"})
    assert res.status_code == 403


@pytest.mark.unbound_tenant
async def test_lists_only_own_tenant(client):
    await _capture("t-out-1", "mine")
    await _capture("t-out-2", "theirs")
    res = await client.get(URL, headers={**HEAD, "x-tenant": "t-out-1"})
    assert res.status_code == 200, res.text
    subjects = [m["subject"] for m in res.json()]
    assert subjects == ["mine"]
    assert res.json()[0]["to"] == "a@example.org"
