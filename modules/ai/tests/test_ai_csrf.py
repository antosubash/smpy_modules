"""CSRF enforcement on the AI settings API.

The app here mounts SessionMiddleware + CsrfCookieMiddleware and wires the
routers exactly as ``AiModule.register_routes`` does, so this covers the
mint → cookie-mirror → verify chain end to end. The bare app used in
``test_api.py`` has no session, which exercises the documented skip path.
"""

from __future__ import annotations

import pytest_asyncio
from ai_test_stubs import GrantAll
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sm_ai import constants, services
from sm_ai.security import CsrfCookieMiddleware, mint_csrf_token, verify_csrf
from sm_ai.service import AiService
from sm_ai.settings import AiSettings
from starlette.middleware.sessions import SessionMiddleware

SECRET = "test-secret-key-for-csrf"


@pytest_asyncio.fixture
async def csrf_client(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    from simple_module_db.deps import get_db
    from sm_ai.endpoints.api import router as api_router

    services.install(services.AiServices(settings=AiSettings()))

    async def _fake_apply(self, changes):
        return self.current()

    monkeypatch.setattr(AiService, "apply", _fake_apply)

    app = FastAPI()
    # Middleware runs bottom-up: session first, then the cookie mirror, then auth.
    app.add_middleware(GrantAll)
    app.add_middleware(CsrfCookieMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=SECRET)
    app.dependency_overrides[get_db] = lambda: None

    api = APIRouter(prefix=constants.ROUTE_PREFIX_API)
    api.include_router(api_router, dependencies=[Depends(verify_csrf)])
    app.include_router(api)

    view = APIRouter(prefix=constants.VIEW_PREFIX, dependencies=[Depends(mint_csrf_token)])

    @view.get("/")
    async def admin_view() -> dict:  # stands in for the Inertia page render
        return {}

    app.include_router(view)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    services.reset()


async def _bootstrap_csrf(client: AsyncClient) -> str:
    """Hit the admin view so the token is minted + mirrored; return it."""
    response = await client.get(constants.MENU_URL)
    assert response.status_code == 200
    token = response.cookies.get(constants.CSRF_COOKIE)
    assert token, "CSRF cookie not set by admin view"
    return token


class TestCsrf:
    async def test_put_without_token_returns_403(self, csrf_client):
        await _bootstrap_csrf(csrf_client)
        res = await csrf_client.put(
            f"{constants.ROUTE_PREFIX_API}/settings", json={"chat_model": "x"}
        )
        assert res.status_code == 403

    async def test_put_with_wrong_token_returns_403(self, csrf_client):
        await _bootstrap_csrf(csrf_client)
        res = await csrf_client.put(
            f"{constants.ROUTE_PREFIX_API}/settings",
            json={"chat_model": "x"},
            headers={"X-CSRF-Token": "not-the-real-token"},
        )
        assert res.status_code == 403

    async def test_put_with_valid_token_succeeds(self, csrf_client):
        token = await _bootstrap_csrf(csrf_client)
        res = await csrf_client.put(
            f"{constants.ROUTE_PREFIX_API}/settings",
            json={"chat_model": "claude-opus-5"},
            headers={"X-CSRF-Token": token},
        )
        assert res.status_code == 200

    async def test_test_endpoint_requires_token(self, csrf_client):
        await _bootstrap_csrf(csrf_client)
        res = await csrf_client.post(
            f"{constants.ROUTE_PREFIX_API}/test", json={"slot": constants.SLOT_CHAT}
        )
        assert res.status_code == 403

    async def test_safe_methods_skip_csrf(self, csrf_client):
        await _bootstrap_csrf(csrf_client)
        res = await csrf_client.get(f"{constants.ROUTE_PREFIX_API}/settings")
        assert res.status_code == 200
