"""Fernet encryption for the stored Stripe secrets."""

from __future__ import annotations

from collections.abc import Callable

_secret_provider: Callable[[], str] | None = None


def set_secret_provider(provider: Callable[[], str]) -> None:
    """Install the live-secret source."""
    global _secret_provider
    _secret_provider = provider
