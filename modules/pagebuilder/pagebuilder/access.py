"""The dependencies every pagebuilder admin route runs, in order.

The pagebuilder module historically assumed the host gated ``/pagebuilder/*``
and ``/api/pagebuilder/*`` via session-cookie middleware. A host that
forgets to mount auth — or one that swaps the users module out — would
expose page CRUD + media upload to the public internet. These helpers
move the gate inside the module so it's secure by default.

The tenancy import is lazy so this module stays importable before the
module's models are.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request

from pagebuilder.csrf import share_csrf_token, verify_csrf_if_configured


async def get_current_user_or_401(request: Request) -> Any:
    """Return the authenticated user or raise 401.

    Reads ``request.state.user`` (set by the host's auth middleware).
    We don't import ``auth.deps.get_current_user`` because it depends on
    the i18n TranslatorDep — the failure mode we care about is "no auth
    middleware mounted at all", which would leave ``request.state.user``
    unset regardless of which dep we use.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def require_user_if_configured(request: Request) -> Any:
    """Apply :func:`get_current_user_or_401` when ``requires_auth`` is set.

    Always installed, and decides per request. The routers are built before
    the host hydrates settings from the database, so a dependency list
    assembled from the flag at that point would be frozen at the pydantic
    default — leaving the Settings screen showing a switch that changes
    nothing until someone edits an environment that no longer exists.
    """
    if not request.app.state.pagebuilder.settings.requires_auth:
        return None
    return await get_current_user_or_401(request)


def build_admin_dependencies() -> list[Any]:
    """Dependencies applied to the API router.

    Returned items are ``Depends(...)`` wrappers ready to be passed to
    ``APIRouter(dependencies=...)``. The dependency order matters: auth
    runs first so an unauthenticated request gets 401 (the more useful
    error), then the tenant binding (403 ``tenant_required`` without one),
    then the framework's CSRF check (403). The binding has to precede
    ``get_db``, which every router-level dependency does: the endpoint's own
    dependencies are resolved after these, so ``get_db`` commits inside the
    tenant scope. The CSRF check also runs before any permission check, which
    is an endpoint dependency.
    """
    from pagebuilder.tenancy import bind_admin

    return [
        Depends(require_user_if_configured),
        Depends(bind_admin),
        Depends(verify_csrf_if_configured),
    ]


def build_view_dependencies() -> list[Any]:
    """Dependencies applied to the Inertia view router.

    The same as :func:`build_admin_dependencies`, except that the CSRF token is
    shared as the ``csrf_token`` prop instead of checked. Inertia GETs are safe
    methods, so the check would pass anyway.
    """
    from pagebuilder.tenancy import bind_admin

    return [
        Depends(require_user_if_configured),
        Depends(bind_admin),
        Depends(share_csrf_token),
    ]
