"""The host's live settings, for what newsletter reads per request (``public_base_url``).

``app.state.sm.settings`` is the boot snapshot; a ``host.*`` row saved on the Settings screen
reloads the framework's host services (``app.state.host``) instead, which is also what the
framework's own ``site_info`` reads. Without host services (a bare test app) the boot snapshot
is all there is.
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
    """The configured public origin, ``""`` when unset; never the request's ``Host``."""
    return str(getattr(host_settings(app), "public_base_url", "") or "")
