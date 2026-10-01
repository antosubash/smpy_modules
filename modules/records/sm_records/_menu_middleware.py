"""The per-request half of the sidebar sync — see :mod:`sm_records.menu`.

Split from that module rather than folded into it because of the 300-line cap,
along the seam the module already has: ``menu.py`` is "what the entries are and
how the registry gets them", this is "when".

Pure ASGI, and a module middleware rather than anything on the route, because
what it needs is to run *before* ``InertiaLayoutDataMiddleware`` — that is
what reads the registry into the shared props of every Inertia response, and
a sync after it would always be one page late. Module middleware does: the
framework's ``install_middleware`` adds the Inertia layer first and each
module's middleware afterwards, and ``add_middleware`` is LIFO, so what is
added last runs first. A sync done here is visible to the very request that
triggered it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from starlette.types import ASGIApp, Receive, Scope, Send

from sm_records import constants, menu

if TYPE_CHECKING:  # pragma: no cover - imports for typing only
    from sm_records.module import RecordsModule

__all__ = ["MenuSyncMiddleware"]


class MenuSyncMiddleware:
    """Bring the admin sidebar up to date before the page that renders it.

    Skips everything that has no sidebar — the JSON API, the static mount and
    the health endpoints. That is not only an optimisation: the write path's
    statement count is a tested property of this module (``tests/perf``), and
    a navigation read riding along on every ``POST /api/records/...`` would
    change it for something no API caller ever looks at.

    The lock makes the refresh single-flight within a worker: several requests
    arriving together after the window expired would otherwise each open a
    session and each splice the registry. Whoever gets there first does the
    read; the rest re-check the clock inside :func:`sm_records.menu.refresh`
    and find nothing to do.
    """

    def __init__(self, app: ASGIApp, module: RecordsModule) -> None:
        self.app = app
        self.module = module
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _renders_a_sidebar(scope.get("path", "")):
            async with self._lock:
                await menu.refresh(self.module)
        await self.app(scope, receive, send)


def _renders_a_sidebar(path: str) -> bool:
    return not path.startswith(constants.MENU_SKIP_PREFIXES)
