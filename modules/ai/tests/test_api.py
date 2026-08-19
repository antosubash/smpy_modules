"""Endpoint behaviour: masking, keep-vs-replace-vs-clear, the test probe.

The app here is assembled by hand (news-conftest style): stub auth middleware
grants ai.manage, the module-global holder carries the settings, and
AiService.apply is monkeypatched to capture changes — persistence itself is
framework code with its own tests upstream.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.test import TestModel
from sm_ai import constants, crypto, services
from sm_ai.contracts.schemas import AiSettingsUpdate
from sm_ai.service import AiService
from sm_ai.settings import AiSettings
from starlette.middleware.base import BaseHTTPMiddleware

SECRET = "test-secret-key-for-api"


class _GrantAll(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.state.user = SimpleNamespace(
            id="test-user", email="t@example.com", name="T", roles=["admin"]
        )
        request.state.resolved_permissions = {constants.PERM_MANAGE}
        return await call_next(request)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    yield
    services.reset()


@pytest_asyncio.fixture
async def client(monkeypatch):
    from sm_ai.endpoints.api import router as api_router

    services.install(
        services.AiServices(
            settings=AiSettings(chat_api_key=crypto.encrypt_value("sk-stored"))
        )
    )
    applied: list[dict] = []

    async def _fake_apply(self, changes):
        applied.append(changes)
        return self.current()

    monkeypatch.setattr(AiService, "apply", _fake_apply)

    app = FastAPI()
    app.add_middleware(_GrantAll)
    # apply() is stubbed above, so no endpoint touches the session — but the
    # get_db dependency still resolves, and without a host there is no
    # app.state.sm to build one from.
    from simple_module_db.deps import get_db

    app.dependency_overrides[get_db] = lambda: None
    prefixed = APIRouter(prefix=constants.ROUTE_PREFIX_API)
    prefixed.include_router(api_router)
    app.include_router(prefixed)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        http.applied = applied
        yield http


class TestGetSettings:
    async def test_masks_secrets(self, client):
        res = await client.get("/api/ai/settings")
        assert res.status_code == 200
        body = res.json()
        assert body["has_chat_api_key"] is True
        assert "chat_api_key" not in body

    async def test_defaults_visible(self, client):
        body = (await client.get("/api/ai/settings")).json()
        assert body["chat_provider"] == constants.PROVIDER_ANTHROPIC
        assert body["embedding_provider"] == ""


class TestBuildChanges:
    def test_blank_key_keeps_stored(self):
        changes = AiService.build_changes(
            AiSettingsUpdate(chat_model="claude-opus-5", chat_api_key="")
        )
        assert changes == {"chat_model": "claude-opus-5"}

    def test_new_key_is_encrypted(self, monkeypatch):
        monkeypatch.setenv("SM_SECRET_KEY", SECRET)
        changes = AiService.build_changes(AiSettingsUpdate(chat_api_key="sk-new"))
        assert changes["chat_api_key"].startswith(crypto.ENC_PREFIX)
        assert crypto.decrypt_value(changes["chat_api_key"], "chat_api_key") == "sk-new"

    def test_clear_wins(self):
        changes = AiService.build_changes(
            AiSettingsUpdate(chat_api_key="sk-new", clear_chat_api_key=True)
        )
        assert changes["chat_api_key"] == ""

    def test_empty_update_no_changes(self):
        assert AiService.build_changes(AiSettingsUpdate()) == {}


class TestPutSettings:
    async def test_put_applies_changes(self, client):
        res = await client.put(
            "/api/ai/settings", json={"chat_model": "claude-sonnet-5"}
        )
        assert res.status_code == 200
        assert client.applied == [{"chat_model": "claude-sonnet-5"}]

    async def test_unknown_provider_rejected(self, client):
        res = await client.put("/api/ai/settings", json={"chat_provider": "watsonx"})
        assert res.status_code == 422

    async def test_noop_put_does_not_apply(self, client):
        res = await client.put("/api/ai/settings", json={})
        assert res.status_code == 200
        assert client.applied == []


class TestTestEndpoint:
    async def test_unconfigured_slot_reports_error(self, client):
        res = await client.post("/api/ai/test", json={"slot": constants.SLOT_EMBEDDING})
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is False
        assert "embedding_provider" in body["error"]

    async def test_chat_ok_with_test_model(self, client, monkeypatch):
        from sm_ai import contracts

        monkeypatch.setattr(contracts, "resolve_model", lambda model_name=None: TestModel())
        res = await client.post("/api/ai/test", json={"slot": constants.SLOT_CHAT})
        body = res.json()
        assert body["ok"] is True
        assert body["model"] == "claude-opus-5"

    async def test_unknown_slot_rejected(self, client):
        res = await client.post("/api/ai/test", json={"slot": "video"})
        assert res.status_code == 422


class TestViewPageName:
    def test_view_renders_the_settings_page_constant(self):
        # The view renders via the constant (repo linter convention); pin the
        # constant's value so the page key stays aligned with pages/Settings.tsx
        # and the manifest prefix derived from ModuleMeta.name.
        from sm_ai.endpoints import views

        source = inspect.getsource(views)
        assert "constants._PAGE_SETTINGS" in source
        assert f"{constants.MODULE_NAME}/Settings" == constants._PAGE_SETTINGS
