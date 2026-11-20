"""``Cache-Control: private, no-store`` on every subscriptions API answer, errors included.

The answers hold the masked address and the fetch status; no cache (shared or private) keeps them
(the private feed's own rule). A middleware, not a route dependency: a refusal raised by the
handler is rendered by the module's error handler as a new response, which a dependency's header
never reaches.
"""

from __future__ import annotations

import re

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sm_events.core import constants

__all__ = ["NoStoreSubscriptions"]

_PATH = re.compile(
    rf"^{re.escape(constants.ROUTE_PREFIX_API)}/(?:calendars/[^/]+/subscriptions(?:/.*)?"
    r"|subscriptions(?:/.*)?)$"
)


class NoStoreSubscriptions:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _PATH.match(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        async def stamp(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
            await send(message)

        await self.app(scope, receive, stamp)
