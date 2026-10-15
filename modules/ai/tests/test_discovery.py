"""Model discovery: provider dispatch, filtering, the endpoint's result contract
and the one-line-vs-traceback logging split."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
import pytest_asyncio
from ai_test_stubs import GrantAll
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sm_ai import constants, crypto, discovery, services
from sm_ai.contracts.errors import AiNotConfiguredError
from sm_ai.settings import AiSettings

SECRET = "test-secret-key-for-discovery"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    yield
    services.reset()


def _install(**fields) -> AiSettings:
    settings = AiSettings(**fields)
    services.install(services.AiServices(settings=settings))
    return settings


@pytest_asyncio.fixture
async def client():
    from simple_module_db.deps import get_db
    from sm_ai.endpoints.api import router as api_router

    app = FastAPI()
    app.add_middleware(GrantAll)
    app.dependency_overrides[get_db] = lambda: None
    prefixed = APIRouter(prefix=constants.ROUTE_PREFIX_API)
    prefixed.include_router(api_router)
    app.include_router(prefixed)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def _aiter(items):
    for item in items:
        yield item


class TestListModels:
    async def test_openai_compatible_needs_no_key_and_sorts(self, monkeypatch):
        seen = {}

        async def fake(key, base_url):
            seen.update(key=key, base_url=base_url)
            return ["b", "a", "b", ""]

        monkeypatch.setattr(discovery, "_openai", fake)
        settings = _install(
            chat_provider="openai_compatible", chat_model="", chat_base_url="http://v/v1"
        )

        assert await discovery.list_models(settings, constants.SLOT_CHAT) == ["a", "b"]
        assert seen == {"key": constants.PLACEHOLDER_API_KEY, "base_url": "http://v/v1"}

    async def test_missing_base_url_is_not_configured(self):
        settings = _install(chat_provider="openai_compatible", chat_base_url="")
        with pytest.raises(AiNotConfiguredError):
            await discovery.list_models(settings, constants.SLOT_CHAT)

    async def test_openai_sdk_is_called_with_the_slot(self, monkeypatch):
        import openai

        made = {}

        class FakeClient:
            def __init__(self, api_key, base_url):
                made.update(api_key=api_key, base_url=base_url)
                self.models = SimpleNamespace(list=lambda: _aiter([SimpleNamespace(id="gpt-x")]))

            async def close(self):
                made["closed"] = True

        monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
        settings = _install(chat_provider="openai", chat_api_key=crypto.encrypt_value("sk-o"))

        assert await discovery.list_models(settings, constants.SLOT_CHAT) == ["gpt-x"]
        assert made == {"api_key": "sk-o", "base_url": None, "closed": True}

    @pytest.mark.parametrize(
        ("slot", "expected"),
        [(constants.SLOT_CHAT, ["gemini-pro"]), (constants.SLOT_EMBEDDING, ["text-embed"])],
    )
    async def test_google_filters_by_slot_and_strips_prefix(self, monkeypatch, slot, expected):
        from google import genai

        models = [
            SimpleNamespace(name="models/gemini-pro", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/text-embed", supported_actions=["embedContent"]),
            SimpleNamespace(name="models/odd", supported_actions=None),
        ]

        async def listing():
            return _aiter(models)

        async def _noop():
            pass

        class FakeClient:
            def __init__(self, api_key, http_options):
                self.aio = SimpleNamespace(models=SimpleNamespace(list=listing), aclose=_noop)

        monkeypatch.setattr(genai, "Client", FakeClient)
        key = crypto.encrypt_value("g")
        settings = _install(
            chat_provider="google",
            chat_api_key=key,
            embedding_provider="google",
            embedding_api_key=key,
        )
        assert await discovery.list_models(settings, slot) == expected


class TestModelsEndpoint:
    async def test_ok(self, client, monkeypatch):
        async def fake(settings, slot):
            return ["one", "two"]

        monkeypatch.setattr(discovery, "list_models", fake)
        _install()
        res = await client.post("/api/ai/models", json={"slot": constants.SLOT_CHAT})
        assert res.status_code == 200
        assert res.json() == {"ok": True, "models": ["one", "two"], "truncated": False, "error": ""}

    async def test_capped_and_says_so(self, client, monkeypatch):
        async def fake(key, base_url):
            return [f"m{i:04}" for i in range(discovery.MAX_MODELS + 50)]

        monkeypatch.setattr(discovery, "_anthropic", fake)
        _install(chat_api_key=crypto.encrypt_value("sk"))
        body = (await client.post("/api/ai/models", json={"slot": "chat"})).json()
        assert len(body["models"]) == discovery.MAX_MODELS
        assert body["truncated"] is True

    async def test_unconfigured_slot_is_a_result(self, client):
        _install()
        res = await client.post("/api/ai/models", json={"slot": constants.SLOT_EMBEDDING})
        body = res.json()
        assert res.status_code == 200
        assert body["ok"] is False
        assert "embedding_provider" in body["error"]

    async def test_timeout_is_a_result(self, client, monkeypatch):
        async def slow(settings, slot):
            await asyncio.sleep(5)

        monkeypatch.setattr(discovery, "list_models", slow)
        monkeypatch.setattr(constants, "TEST_TIMEOUT_SECONDS", 0.05)
        _install()
        body = (await client.post("/api/ai/models", json={"slot": "chat"})).json()
        assert body["ok"] is False
        assert "Timed out" in body["error"]

    async def test_unknown_slot_rejected(self, client):
        _install()
        res = await client.post("/api/ai/models", json={"slot": "video"})
        assert res.status_code == 422


class TestProbeLogging:
    async def test_config_problem_logs_one_line(self, client, caplog):
        _install()
        with caplog.at_level(logging.WARNING, logger="sm_ai.endpoints.api"):
            await client.post("/api/ai/test", json={"slot": constants.SLOT_EMBEDDING})
        [record] = caplog.records
        assert record.exc_info is None

    async def test_provider_refusal_logs_one_line(self, client, monkeypatch, caplog):
        import httpx

        async def refused(settings, slot):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(discovery, "list_models", refused)
        _install()
        with caplog.at_level(logging.WARNING, logger="sm_ai.endpoints.api"):
            body = (await client.post("/api/ai/models", json={"slot": "chat"})).json()
        assert body == {
            "ok": False,
            "models": [],
            "truncated": False,
            "error": "connection refused",
        }
        [record] = caplog.records
        assert record.exc_info is None

    async def test_wrapped_connection_error_logs_one_line(self, client, monkeypatch, caplog):
        # What a refused connection looks like from inside agent.run().
        from pydantic_ai.exceptions import ModelAPIError
        from pydantic_ai.models.function import FunctionModel
        from sm_ai import resolve

        def refused(messages, info):
            raise ModelAPIError(model_name="m", message="Connection error.")

        monkeypatch.setattr(
            resolve, "build_chat_model", lambda s, model_name=None: FunctionModel(refused)
        )
        _install()
        with caplog.at_level(logging.WARNING, logger="sm_ai.endpoints.api"):
            body = (await client.post("/api/ai/test", json={"slot": "chat"})).json()
        assert body["ok"] is False
        assert all(record.exc_info is None for record in caplog.records)

    async def test_unreadable_key_logs_one_line(self, client, monkeypatch, caplog):
        from sm_ai.contracts.errors import AiKeyUnreadableError

        async def unreadable(settings, slot):
            raise AiKeyUnreadableError("chat_api_key")

        monkeypatch.setattr(discovery, "list_models", unreadable)
        _install()
        with caplog.at_level(logging.WARNING, logger="sm_ai.endpoints.api"):
            await client.post("/api/ai/models", json={"slot": "chat"})
        [record] = caplog.records
        assert record.exc_info is None

    async def test_unexpected_error_keeps_the_traceback(self, client, monkeypatch, caplog):
        async def broken(settings, slot):
            raise AttributeError("SDK changed")

        monkeypatch.setattr(discovery, "list_models", broken)
        _install()
        with caplog.at_level(logging.WARNING, logger="sm_ai.endpoints.api"):
            await client.post("/api/ai/models", json={"slot": "chat"})
        [record] = caplog.records
        assert record.exc_info is not None
