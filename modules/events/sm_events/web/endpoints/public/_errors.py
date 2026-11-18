"""The route class every public router uses: errors leave through the cache policy.

An exception left to propagate is rendered by the app's handler, where nothing in the route can
add a header, and the framework's handler drops ``HTTPException.headers``. So this route class
answers the exceptions the app has a handler for itself, through that same handler (the body is
unchanged), and puts every error answer, those and the plain 404 responses endpoints return,
through :func:`~sm_events.web.endpoints.public._cache.error_headers`: ``no-store``, no ``ETag``,
the tenant in ``Vary``.

An exception nobody has a handler for propagates (the host's last-resort page). The public
routes write nothing, so there is nothing to roll back.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from sm_events.web.endpoints.public._cache import error_headers

__all__ = ["PublicErrorRoute"]


def _host_handler(request: Request, exc: Exception) -> Callable[..., Any] | None:
    """The handler the app registered for ``exc``'s nearest class, as Starlette's
    ``ExceptionMiddleware`` would pick it (``Exception`` itself aside)."""
    handlers = getattr(request.app, "exception_handlers", None) or {}
    for cls in type(exc).__mro__:
        if cls is not Exception and cls in handlers:
            return handlers[cls]
    return None


class PublicErrorRoute(APIRoute):
    """Every error answer of a public router leaves through ``error_headers``."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                response = await handler(request)
            except Exception as exc:
                host = _host_handler(request, exc)
                if host is None:
                    raise
                response = host(request, exc)
                if hasattr(response, "__await__"):
                    response = await response
            return error_headers(request, response)

        return wrapped
