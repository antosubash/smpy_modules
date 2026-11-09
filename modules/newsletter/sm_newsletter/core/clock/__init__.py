"""The process's wall clock, in UTC: the one ``now()`` the module imports.

A package rather than a module so a test can pin one caller's clock by
patching the name that caller imported.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["utcnow"]


def utcnow() -> datetime:
    return datetime.now(UTC)
