"""Exceptions consuming modules catch. No imports from the rest of sm_ai —
this file sits at the bottom of the dependency graph."""

from __future__ import annotations


class AiError(Exception):
    """Base class for AI module errors."""


class AiNotConfiguredError(AiError):
    """A required connection setting is missing or invalid."""

    def __init__(self, field: str, hint: str = "") -> None:
        self.field = field
        message = f"AI is not configured: {field!r} is missing or invalid."
        if hint:
            message = f"{message} {hint}"
        super().__init__(message)


class AiKeyUnreadableError(AiError):
    """A stored key has the enc:v1: prefix but cannot be decrypted."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(
            f"The stored key {field!r} cannot be decrypted — SM_SECRET_KEY has "
            "changed. Re-enter the key on the AI settings page."
        )
