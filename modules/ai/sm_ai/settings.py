"""AI connection settings — DB-backed via ``register_module_settings``.

The module owns *connection* configuration (provider, endpoint, key, model
name); consuming modules own *behaviour* (agents, prompts, temperature,
retries, streaming). Two slots because real deployments run chat and
embeddings as separate endpoints (e.g. two vLLM processes on one GPU host).

No environment, ``.env`` or secrets-file sources (``DbBackedSettings``): an
``SM_AI_*`` variable is dead, so a worker started from another directory can
no longer see a different provider than the web host (#124). Configure on
``/ai/`` (which encrypts the API keys), on the Settings screen, or with
``scripts/set_setting.py``.

Values persist in the shared settings store at SYSTEM scope and hot-swap on
save: there is one provider configuration — and one API key per slot — for
the whole deployment, shared by every tenant. Nothing is read while booting,
so no field needs a restart.

API keys are stored as ``enc:v1:<fernet>`` — see ``sm_ai.crypto``.
"""

from __future__ import annotations

from pydantic import Field
from simple_module_core.settings_base import DbBackedSettings

from sm_ai import constants


class AiSettings(DbBackedSettings):
    """Connection configuration for the chat and embedding slots."""

    # --- chat slot ---
    chat_provider: str = Field(
        default=constants.PROVIDER_ANTHROPIC,
        description="Chat provider: anthropic, openai, google or openai_compatible.",
    )
    chat_model: str = Field(
        default="claude-opus-5", description="Bare model name, no provider prefix."
    )
    chat_base_url: str = Field(
        default="",
        description="Endpoint URL. Required for openai_compatible; optional override otherwise.",
    )
    chat_api_key: str = Field(
        default="", description="Provider API key. Save it on /ai/ to store it encrypted."
    )

    # --- embedding slot (unconfigured by default) ---
    embedding_provider: str = Field(
        default="",
        description=(
            "Embedding provider: openai, google or openai_compatible. Empty: not configured."
        ),
    )
    embedding_model: str = Field(default="", description="Bare embedding model name.")
    embedding_base_url: str = Field(
        default="",
        description="Endpoint URL. Required for openai_compatible; optional override otherwise.",
    )
    embedding_api_key: str = Field(
        default="", description="Provider API key. Save it on /ai/ to store it encrypted."
    )
    # Consumer-visible: vector stores fix their width to it.
    embedding_dim: int = Field(default=0, description="Embedding vector width.")
