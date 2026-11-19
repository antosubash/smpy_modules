"""The host's public origin, as the reminders read it.

``app.state.sm.settings`` is the **boot snapshot**; a ``host.*`` row saved on the Settings screen
reloads the framework's host services (``app.state.host``) instead, and that is what is current.
Reading the snapshot made a freshly configured address invisible until a restart (found in the
browser: the control stayed ``no_public_base_url`` after the operator set it), so the live
settings win and the snapshot is only the fallback of a bare app.
"""

from __future__ import annotations

from typing import Any

from simple_module_core.app_state import get_host_services

__all__ = ["public_base_url"]


def public_base_url(app: Any) -> str:
    """The host's ``public_base_url`` without a trailing slash; ``""`` when unset."""
    live = getattr(get_host_services(app), "settings", None)
    host = live if live is not None else getattr(getattr(app.state, "sm", None), "settings", None)
    return str(getattr(host, "public_base_url", "") or "").strip().rstrip("/")
