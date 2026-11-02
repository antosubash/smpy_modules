"""The current HTTP request, for code a framework router calls without one.

The ``sharing`` router calls images' ``images.collection`` loader with only a
resource id. To apply images' per-request tenancy rule there
(:func:`sm_images.core.tenancy.resolve_admin`: an upstream tenant wins, a
single-tenant host supplies ``default`` only when nothing upstream resolved
one, a mounted child app the framework cannot answer for is multi), the loader
needs the request. This middleware remembers the request's ASGI scope in a
contextvar for the duration of the request; nothing else changes.

It sits outside the framework's ``TenantMiddleware`` (module middleware is
added after it), so it cannot resolve the tenant itself. It doesn't need to:
it ensures ``scope["state"]`` exists before anything inner runs, so the state
``TenantMiddleware`` and auth write later is the same dict the loader reads
when it runs, inside the endpoint.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

__all__ = ["RequestContextMiddleware", "current_request"]

_scope: ContextVar[Scope | None] = ContextVar("sm_images_request_scope", default=None)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        scope.setdefault("state", {})
        token = _scope.set(scope)
        try:
            await self.app(scope, receive, send)
        finally:
            _scope.reset(token)


def current_request() -> Any:
    """The request being served, or ``None`` outside one (a worker, the CLI)."""
    scope = _scope.get()
    return Request(scope) if scope is not None else None
