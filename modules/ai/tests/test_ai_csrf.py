"""CSRF enforcement on the AI settings API (#126).

The check is the framework's ``RequiresCsrf``, the one billing, news, records
and pagebuilder use. The app here mounts SessionMiddleware and wires the
routers through ``AiModule.register_routes``, so the token travels the real
way: the settings screen shares it as the ``csrf_token`` Inertia prop, and the
test sends it back. The bare app in ``test_ai_api.py`` has no session, which
exercises the framework's documented no-session exemption.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from ai_test_stubs import GrantAll
from fastapi import APIRouter, FastAPI
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from simple_module_hosting.csrf import CSRF_HEADER
from simple_module_hosting.permissions import PERMISSION_DENIED_PREFIX
from simple_module_inertia import InertiaConfig, inertia_dependency_factory
from sm_ai import constants, services
from sm_ai.csrf import CSRF_PROP
from sm_ai.module import AiModule
from sm_ai.service import AiService
from sm_ai.settings import AiSettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

SECRET = "test-secret-key-for-csrf"
SETTINGS = f"{constants.ROUTE_PREFIX_API}/settings"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


class DenyWrites(BaseHTTPMiddleware):
    """Like ``GrantAll``, but the user may open the screen and not change it.

    ``ai.manage`` gates both, so the permission is granted for safe methods
    only: what matters is that a write with a real token reaches the
    permission check and is refused there.
    """

    async def dispatch(self, request, call_next):
        request.state.user = SimpleNamespace(id="u", email="u@example.com", name="U", roles=[])
        allowed = request.method in ("GET", "HEAD", "OPTIONS")
        request.state.resolved_permissions = {constants.PERM_MANAGE} if allowed else set()
        return await call_next(request)


def _app(tmp_path, auth: type[BaseHTTPMiddleware]) -> FastAPI:
    from simple_module_db.deps import get_db

    services.install(services.AiServices(settings=AiSettings()))
    app = FastAPI()
    app.add_middleware(auth)
    app.add_middleware(SessionMiddleware, secret_key=SECRET)
    app.dependency_overrides[get_db] = lambda: None
    (tmp_path / "index.html").write_text("<html></html>")
    app.state.inertia_dependency = inertia_dependency_factory(
        InertiaConfig(
            environment="development",
            version="1.0",
            dev_url="http://localhost:5050",
            templates=Jinja2Templates(directory=str(tmp_path)),
            root_template_filename="index.html",
            entrypoint_filename="main.tsx",
            root_directory=".",
        )
    )
    api = APIRouter(prefix=constants.ROUTE_PREFIX_API)
    view = APIRouter(prefix=constants.VIEW_PREFIX)
    AiModule().register_routes(api, view)
    app.include_router(api)
    app.include_router(view)
    return app


async def _client(monkeypatch, tmp_path, auth: type[BaseHTTPMiddleware]):
    """A client whose ``apply`` calls are recorded on ``client.applied``."""
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    applied: list[dict] = []

    async def _fake_apply(self, changes):
        applied.append(changes)
        return self.current()

    monkeypatch.setattr(AiService, "apply", _fake_apply)
    transport = ASGITransport(app=_app(tmp_path, auth))
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        http.applied = applied
        yield http
    services.reset()


@pytest_asyncio.fixture
async def csrf_client(monkeypatch, tmp_path):
    async for http in _client(monkeypatch, tmp_path, GrantAll):
        yield http


@pytest_asyncio.fixture
async def denied_client(monkeypatch, tmp_path):
    async for http in _client(monkeypatch, tmp_path, DenyWrites):
        yield http


async def _token_from_screen(client: AsyncClient) -> str:
    response = await client.get(constants.MENU_URL, headers=INERTIA)
    assert response.status_code == 200, response.text
    token = response.json()["props"][CSRF_PROP]
    assert token
    return token


class TestCsrf:
    async def test_put_without_token_is_refused_and_writes_nothing(self, csrf_client):
        await _token_from_screen(csrf_client)
        res = await csrf_client.put(SETTINGS, json={"chat_model": "x"})
        assert res.status_code == 403
        assert "CSRF" in res.json()["detail"]
        assert csrf_client.applied == []

    async def test_put_with_wrong_token_is_refused(self, csrf_client):
        await _token_from_screen(csrf_client)
        res = await csrf_client.put(
            SETTINGS, json={"chat_model": "x"}, headers={CSRF_HEADER: "not-the-real-token"}
        )
        assert res.status_code == 403
        assert csrf_client.applied == []

    async def test_put_with_the_screens_token_succeeds(self, csrf_client):
        token = await _token_from_screen(csrf_client)
        res = await csrf_client.put(
            SETTINGS, json={"chat_model": "claude-opus-5"}, headers={CSRF_HEADER: token}
        )
        assert res.status_code == 200, res.text
        assert csrf_client.applied and csrf_client.applied[0]["chat_model"] == "claude-opus-5"

    @pytest.mark.parametrize("path", ["test", "models"])
    async def test_slot_actions_require_the_token(self, csrf_client, path):
        await _token_from_screen(csrf_client)
        res = await csrf_client.post(
            f"{constants.ROUTE_PREFIX_API}/{path}", json={"slot": constants.SLOT_CHAT}
        )
        assert res.status_code == 403

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    async def test_safe_methods_are_not_checked(self, csrf_client, method):
        res = await csrf_client.request(method, SETTINGS)
        assert res.status_code != 403

    async def test_no_cookie_mirrors_the_token(self, csrf_client):
        res = await csrf_client.get(constants.MENU_URL, headers=INERTIA)
        names = {c.split("=", 1)[0] for c in res.headers.get_list("set-cookie")}
        assert "sm_ai_csrf" not in names


class TestTokenIsNotAPermission:
    async def test_a_valid_token_without_ai_manage_is_refused_by_the_permission_check(
        self, denied_client
    ):
        token = await _token_from_screen(denied_client)
        res = await denied_client.put(
            SETTINGS, json={"chat_model": "x"}, headers={CSRF_HEADER: token}
        )
        assert res.status_code == 403, res.text
        detail = res.json()["detail"]
        assert "CSRF" not in detail
        assert detail == f"{PERMISSION_DENIED_PREFIX}{constants.PERM_MANAGE}"
        assert denied_client.applied == []
