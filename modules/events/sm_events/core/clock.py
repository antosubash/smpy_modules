"""The process's wall clock, in UTC: the one ``now()`` the module imports."""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["utcnow"]


def utcnow() -> datetime:
    """The current instant, timezone-aware UTC."""
    return datetime.now(UTC)
