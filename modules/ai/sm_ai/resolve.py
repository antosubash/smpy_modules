"""Build Pydantic AI model / embedder objects from AiSettings.

Pure construction — no network I/O. Provider and auth failures surface in the
consumer's ``agent.run()`` where they belong. Objects are built per call:
construction is cheap, pydantic-ai's shared HTTP client keeps pooling, and a
settings save applies on the very next call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sm_ai import constants, crypto
from sm_ai.contracts.errors import AiNotConfiguredError

if TYPE_CHECKING:
    from pydantic_ai import Embedder
    from pydantic_ai.models import Model

    from sm_ai.settings import AiSettings


def slot_inputs(
    settings: AiSettings,
    slot: str,
    allowed: tuple[str, ...],
    model_override: str | None = None,
    *,
    require_model: bool = True,
) -> tuple[str, str, str, str]:
    """Validate one slot's settings; returns (provider_id, model, key, base_url).

    The single validation path for both slots — provider membership, model
    presence, key decryption, and the openai_compatible base_url requirement
    (with the placeholder-key substitution) live here once.
    """
    provider_id = getattr(settings, f"{slot}_provider").strip().lower()
    if not provider_id and slot == constants.SLOT_EMBEDDING:
        raise AiNotConfiguredError("embedding_provider", "The embedding slot is not configured.")
    if provider_id not in allowed:
        hint = (
            "Anthropic does not offer an embeddings API."
            if slot == constants.SLOT_EMBEDDING and provider_id == constants.PROVIDER_ANTHROPIC
            else f"Unknown provider {provider_id!r}; expected one of {', '.join(allowed)}."
        )
        raise AiNotConfiguredError(f"{slot}_provider", hint)
    model = (model_override or getattr(settings, f"{slot}_model")).strip()
    # Discovery asks precisely because the model is missing or unknown.
    if not model and require_model:
        raise AiNotConfiguredError(f"{slot}_model")

    key = crypto.decrypt_value(getattr(settings, f"{slot}_api_key"), f"{slot}_api_key")
    base_url = getattr(settings, f"{slot}_base_url").strip()

    if provider_id == constants.PROVIDER_OPENAI_COMPATIBLE:
        if not base_url:
            raise AiNotConfiguredError(
                f"{slot}_base_url",
                "The openai_compatible provider needs the server's /v1 URL.",
            )
        # vLLM and friends ignore the key but the protocol wants a value.
        key = key or constants.PLACEHOLDER_API_KEY
    elif not key:
        raise AiNotConfiguredError(f"{slot}_api_key")
    return provider_id, model, key, base_url


def build_chat_model(
    settings: AiSettings, model_name: str | None = None, *, max_retries: int | None = None
) -> Model:
    """A ready chat model for the configured provider.

    ``model_name`` overrides the configured name for same-endpoint
    multi-model setups (e.g. a vision and a text model on one vLLM server).
    ``max_retries`` sets the provider SDK's own transport retries (``None``:
    the SDK default). A caller that meters each call passes ``0``, so one
    charge is at most one provider request.
    """
    provider_id, name, key, base_url = slot_inputs(
        settings, constants.SLOT_CHAT, constants.CHAT_PROVIDERS, model_name
    )

    if provider_id in (constants.PROVIDER_OPENAI, constants.PROVIDER_OPENAI_COMPATIBLE):
        return _openai_chat(name, base_url, key, max_retries)

    if provider_id == constants.PROVIDER_ANTHROPIC:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        kwargs = {"base_url": base_url} if base_url else {}
        provider = AnthropicProvider(api_key=key, **kwargs)
        if max_retries is not None:
            client = provider.client.with_options(max_retries=max_retries)
            provider = AnthropicProvider(anthropic_client=client)
        return AnthropicModel(name, provider=provider)

    # google — GoogleProvider wires base_url into the genai client's
    # http_options, so a gateway override routes exactly like the other
    # providers' plain kwarg.
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    kwargs: dict = {"base_url": base_url} if base_url else {}
    if max_retries is not None:  # genai counts attempts, the first included
        from google.genai.types import HttpRetryOptions

        kwargs["retry_options"] = HttpRetryOptions(attempts=max_retries + 1)
    return GoogleModel(name, provider=GoogleProvider(api_key=key, **kwargs))


def _openai_chat(name: str, base_url: str, key: str, max_retries: int | None = None) -> Model:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    kwargs = {"base_url": base_url} if base_url else {}
    provider = OpenAIProvider(api_key=key, **kwargs)
    if max_retries is not None:  # a copy sharing the pooled HTTP client
        provider = OpenAIProvider(
            openai_client=provider.client.with_options(max_retries=max_retries)
        )
    return OpenAIChatModel(name, provider=provider)


def build_embedder(settings: AiSettings) -> Embedder:
    """A ready ``Embedder`` for the configured embedding slot."""
    from pydantic_ai import Embedder

    provider_id, name, key, base_url = slot_inputs(
        settings, constants.SLOT_EMBEDDING, constants.EMBEDDING_PROVIDERS
    )

    if provider_id in (constants.PROVIDER_OPENAI, constants.PROVIDER_OPENAI_COMPATIBLE):
        return Embedder(_openai_embedding(name, base_url, key))

    from pydantic_ai.embeddings.google import GoogleEmbeddingModel
    from pydantic_ai.providers.google import GoogleProvider

    kwargs = {"base_url": base_url} if base_url else {}
    return Embedder(GoogleEmbeddingModel(name, provider=GoogleProvider(api_key=key, **kwargs)))


def _openai_embedding(name: str, base_url: str, key: str):
    from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
    from pydantic_ai.providers.openai import OpenAIProvider

    kwargs = {"base_url": base_url} if base_url else {}
    return OpenAIEmbeddingModel(name, provider=OpenAIProvider(api_key=key, **kwargs))
