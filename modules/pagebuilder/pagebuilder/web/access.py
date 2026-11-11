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
from simple_module_hosting.permissions import PermissionDenied, ensure_resolved_permissions

from pagebuilder.core.permissions import PERM_EDIT, may_read
from pagebuilder.web.csrf import share_csrf_token, verify_csrf_if_configured


async def get_current_user_or_401(request: Request) -> Any:
    """Return the authenticated user or raise 401.

    Reads ``request.state.user`` (set by the host's auth middleware).
    We don't import ``auth.web.deps.get_current_user`` because it depends on
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


async def require_reader(request: Request) -> None:
    """Refuse a signed-in user who holds no pagebuilder permission (#346).

    Every admin read — the page list, a draft, its revisions, the site layout,
    the media library, the draft preview — is gated here, once, for the whole
    API and view routers, rather than per endpoint: a read added later is
    covered without anyone remembering to. Any one of ``pagebuilder.edit``,
    ``.publish`` or ``.approve`` is enough (:func:`may_read`); the writes keep
    their own, stricter checks.

    A request without a user is left to :func:`require_user_if_configured`,
    which has already answered 401 when ``requires_auth`` is on. With it off
    (an authenticating proxy in front) an anonymous request reads as before.

    Deliberately not marked as a token permission gate: API tokens could not
    reach these reads before, and this does not open them.
    """
    if getattr(request.state, "user", None) is None:
        return
    held = await ensure_resolved_permissions(request)
    if not may_read(held):
        # Named after the least of the three, the one an editor role grants.
        raise PermissionDenied(PERM_EDIT)


def build_admin_dependencies() -> list[Any]:
    """Dependencies applied to the API router.

    Returned items are ``Depends(...)`` wrappers ready to be passed to
    ``APIRouter(dependencies=...)``. The dependency order matters: auth
    runs first so an unauthenticated request gets 401 (the more useful
    error), then the tenant binding (403 ``tenant_required`` without one),
    then the framework's CSRF check (403). The binding has to precede
    ``get_db``, which every router-level dependency does: the endpoint's own
    dependencies are resolved after these, so ``get_db`` commits inside the
    tenant scope. The CSRF check also runs before any permission check: the
    router-wide read gate (:func:`require_reader`) comes last, and the
    per-endpoint permissions after it.
    """
    from pagebuilder.core.tenancy import bind_admin

    return [
        Depends(require_user_if_configured),
        Depends(bind_admin),
        Depends(verify_csrf_if_configured),
        Depends(require_reader),
    ]


def build_view_dependencies() -> list[Any]:
    """Dependencies applied to the Inertia view router.

    The same as :func:`build_admin_dependencies`, except that the CSRF token is
    shared as the ``csrf_token`` prop instead of checked. Inertia GETs are safe
    methods, so the check would pass anyway.
    """
    from pagebuilder.core.tenancy import bind_admin

    return [
        Depends(require_user_if_configured),
        Depends(bind_admin),
        Depends(share_csrf_token),
        Depends(require_reader),
    ]
