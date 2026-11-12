"""The base-URL guard at client build and through each SDK (#347).

The SDK cases run a real model call through pydantic-ai and the provider SDK,
with only DNS and the socket layer faked, so they prove the pinned client is
the one each SDK actually sends with.
"""

from __future__ import annotations

import httpx2
import pytest
from pydantic_ai import Agent
from sm_ai.connections import base_url, discovery, pinned, resolve
from sm_ai.contracts.errors import AiBaseUrlRefusedError
from sm_ai.core import constants, crypto, services
from sm_ai.core.settings import AiSettings
from sm_ai.web import probe_errors

from tests.support.ai_test_stubs import fake_dns

SECRET = "test-secret-key-for-base-url"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    yield
    services.reset()


@pytest.fixture
def wire(monkeypatch):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(401, json={"error": {"message": "internal banner: host-7"}})

    monkeypatch.setattr(pinned, "_inner_transport", lambda: httpx2.MockTransport(handler))
    return seen


def _chat(provider: str, url: str, **kw) -> AiSettings:
    return AiSettings(
        chat_provider=provider,
        chat_model="m",
        chat_base_url=url,
        chat_api_key=crypto.encrypt_value("sk-secret"),
        **kw,
    )


class TestHttpClientFor:
    def test_no_base_url_uses_the_sdk_client(self):
        assert base_url.http_client_for(AiSettings(), constants.SLOT_CHAT, "") is None

    def test_a_name_gets_a_pinned_client_without_resolving(self, monkeypatch):
        asked = fake_dns(monkeypatch, {})
        client = base_url.http_client_for(AiSettings(), constants.SLOT_CHAT, "http://vllm/v1")
        assert isinstance(client._transport, pinned.PinnedTransport)
        assert asked == []  # build is synchronous: DNS waits for the request

    @pytest.mark.parametrize("url", ["http://127.0.0.1:11434/v1", "http://[::1]/v1"])
    def test_a_private_literal_is_refused_at_build(self, url):
        with pytest.raises(AiBaseUrlRefusedError) as caught:
            base_url.http_client_for(AiSettings(), constants.SLOT_CHAT, url)
        assert "allow_private_base_url" in str(caught.value)
        assert url not in str(caught.value)

    def test_allowed_private_gets_a_client_that_follows_no_redirect(self):
        settings = AiSettings(allow_private_base_url=True)
        url = "http://127.0.0.1/v1"
        client = base_url.http_client_for(settings, constants.SLOT_CHAT, url)
        assert client is not None and client.follow_redirects is False
        assert client.trust_env is True  # an egress proxy still works
        assert not isinstance(client._transport, pinned.PinnedTransport)

    def test_the_scheme_rule_holds_even_when_private_is_allowed(self):
        settings = AiSettings(allow_private_base_url=True)
        with pytest.raises(AiBaseUrlRefusedError, match="invalid_scheme"):
            base_url.http_client_for(settings, constants.SLOT_CHAT, "file:///etc/passwd")


CHAT_CASES = [
    (constants.PROVIDER_OPENAI_COMPATIBLE, "http://gw.example/v1"),
    (constants.PROVIDER_OPENAI, "https://gw.example/v1"),
    (constants.PROVIDER_ANTHROPIC, "https://gw.example"),
    (constants.PROVIDER_GOOGLE, "https://gw.example"),
]


@pytest.mark.parametrize(("provider", "url"), CHAT_CASES)
async def test_each_sdk_refuses_a_name_for_a_private_address(monkeypatch, wire, provider, url):
    fake_dns(monkeypatch, {"gw.example": ["10.0.0.7"]})
    model = resolve.build_chat_model(_chat(provider, url), max_retries=0)
    with pytest.raises(Exception) as caught:
        await Agent(model).run("hi")
    assert probe_errors.classify(caught.value).code == probe_errors.BASE_URL_REFUSED
    assert wire == []  # the key never left


@pytest.mark.parametrize(("provider", "url"), CHAT_CASES)
async def test_each_sdk_dials_the_validated_address(monkeypatch, wire, provider, url):
    fake_dns(monkeypatch, {"gw.example": ["93.184.216.34"]})
    model = resolve.build_chat_model(_chat(provider, url), max_retries=0)
    with pytest.raises(Exception) as caught:
        await Agent(model).run("hi")
    assert probe_errors.classify(caught.value) == (probe_errors.UNAUTHORISED, 401)
    assert {r.url.host for r in wire} == {"93.184.216.34"}
    assert {r.headers["host"] for r in wire} == {"gw.example"}


async def test_the_embedder_is_pinned_too(monkeypatch, wire):
    fake_dns(monkeypatch, {"emb.example": ["10.9.9.9"]})
    settings = AiSettings(
        embedding_provider=constants.PROVIDER_OPENAI_COMPATIBLE,
        embedding_model="e",
        embedding_base_url="http://emb.example/v1",
    )
    with pytest.raises(Exception) as caught:
        await resolve.build_embedder(settings).embed_query("x")
    assert probe_errors.classify(caught.value).code == probe_errors.BASE_URL_REFUSED
    assert wire == []


@pytest.mark.parametrize(("provider", "url"), CHAT_CASES)
async def test_model_listing_is_pinned(monkeypatch, wire, provider, url):
    fake_dns(monkeypatch, {"gw.example": ["10.0.0.7"]})
    with pytest.raises(Exception) as caught:
        await discovery.list_models(_chat(provider, url), constants.SLOT_CHAT)
    assert probe_errors.classify(caught.value).code == probe_errors.BASE_URL_REFUSED
    assert wire == []


class TestSaveErrors:
    async def test_private_name_refused_naming_the_setting(self, monkeypatch):
        fake_dns(monkeypatch, {"ollama": ["192.168.1.20"]})
        [error] = await base_url.save_errors({"chat_base_url": "http://ollama:11434/v1"})
        assert error["loc"] == ["body", "chat_base_url"]
        assert "allow_private_base_url" in error["msg"]
        assert error["ctx"] == {"reason": "non_public_address"}

    async def test_allowed_private_is_not_resolved(self, monkeypatch):
        asked = fake_dns(monkeypatch, {})
        merged = {"chat_base_url": "http://ollama:11434/v1", "allow_private_base_url": True}
        assert await base_url.save_errors(merged) == []
        assert asked == []

    async def test_unresolvable_refused(self, monkeypatch):
        fake_dns(monkeypatch, {})
        [error] = await base_url.save_errors({"embedding_base_url": "https://typo.example/v1"})
        assert error["ctx"] == {"reason": "unresolvable_host"}

    async def test_bad_scheme_refused_even_when_allowed(self):
        merged = {"chat_base_url": "gopher://x/", "allow_private_base_url": True}
        [error] = await base_url.save_errors(merged)
        assert error["ctx"] == {"reason": "invalid_scheme"}

    async def test_public_and_blank_pass(self, monkeypatch):
        fake_dns(monkeypatch, {"api.example": ["93.184.216.34"]})
        merged = {"chat_base_url": "https://api.example/v1", "embedding_base_url": ""}
        assert await base_url.save_errors(merged) == []
