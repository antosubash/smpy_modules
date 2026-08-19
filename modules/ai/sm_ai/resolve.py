"""Build Pydantic AI model / embedder objects from AiSettings.

Pure construction — no network I/O. Provider and auth failures surface in the
consumer's ``agent.run()`` where they belong. Objects are built per call:
construction is cheap, pydantic-ai's shared HTTP client keeps pooling, and a
settings save applies on the very next call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sm_ai import constants, crypto
from sm_ai.contracts.errors import AiNotConfiguredError

if TYPE_CHECKING:
    from pydantic_ai import Embedder
    from pydantic_ai.models import Model

    from sm_ai.settings import AiSettings

logger = logging.getLogger(__name__)


def build_chat_model(settings: AiSettings, model_name: str | None = None) -> Model:
    """A ready chat model for the configured provider.

    ``model_name`` overrides the configured name for same-endpoint
    multi-model setups (e.g. a vision and a text model on one vLLM server).
    """
    provider_id = settings.chat_provider.strip().lower()
    name = (model_name or settings.chat_model).strip()
    if provider_id not in constants.CHAT_PROVIDERS:
        raise AiNotConfiguredError(
            "chat_provider",
            f"Unknown provider {provider_id!r}; expected one of "
            f"{', '.join(constants.CHAT_PROVIDERS)}.",
        )
    if not name:
        raise AiNotConfiguredError("chat_model")

    key = crypto.decrypt_value(settings.chat_api_key, "chat_api_key")
    base_url = settings.chat_base_url.strip()

    if provider_id == constants.PROVIDER_OPENAI_COMPATIBLE:
        if not base_url:
            raise AiNotConfiguredError(
                "chat_base_url",
                "The openai_compatible provider needs the server's /v1 URL.",
            )
        return _openai_chat(name, base_url, key or constants.PLACEHOLDER_API_KEY)

    if not key:
        raise AiNotConfiguredError("chat_api_key")

    if provider_id == constants.PROVIDER_ANTHROPIC:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        kwargs = {"base_url": base_url} if base_url else {}
        return AnthropicModel(name, provider=AnthropicProvider(api_key=key, **kwargs))

    if provider_id == constants.PROVIDER_OPENAI:
        return _openai_chat(name, base_url, key)

    # google — the genai client has no plain base_url knob; ignore with a
    # warning rather than fail a working configuration.
    if base_url:
        logger.warning("chat_base_url is ignored for the google provider.")
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    return GoogleModel(name, provider=GoogleProvider(api_key=key))


def _openai_chat(name: str, base_url: str, key: str) -> Model:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    kwargs = {"base_url": base_url} if base_url else {}
    return OpenAIChatModel(name, provider=OpenAIProvider(api_key=key, **kwargs))


def build_embedder(settings: AiSettings) -> Embedder:
    """A ready ``Embedder`` for the configured embedding slot."""
    from pydantic_ai import Embedder

    provider_id = settings.embedding_provider.strip().lower()
    name = settings.embedding_model.strip()
    if not provider_id:
        raise AiNotConfiguredError(
            "embedding_provider", "The embedding slot is not configured."
        )
    if provider_id not in constants.EMBEDDING_PROVIDERS:
        hint = (
            "Anthropic does not offer an embeddings API."
            if provider_id == constants.PROVIDER_ANTHROPIC
            else f"Expected one of {', '.join(constants.EMBEDDING_PROVIDERS)}."
        )
        raise AiNotConfiguredError("embedding_provider", hint)
    if not name:
        raise AiNotConfiguredError("embedding_model")

    key = crypto.decrypt_value(settings.embedding_api_key, "embedding_api_key")
    base_url = settings.embedding_base_url.strip()

    if provider_id == constants.PROVIDER_OPENAI_COMPATIBLE:
        if not base_url:
            raise AiNotConfiguredError(
                "embedding_base_url",
                "The openai_compatible provider needs the server's /v1 URL.",
            )
        return Embedder(
            _openai_embedding(name, base_url, key or constants.PLACEHOLDER_API_KEY)
        )

    if not key:
        raise AiNotConfiguredError("embedding_api_key")

    if provider_id == constants.PROVIDER_OPENAI:
        return Embedder(_openai_embedding(name, base_url, key))

    if base_url:
        logger.warning("embedding_base_url is ignored for the google provider.")
    from pydantic_ai.embeddings.google import GoogleEmbeddingModel
    from pydantic_ai.providers.google import GoogleProvider

    return Embedder(GoogleEmbeddingModel(name, provider=GoogleProvider(api_key=key)))


def _openai_embedding(name: str, base_url: str, key: str):
    from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
    from pydantic_ai.providers.openai import OpenAIProvider

    kwargs = {"base_url": base_url} if base_url else {}
    return OpenAIEmbeddingModel(name, provider=OpenAIProvider(api_key=key, **kwargs))
