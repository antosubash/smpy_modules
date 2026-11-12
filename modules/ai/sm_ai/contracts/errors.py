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
    """A stored key has an ``enc:`` prefix but no known key decrypts it."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(
            f"The stored key {field!r} cannot be decrypted with SM_SECRET_KEY or any "
            "key in SM_SECRET_KEY_PREVIOUS. If SM_SECRET_KEY was rotated, add the old "
            "key to SM_SECRET_KEY_PREVIOUS (see docs/secret-key-rotation.md), or "
            "re-enter the key on the AI settings page."
        )


class AiBaseUrlRefusedError(AiError):
    """A slot's base URL points somewhere the module will not send its key (#347).

    ``reason`` is a constant (``invalid_scheme``, ``non_public_address``, …)
    and the message never echoes the URL.
    """

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        if reason == "non_public_address":
            message = (
                f"The AI setting {field!r} points at a private or local address. "
                "To use a local endpoint such as Ollama or an in-network gateway, turn on "
                "'Allow private base URLs' (the sm_ai setting allow_private_base_url) on "
                "the AI settings page."
            )
        else:
            message = f"The AI setting {field!r} is not a usable http(s) URL ({reason})."
        super().__init__(message)
