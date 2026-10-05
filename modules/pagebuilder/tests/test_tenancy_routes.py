"""Guard: every route that touches pagebuilder's tables binds a tenant.

``tenant_fixture`` binds the default tenant around every test, which would
hide a router that forgot ``bind_admin`` / ``bind_public``. This walks each
route's dependency tree instead, so a missing binding fails here.
"""

from __future__ import annotations

from collections.abc import Iterator

from conftest import _build_app
from fastapi.dependencies.models import Dependant
from pagebuilder.module import PagebuilderModule
from pagebuilder.tenancy import bind_admin, bind_public

#: Reads no rows, so it answers on any host (see ``endpoints/seo.py``).
ALLOW_UNBOUND = {"/robots.txt"}


def _calls(dep: Dependant) -> Iterator[object]:
    for sub in dep.dependencies:
        yield sub.call
        yield from _calls(sub)


def _api_routes(routes: list) -> Iterator[object]:
    """Every API route with its final path and dependency tree.

    Recent FastAPI keeps ``include_router`` lazy: the app holds an
    ``_IncludedRouter`` whose ``effective_candidates()`` yield per-route
    contexts carrying the prefixed ``path`` and the ``dependant``. Older
    versions flatten into ``APIRoute`` objects; both shapes are handled.
    """
    for route in routes:
        if hasattr(route, "effective_candidates"):
            yield from _api_routes(route.effective_candidates())
        elif getattr(route, "dependant", None) is not None:
            yield route


def _guarded(route: object) -> bool:
    calls = list(_calls(route.dependant))
    return bind_admin in calls or bind_public in calls


async def test_every_pagebuilder_route_binds_a_tenant(tmp_path) -> None:
    app, cleanup = await _build_app(
        tmp_path, requires_auth=False, csrf_protect=False, inject_user=True
    )
    try:
        meta = PagebuilderModule().meta
        prefixes = (meta.route_prefix, meta.view_prefix, "/p/", "/sitemap.xml")
        routes = [
            r
            for r in _api_routes(app.routes)
            if r.path not in ALLOW_UNBOUND
            and r.path.startswith(prefixes)
        ]
        assert routes, "no pagebuilder routes found; the guard is checking nothing"
        unbound = sorted(f"{sorted(r.methods)} {r.path}" for r in routes if not _guarded(r))
        assert not unbound, f"routes without bind_admin/bind_public: {unbound}"
    finally:
        await cleanup()
