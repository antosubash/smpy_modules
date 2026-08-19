"""Public surface for consuming modules.

    from sm_ai.contracts import resolve_model, resolve_embedder, embedding_dim

    agent = Agent(instructions=..., output_type=MySchema)
    result = await agent.run(text, model=resolve_model())

The base module resolves *connections*; consumers own *behaviour* —
temperature, prompts, retries and streaming belong on the consumer's Agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sm_ai.contracts.errors import AiError, AiKeyUnreadable, AiNotConfigured

if TYPE_CHECKING:
    from pydantic_ai import Embedder
    from pydantic_ai.models import Model


def resolve_model(model_name: str | None = None) -> Model:
    """A ready chat model built from the host's AI settings."""
    from sm_ai import resolve, services

    return resolve.build_chat_model(services.current_settings(), model_name)


def resolve_embedder() -> Embedder:
    """A ready ``Embedder`` built from the host's AI settings."""
    from sm_ai import resolve, services

    return resolve.build_embedder(services.current_settings())


def embedding_dim() -> int:
    """The configured embedding vector width (vector stores need it)."""
    from sm_ai import services

    dim = services.current_settings().embedding_dim
    if dim <= 0:
        raise AiNotConfigured("embedding_dim", "Set the vector width in AI settings.")
    return dim


__all__ = [
    "AiError",
    "AiKeyUnreadable",
    "AiNotConfigured",
    "embedding_dim",
    "resolve_embedder",
    "resolve_model",
]
