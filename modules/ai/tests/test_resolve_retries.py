"""``resolve_model(..., max_retries=0)``: one charge, at most one provider request.

A metered caller outside a request (images' AI steps) charges once per call,
so the provider SDK must not retry the request behind its back. Every chat
provider's client honours ``max_retries``; ``None`` keeps the SDK default.
"""

from __future__ import annotations

import pytest
from sm_ai import constants, crypto, resolve, services
from sm_ai.contracts import resolve_model

SECRET = "test-secret-key-for-retries"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    yield
    services.reset()


def _settings(provider: str, **kw):
    from sm_ai.settings import AiSettings

    return AiSettings(
        chat_provider=provider,
        chat_model="m",
        chat_api_key=crypto.encrypt_value("sk-test"),
        **kw,
    )


def _sdk_retries(model) -> int:
    client = model._provider.client if hasattr(model, "_provider") else model.client
    if hasattr(client, "max_retries"):  # openai, anthropic
        return client.max_retries
    options = client._api_client._http_options.retry_options  # google-genai
    return 0 if options is None else options.attempts - 1


CASES = [
    (constants.PROVIDER_OPENAI, {}),
    (constants.PROVIDER_OPENAI_COMPATIBLE, {"chat_base_url": "http://vllm.local/v1"}),
    (constants.PROVIDER_ANTHROPIC, {}),
    (constants.PROVIDER_GOOGLE, {}),
]


@pytest.mark.parametrize(("provider", "extra"), CASES)
def test_max_retries_reaches_the_sdk_client(provider, extra):
    model = resolve.build_chat_model(_settings(provider, **extra), max_retries=0)
    assert _sdk_retries(model) == 0


@pytest.mark.parametrize(("provider", "extra"), CASES[:3])
def test_without_it_the_sdk_default_stands(provider, extra):
    model = resolve.build_chat_model(_settings(provider, **extra))
    assert _sdk_retries(model) > 0


def test_the_contract_passes_it_through(monkeypatch):
    seen = {}

    def build(settings, model_name=None, *, max_retries=None):
        seen["max_retries"] = max_retries
        return "model"

    monkeypatch.setattr(resolve, "build_chat_model", build)
    monkeypatch.setattr(services, "current_settings", lambda: None)
    assert resolve_model(max_retries=0) == "model"
    assert seen == {"max_retries": 0}
