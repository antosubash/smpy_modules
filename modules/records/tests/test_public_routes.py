"""The anonymous read API must be reachable without a session — asserted
against the registry, from the anonymous side.

Design §15 asks for exactly this, as ``modules/pagebuilder/tests/
test_public_routes.py`` does it: the Playwright suite runs as a logged-in
admin, so a missing exemption is invisible there. The consequence of getting
it wrong in *this* module runs in both directions — too little and a public
type 302s to the login screen, too much and an unterminated prefix hands the
admin API to anonymous callers, unpublished records and all.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from simple_module_core.public_routes import PublicRouteRegistry
from sm_records import boot, constants
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings


def _registry(**overrides) -> PublicRouteRegistry:
    """The rules the module adds for an install configured with ``overrides``.

    Filled from ``boot.exempt_public_routes`` and not from the
    ``register_public_routes`` hook, because ``public_route_prefix`` is
    hydrated from the database *after* that hook has run — the module adds the
    rule at startup instead, into the registry ``AuthMiddleware`` reads live.
    A stub app is all the function needs; the registry hangs off ``app.state``.
    """
    registry = PublicRouteRegistry()
    app = SimpleNamespace(state=SimpleNamespace(public_routes=registry))
    boot.exempt_public_routes(app, RecordsSettings(**overrides))
    return registry


def test_no_registry_is_survivable():
    """A host with no auth middleware publishes no registry to add to."""
    boot.exempt_public_routes(SimpleNamespace(state=SimpleNamespace()), RecordsSettings())


def test_the_construction_time_hook_adds_nothing():
    """It cannot: the prefix is not known yet. The empty hook is the documented
    half of the arrangement, so a future edit that "fills it in" fails here."""
    registry = PublicRouteRegistry()
    RecordsModule().register_public_routes(registry)
    assert registry.routes == []


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    "path",
    [
        "/api/records/public/article",
        "/api/records/public/article/0123456789abcdef0123456789abcdef",
    ],
)
def test_the_public_read_api_is_anonymous(path, method):
    """``HEAD`` too: conditional GETs and link checkers issue it, and Starlette
    answers it on every GET route — so the exemption has to cover it or the
    check 302s."""
    assert _registry().matches(method, path), f"{method} {path} would 302 to login"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_only_read_verbs_are_exempt(method):
    """``PUBLIC_ROUTE_METHODS`` is pinned, so a future route mounted under the
    same prefix cannot widen the exemption by accident (§10)."""
    assert not _registry().matches(method, "/api/records/public/article")


@pytest.mark.parametrize(
    "path",
    [
        "/api/records/types",
        "/api/records/types/article/records",
        "/api/records/types/article/records/0123456789abcdef0123456789abcdef",
        "/admin/records/",
        "/admin/records/article",
        # Shares every character of the public prefix but the terminator. An
        # unterminated prefix rule would exempt it — which is why
        # ``boot.dir_prefix`` exists.
        "/api/records/publicity",
    ],
)
def test_the_admin_surface_stays_gated(path):
    assert not _registry().matches("GET", path), f"{path} must require auth"


def test_respects_a_custom_public_prefix():
    registry = _registry(public_route_prefix="/content")
    assert registry.matches("GET", "/content/article")
    assert not registry.matches("GET", "/api/records/public/article")


def test_a_prefix_written_with_a_trailing_slash_behaves_the_same():
    """Operators type both; ``dir_prefix`` normalises to exactly one slash, so
    the rule cannot end up as ``/content//``."""
    registry = _registry(public_route_prefix="/content/")
    assert registry.matches("GET", "/content/article")
    assert not registry.matches("GET", "/contentious/article")


def test_the_methods_are_the_pinned_constant():
    """Not a local literal: the constant is what ``§10`` pins, and the router
    and the exemption have to agree on it."""
    (rule,) = _registry().routes
    assert set(rule.methods) == set(constants.PUBLIC_ROUTE_METHODS)
