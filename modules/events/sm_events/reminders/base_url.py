"""The host's public origin, as the reminders read it (a leaf module: no imports of its own)."""

from __future__ import annotations

from typing import Any

__all__ = ["public_base_url"]


def public_base_url(app: Any) -> str:
    """The host's ``public_base_url`` without a trailing slash; ``""`` when unset."""
    host = getattr(getattr(app.state, "sm", None), "settings", None)
    return str(getattr(host, "public_base_url", "") or "").strip().rstrip("/")
