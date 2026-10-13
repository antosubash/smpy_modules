"""Guard: every route that touches news' tables binds a tenant.

``tenant_fixture`` binds the default tenant around every test, which would
hide a router that forgot ``bind_admin`` / ``bind_public``. This walks each
route's dependency tree instead, so a missing binding fails here. Ported from
pagebuilder's guard.
"""

from __future__ import annotations

from collections.abc import Iterator

from conftest import ROLE_EDITOR, _build_app
from fastapi.dependencies.models import Dependant
from news import constants
from news.module import NewsModule
from news.settings import active
from news.tenancy import bind_admin, bind_public
from stub_auth import stub_user


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


async def test_every_news_route_binds_a_tenant(bilingual) -> None:
    # Bilingual, so the default-locale alias router and a second language's
    # public router are mounted, and checked, too.
    app, state = await _build_app(stub_user((ROLE_EDITOR,)), mount_public=True)
    try:
        meta = NewsModule().meta
        public = active().public_route_prefix.rstrip("/")
        prefixes = (
            meta.route_prefix,
            meta.view_prefix,
            constants.ADMIN_SEARCH_PREFIX,
            public,
            f"/de{public}",
            f"/en{public}",
        )
        # Every news route reads rows, so none is allow-listed as unbound.
        routes = [r for r in _api_routes(app.routes) if r.path.startswith(prefixes)]
        paths = {r.path for r in routes}
        assert f"{public}/{{slug}}" in paths, "public viewer not mounted"
        assert f"/de{public}/{{slug}}" in paths, "second language not mounted"
        assert f"/en{public}/{{slug}}" in paths, "default-locale alias not mounted"
        assert f"{public}/sitemap.xml" in paths, "sitemap not mounted"
        assert f"{constants.ADMIN_SEARCH_PREFIX}/search" in paths, "admin search not mounted"
        unbound = sorted(f"{sorted(r.methods)} {r.path}" for r in routes if not _guarded(r))
        assert not unbound, f"routes without bind_admin/bind_public: {unbound}"
    finally:
        await state.engine.dispose()
