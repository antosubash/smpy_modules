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


# --- POST /outbox/dispatch: the development and e2e dispatch hook (R17) ---------------

from simple_module_hosting.csrf import CSRF_HEADER  # noqa: E402
from sm_newsletter.web.endpoints import outbox_api  # noqa: E402

from tests.support.dispatch_world import due  # noqa: E402
from tests.support.sending import make_app  # noqa: E402

DISPATCH = f"{constants.ROUTE_PREFIX_API}/outbox/dispatch"
PROGRESS = f"{constants.ROUTE_PREFIX_API}/campaigns"
VIEW_MANAGE = {"x-perms": f"{constants.PERM_MANAGE},{constants.PERM_VIEW}"}


@pytest.fixture
def eager(monkeypatch):
    def set_(value: bool) -> None:
        monkeypatch.setattr(outbox_api, "celery_eager", lambda: value)

    set_(True)
    return set_


async def _hook_app(tmp_path, *, transport="console", environment="testing", session=False):
    app, state, _ = await make_app(file=tmp_path / "hook.db", transport=transport)
    app.state.sm.settings.environment = environment
    return app, state


@pytest.mark.unbound_tenant
@pytest.mark.parametrize(
    ("transport", "is_eager", "environment", "status"),
    [
        ("smtp", True, "testing", 404),
        ("console", False, "testing", 404),
        ("console", True, "production", 404),
        ("console", True, "staging", 404),
        ("console", True, "development", 200),
        ("console", True, "testing", 200),
    ],
)
async def test_dispatch_404_unless_all_conditions(
    tmp_path, eager, transport, is_eager, environment, status
):
    eager(is_eager)
    app, state = await _hook_app(tmp_path, transport=transport, environment=environment)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            res = await c.post(DISPATCH, headers=HEAD)
        assert res.status_code == status, res.text
        if status == 200:
            assert set(res.json()) == {"started", "spent", "finished", "stopped"}
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_dispatch_404_without_a_host_environment(tmp_path, eager):
    app, state = await _hook_app(tmp_path)
    del app.state.sm.settings.environment  # fails closed
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.post(DISPATCH, headers=HEAD)).status_code == 404
    finally:
        await state.engine.dispose()


async def test_dispatch_requires_csrf(eager):
    app, state = await _build(session=True, settings={"transport": "console"})
    app.state.sm.settings.environment = "testing"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            token = (await c.get("/token")).json()["token"]
            assert (await c.post(DISPATCH, headers=HEAD)).status_code == 403
            ok = await c.post(DISPATCH, headers={**HEAD, CSRF_HEADER: token})
            assert ok.status_code == 200, ok.text
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_dispatch_needs_manage(tmp_path, eager):
    app, state = await _hook_app(tmp_path)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            res = await c.post(DISPATCH, headers={"x-perms": constants.PERM_SEND})
        assert res.status_code == 403
    finally:
        await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_dispatch_sends_a_due_campaign(tmp_path, eager):
    app, state = await _hook_app(tmp_path)
    try:
        cid, emails = await due(state, 2)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            for _ in range(2):
                res = await c.post(DISPATCH, headers=HEAD)
                assert res.status_code == 200, res.text
            box = (await c.get(URL, headers=HEAD)).json()
            assert sorted(m["to"] for m in box) == sorted(emails)
            progress = (await c.get(f"{PROGRESS}/{cid}/progress", headers=VIEW_MANAGE)).json()
        assert progress["sent"] == 2, progress
    finally:
        await state.engine.dispose()
