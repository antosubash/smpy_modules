"""The signed-in person a plugin source is read for."""

from __future__ import annotations

from fastapi import Request
from simple_module_core.resources import ResourcePrincipal

from sm_events.calendar.plugins.extension_types import SourceViewer

__all__ = ["source_viewer_from"]


def source_viewer_from(request: Request, who: ResourcePrincipal) -> SourceViewer | None:
    """``None`` for an anonymous request. Roles come from the request's user (a plugin may
    narrow by role), permissions from ``who`` (already resolved for this request) and the
    role map from the host's permission registry."""
    if who.user_id is None:
        return None
    user = getattr(request.state, "user", None)
    registry = getattr(getattr(request.app.state, "sm", None), "permissions", None)
    role_map = getattr(registry, "role_map", None)
    return SourceViewer(
        user_id=who.user_id,
        roles=tuple(str(r) for r in (getattr(user, "roles", None) or ())),
        permissions=frozenset(who.permissions),
        role_map=dict(role_map) if role_map is not None else None,
    )
