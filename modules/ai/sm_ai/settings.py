"""AI connection settings — DB-backed via ``register_module_settings``.

The module owns *connection* configuration (provider, endpoint, key, model
name); consuming modules own *behaviour* (agents, prompts, temperature,
retries, streaming). Two slots because real deployments run chat and
embeddings as separate endpoints (e.g. two vLLM processes on one GPU host).

Values persist in the shared settings store at SYSTEM scope and hot-swap on
save. Unset fields fall back to ``SM_AI_*`` environment variables or the root
``.env`` (the same sources the host's BootstrapSettings reads) — dev, CI and
e2e configure with zero DB rows; DB values win when present.

API keys are stored as ``enc:v1:<fernet>`` — see ``sm_ai.crypto``.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from sm_ai import constants


class AiSettings(BaseSettings):
    """Connection configuration for the chat and embedding slots."""

    model_config = SettingsConfigDict(
        env_prefix="SM_AI_", env_file=".env", extra="ignore"
    )

    # --- chat slot ---
    chat_provider: str = constants.PROVIDER_ANTHROPIC
    chat_model: str = "claude-opus-5"  # bare model name, no provider prefix
    chat_base_url: str = ""  # required for openai_compatible; optional override otherwise
    chat_api_key: str = ""

    # --- embedding slot (unconfigured by default) ---
    embedding_provider: str = ""  # "" = embeddings not configured
    embedding_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_dim: int = 0  # consumer-visible (vector stores fix width to it)
