"""What the private feed's tests share: users the directory knows, and a request to ask as."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request

from tests.support.app import Directory, build_app

NOW = datetime(2026, 6, 15, 12, tzinfo=UTC)
"""A clock a month before ``tests.support.calendars``' default event date (2026-07-01)."""

USERS = {
    uid: (f"{uid}@example.com", uid.title(), True)
    for uid in ("o", "sv", "se", "v", "m", "e", "a", "x")
}
ROLES: dict[str, tuple[str, ...] | None] = {
    "o": ("editor",),
    "sv": ("viewer",),
    "se": ("viewer",),
    "v": ("viewer",),
    "e": ("editor",),
    "m": ("manager",),
    "a": (),
    "x": ("viewer",),
}


def fake_request(app: Any, *, locale: str | None = None, host_tenant: str | None = None) -> Request:
    """A bare request on ``app``: what ``create_token`` and ``resolve`` read from it."""
    request = Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"})
    if locale is not None:
        request.state.locale = locale
    if host_tenant is not None:
        request.state.tenant_id = host_tenant
        request.state.tenant_source = "subdomain"
    return request


def install_directory(app: Any, *, roles: dict | None = None) -> Directory:
    directory = Directory(dict(USERS), dict(ROLES if roles is None else roles))
    app.state.user_directory = directory
    return directory


def install_members(app: Any, members: dict[str, set[str]]) -> Callable[..., Any]:
    """A membership store over ``{tenant: user ids}`` (the framework's ``tenant_members``)."""

    async def tenant_members(db: Any, tenant_id: str, ids: Any) -> set[str]:
        return {i for i in ids if i in members.get(tenant_id, set())}

    app.state.tenant_members = tenant_members
    return tenant_members


async def token_app(*, multi: bool = False, settings: dict | None = None):
    """An events app with the directory installed; the caller disposes of ``state.engine``."""
    app, state = await build_app(multi=multi, settings=settings)
    install_directory(app)
    return app, state


__all__ = [
    "NOW",
    "ROLES",
    "USERS",
    "fake_request",
    "install_directory",
    "install_members",
    "token_app",
]
