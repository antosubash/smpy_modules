"""DTOs for the AI settings API. Secrets never travel outward — reads carry
``has_*_api_key`` booleans; writes treat blank as "keep" and ``clear_*`` as
explicit removal."""

from __future__ import annotations

from pydantic import field_validator
from sqlmodel import SQLModel

from sm_ai import constants


class AiSettingsOut(SQLModel):
    """Current AI settings with secrets reduced to presence flags.

    Carries the allowed provider ids so the settings page renders its
    dropdowns from the same tuples the validators enforce — the frontend
    holds no provider list of its own.
    """

    chat_providers: list[str] = list(constants.CHAT_PROVIDERS)
    embedding_providers: list[str] = list(constants.EMBEDDING_PROVIDERS)
    chat_provider: str
    chat_model: str
    chat_base_url: str
    has_chat_api_key: bool
    embedding_provider: str
    embedding_model: str
    embedding_base_url: str
    has_embedding_api_key: bool
    embedding_dim: int


class AiSettingsUpdate(SQLModel):
    """Partial update. Key fields: blank/omitted = keep the stored key."""

    chat_provider: str | None = None
    chat_model: str | None = None
    chat_base_url: str | None = None
    chat_api_key: str | None = None
    clear_chat_api_key: bool = False
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    clear_embedding_api_key: bool = False
    embedding_dim: int | None = None

    @field_validator("chat_provider")
    @classmethod
    def _chat_provider_known(cls, value: str | None) -> str | None:
        if value is not None and value not in constants.CHAT_PROVIDERS:
            raise ValueError(f"chat_provider must be one of {constants.CHAT_PROVIDERS}")
        return value

    @field_validator("embedding_provider")
    @classmethod
    def _embedding_provider_known(cls, value: str | None) -> str | None:
        if value is not None and value != "" and value not in constants.EMBEDDING_PROVIDERS:
            raise ValueError(
                f"embedding_provider must be empty or one of {constants.EMBEDDING_PROVIDERS}"
            )
        return value

    @field_validator("embedding_dim")
    @classmethod
    def _dim_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("embedding_dim must be >= 0")
        return value


class AiTestRequest(SQLModel):
    """Which slot to test."""

    slot: str

    @field_validator("slot")
    @classmethod
    def _slot_known(cls, value: str) -> str:
        if value not in constants.TEST_SLOTS:
            raise ValueError(f"slot must be one of {constants.TEST_SLOTS}")
        return value


class AiTestResult(SQLModel):
    """Outcome of one test call. Failure is a result, never a 500."""

    ok: bool
    model: str = ""
    latency_ms: int = 0
    error: str = ""
