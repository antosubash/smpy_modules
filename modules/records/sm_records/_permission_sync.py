"""The per-request half of the role editor's per-type permissions — see
:mod:`sm_records.type_permissions`.

Split from that module along the seam it already has: that one is "what the
permissions are and how the registry gets them", this is "when". The source
the framework calls is sync and must not read the database, so the read
happens here, before the route, and the source only ever hands back the cache.

Pure ASGI module middleware, so it runs before ``InertiaLayoutDataMiddleware``
(the framework adds that first and each module's middleware afterwards, and
``add_middleware`` is LIFO): the role editor's page, its
``GET /api/permissions/`` and the ``PUT`` that saves a grant all see a type
written in this process on their very first request.

The sidebar needs no such step any more: its per-type entries come from a
``MenuRegistry`` provider evaluated per request (:mod:`sm_records.menu`).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from starlette.types import ASGIApp, Receive, Scope, Send

from sm_records import constants, type_permissions
from sm_records._tenancy_mode import TenancyMode, scope_mode

if TYPE_CHECKING:  # pragma: no cover - imports for typing only
    from sm_records.module import RecordsModule

__all__ = ["PermissionSyncMiddleware"]


class PermissionSyncMiddleware:
    """Bring the per-type permission list up to date before the route runs.

    Skips this module's own JSON API, the static mount and the health
    endpoints (:data:`~sm_records.constants.PERMISSION_SYNC_SKIP_PREFIXES`):
    the write path's statement count is a tested property of this module
    (``tests/perf``), and nothing there lists permissions.

    The lock makes the refresh single-flight within a worker: whoever gets
    there first does the read; the rest re-check the clock inside
    :func:`sm_records.type_permissions.refresh` and find nothing to do.
    """

    def __init__(self, app: ASGIApp, module: RecordsModule) -> None:
        self.app = app
        self.module = module
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _covered(scope.get("path", "")):
            if _ambiguous(scope) and not self.module.type_permissions.ambiguous:
                # Mounted under a parent nothing here can see (#210): it may
                # serve many tenants, so the labels go, for the process's life.
                self.module.type_permissions.ambiguous = True
                self.module.type_permissions.mark_dirty()
            async with self._lock:
                await type_permissions.refresh(self.module)
        await self.app(scope, receive, send)


def _ambiguous(scope: Scope) -> bool:
    """Whether this request reached a single-detected app through a mount the
    framework cannot answer for — :func:`sm_records.tenancy.request_mode`'s rule."""
    app = scope.get("app")
    return app is not None and scope_mode(app, scope, TenancyMode.SINGLE) is TenancyMode.MULTI


def _covered(path: str) -> bool:
    return not path.startswith(constants.PERMISSION_SYNC_SKIP_PREFIXES)
