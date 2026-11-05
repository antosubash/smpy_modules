"""The route-guard matrix: every mounted newsletter route, and what guards it.

The walk uses ``iter_route_contexts`` (effective routes, with their include
prefixes and router-level dependencies), compares the result with an explicit
expected set, and checks each route's dependency chain.

Order, as PR 2's routers have it: the API tree is included under
``RequiresCsrf`` by ``module.register_routes`` (outermost), then each router
lists ``bind_admin`` first, then its permission. So ``bind_admin`` must precede
every ``RequiresPermission`` (``get_db``'s commit has to run while the tenant
is still bound), and an unsafe API method must sit under ``RequiresCsrf``. The
anonymous routes (the email logo, the open pixel and the click redirect) carry
none of these and are asserted public.
"""

from __future__ import annotations

from fastapi.routing import iter_route_contexts
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_hosting.csrf import RequiresCsrf
from simple_module_hosting.permissions import RequiresPermission
from sm_newsletter.core import constants
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.module import NewsletterModule

from tests.support.app import build_app

API = constants.ROUTE_PREFIX_API
VIEW = constants.VIEW_PREFIX
ALLOWED = {*constants.PERMISSIONS, constants.PERM_SETTINGS_EDIT}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

EXPECTED = {
    ("GET", f"{API}/settings"),
    ("PUT", f"{API}/settings"),
    ("PUT", f"{API}/settings/smtp-password"),
    ("GET", f"{API}/campaigns"),
    ("POST", f"{API}/campaigns"),
    ("GET", f"{API}/campaigns/{{campaign_id}}"),
    ("PATCH", f"{API}/campaigns/{{campaign_id}}"),
    ("DELETE", f"{API}/campaigns/{{campaign_id}}"),
    ("GET", f"{API}/campaigns/{{campaign_id}}/preview"),
    ("POST", f"{API}/preview"),
    ("POST", f"{API}/campaigns/{{campaign_id}}/cards/refresh"),
    ("POST", f"{API}/campaigns/{{campaign_id}}/test-send"),
    ("POST", f"{API}/campaigns/{{campaign_id}}/send"),
    ("POST", f"{API}/campaigns/{{campaign_id}}/unschedule"),
    ("POST", f"{API}/campaigns/{{campaign_id}}/pause"),
    ("POST", f"{API}/campaigns/{{campaign_id}}/resume"),
    ("POST", f"{API}/campaigns/{{campaign_id}}/cancel"),
    ("GET", f"{API}/campaigns/{{campaign_id}}/progress"),
    ("GET", f"{API}/campaigns/{{campaign_id}}/estimate"),
    ("GET", f"{API}/cards/articles"),
    ("GET", f"{API}/cards/pages"),
    ("POST", f"{API}/cards/snapshot"),
    ("GET", f"{API}/media"),
    ("GET", f"{API}/outbox"),
    ("GET", f"{API}/lists"),
    ("GET", f"{VIEW}/"),
    ("GET", f"{VIEW}/settings"),
    ("GET", f"{VIEW}/campaigns/{{campaign_id}}"),
}


def _guarded(app):
    """``{(method, path): [dependency callables, outermost first]}`` for every
    newsletter route, the anonymous logo route aside."""
    out = {}
    for ctx in iter_route_contexts(app.routes):
        path = ctx.path or ""
        if not path.startswith((API, VIEW)):
            continue
        chain = [d.call for d in ctx.dependant.dependencies]
        for method in sorted((ctx.methods or set()) - {"HEAD"}):
            out[(method, path)] = chain
    return out


async def test_route_set_is_the_expected_one():
    app, state = await build_app()
    try:
        found = set(_guarded(app))
    finally:
        await state.engine.dispose()
    assert EXPECTED
    assert found == EXPECTED, (sorted(found - EXPECTED), sorted(EXPECTED - found))


async def test_every_route_is_guarded():
    app, state = await build_app()
    try:
        table = _guarded(app)
    finally:
        await state.engine.dispose()
    assert table
    for (method, path), chain in table.items():
        label = f"{method} {path}"
        binds = [i for i, d in enumerate(chain) if d is bind_admin]
        perms = [
            (i, d.permission) for i, d in enumerate(chain) if isinstance(d, RequiresPermission)
        ]
        assert binds, f"{label}: no bind_admin"
        assert perms, f"{label}: no RequiresPermission"
        assert binds[0] < min(i for i, _ in perms), (
            f"{label}: bind_admin is not before the permission"
        )
        assert {p for _, p in perms} <= ALLOWED, f"{label}: {perms}"
        if path.startswith(API) and method in UNSAFE:
            assert any(isinstance(d, RequiresCsrf) for d in chain), f"{label}: no RequiresCsrf"
            csrf = next(i for i, d in enumerate(chain) if isinstance(d, RequiresCsrf))
            assert csrf < binds[0], f"{label}: RequiresCsrf is not outermost"


def test_the_logo_route_is_public_and_unguarded():
    registry = PublicRouteRegistry()
    NewsletterModule().register_public_routes(registry)
    assert registry.matches("GET", constants.BRAND_LOGO_PATH)
    assert not registry.matches("POST", constants.BRAND_LOGO_PATH)
    from sm_newsletter.web.endpoints.brand import router

    routes = [(c.path, sorted(c.methods or ())) for c in iter_route_contexts(router.routes)]
    assert routes == [(constants.BRAND_LOGO_PATH, ["GET"])]
    for ctx in iter_route_contexts(router.routes):
        calls = [d.call for d in ctx.dependant.dependencies]
        assert bind_admin not in calls
        assert not any(isinstance(c, RequiresPermission) for c in calls)


def test_tracking_routes_are_public_and_unguarded():
    from sm_newsletter.web.endpoints.tracking import router

    routes = sorted((c.path, sorted(c.methods or ())) for c in iter_route_contexts(router.routes))
    assert routes == [
        (f"{constants.CLICK_PREFIX}{{token}}/{{position}}", ["GET"]),
        (f"{constants.OPEN_PREFIX}{{token}}.gif", ["GET"]),
    ]
    for ctx in iter_route_contexts(router.routes):
        calls = [d.call for d in ctx.dependant.dependencies]
        assert bind_admin not in calls
        assert not any(isinstance(c, RequiresPermission) for c in calls)
        assert not any(isinstance(c, RequiresCsrf) for c in calls)
