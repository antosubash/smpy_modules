"""The host's live settings, and the public origin built from them: the one reader.

``app.state.sm.settings`` is the **boot snapshot**. A ``host.*`` row saved on the Settings screen
reloads the framework's host services (``app.state.host``) and leaves the snapshot as it was, so
``public_base_url`` (documented as read per request) would lag a saved address until a restart.
Public URLs (pages, feeds, the sitemap, JSON-LD) and reminders both read it here; the snapshot is
only the fallback of a bare app or a headless worker app that has no host services.
"""

from __future__ import annotations

from typing import Any

from simple_module_core.app_state import get_host_services

__all__ = ["host_settings", "public_base_url"]


def host_settings(app: Any) -> Any:
    live = getattr(get_host_services(app), "settings", None)
    if live is not None:
        return live
    return getattr(getattr(app.state, "sm", None), "settings", None)


def public_base_url(app: Any) -> str:
    """The host's ``public_base_url`` without a trailing slash; ``""`` when unset."""
    return str(getattr(host_settings(app), "public_base_url", "") or "").strip().rstrip("/")
