"""Per-provider model construction — pure, zero network."""

from __future__ import annotations

import pytest
from pydantic_ai import Embedder
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from sm_ai import constants, crypto, resolve, services
from sm_ai.contracts import embedding_dim, resolve_model
from sm_ai.contracts.errors import AiNotConfiguredError
from sm_ai.settings import AiSettings

SECRET = "test-secret-key-for-resolve"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    # Keep host env out of these constructions.
    for var in ("SM_AI_CHAT_PROVIDER", "SM_AI_CHAT_MODEL", "SM_AI_CHAT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield
    services.reset()


def _chat(**kw) -> AiSettings:
    base = {
        "chat_provider": constants.PROVIDER_ANTHROPIC,
        "chat_model": "claude-opus-5",
        "chat_api_key": crypto.encrypt_value("sk-test"),
    }
    base.update(kw)
    return AiSettings(**base)


class TestChatProviders:
    def test_anthropic(self):
        model = resolve.build_chat_model(_chat())
        assert isinstance(model, AnthropicModel)
        assert model.model_name == "claude-opus-5"

    def test_openai(self):
        model = resolve.build_chat_model(
            _chat(chat_provider=constants.PROVIDER_OPENAI, chat_model="gpt-5.2")
        )
        assert isinstance(model, OpenAIChatModel)

    def test_google(self):
        model = resolve.build_chat_model(
            _chat(chat_provider=constants.PROVIDER_GOOGLE, chat_model="gemini-3-pro")
        )
        assert isinstance(model, GoogleModel)

    def test_openai_compatible_with_base_url(self):
        model = resolve.build_chat_model(
            _chat(
                chat_provider=constants.PROVIDER_OPENAI_COMPATIBLE,
                chat_model="Qwen/Qwen3.6-35B-A3B-FP8",
                chat_base_url="http://vllm.example:8000/v1",
                chat_api_key="",
            )
        )
        assert isinstance(model, OpenAIChatModel)

    def test_model_name_override(self):
        model = resolve.build_chat_model(_chat(), model_name="claude-haiku-4-5")
        assert model.model_name == "claude-haiku-4-5"


class TestChatErrors:
    def test_unknown_provider(self):
        with pytest.raises(AiNotConfiguredError) as exc:
            resolve.build_chat_model(_chat(chat_provider="watsonx"))
        assert exc.value.field == "chat_provider"

    def test_empty_model(self):
        with pytest.raises(AiNotConfiguredError) as exc:
            resolve.build_chat_model(_chat(chat_model=""))
        assert exc.value.field == "chat_model"

    def test_missing_key_for_hosted_provider(self):
        with pytest.raises(AiNotConfiguredError) as exc:
            resolve.build_chat_model(_chat(chat_api_key=""))
        assert exc.value.field == "chat_api_key"

    def test_openai_compatible_needs_base_url(self):
        with pytest.raises(AiNotConfiguredError) as exc:
            resolve.build_chat_model(
                _chat(chat_provider=constants.PROVIDER_OPENAI_COMPATIBLE, chat_base_url="")
            )
        assert exc.value.field == "chat_base_url"


def _embed(**kw) -> AiSettings:
    base = {
        "embedding_provider": constants.PROVIDER_OPENAI_COMPATIBLE,
        "embedding_model": "qwen3-embedding-8b",
        "embedding_base_url": "http://vllm.example:8001/v1",
        "embedding_dim": 4096,
    }
    base.update(kw)
    return AiSettings(**base)


class TestEmbeddings:
    def test_openai_compatible(self):
        assert isinstance(resolve.build_embedder(_embed()), Embedder)

    def test_openai(self):
        embedder = resolve.build_embedder(
            _embed(
                embedding_provider=constants.PROVIDER_OPENAI,
                embedding_model="text-embedding-3-small",
                embedding_api_key=crypto.encrypt_value("sk-test"),
                embedding_base_url="",
            )
        )
        assert isinstance(embedder, Embedder)

    def test_unconfigured(self):
        with pytest.raises(AiNotConfiguredError) as exc:
            resolve.build_embedder(_embed(embedding_provider=""))
        assert exc.value.field == "embedding_provider"

    def test_anthropic_unsupported(self):
        with pytest.raises(AiNotConfiguredError) as exc:
            resolve.build_embedder(_embed(embedding_provider=constants.PROVIDER_ANTHROPIC))
        assert exc.value.field == "embedding_provider"


class TestContractsFacade:
    def test_resolve_model_reads_holder(self):
        services.install(services.AiServices(settings=_chat()))
        assert isinstance(resolve_model(), AnthropicModel)

    def test_embedding_dim(self):
        services.install(services.AiServices(settings=_embed()))
        assert embedding_dim() == 4096

    def test_embedding_dim_unset_raises(self):
        services.install(services.AiServices(settings=_embed(embedding_dim=0)))
        with pytest.raises(AiNotConfiguredError):
            embedding_dim()
