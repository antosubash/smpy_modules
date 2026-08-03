"""The reader-facing surface must be reachable without a session.

Regression guard. The module previously never called
``register_public_routes``, so ``AuthMiddleware`` gated the published page,
the sitemap, and robots.txt — every anonymous visitor was 302'd to the login
screen, which defeats the point of a page builder.

The Playwright suite can't catch this: it runs as a logged-in admin, so the
gated routes answer normally there. These tests assert on the registry
directly, from the anonymous side.
"""

from __future__ import annotations

import pytest
from pagebuilder.module import PagebuilderModule
from pagebuilder.settings import PagebuilderSettings
from simple_module_core.public_routes import PublicRouteRegistry


def _registry(**overrides) -> PublicRouteRegistry:
    module = PagebuilderModule()
    module.settings = PagebuilderSettings(**overrides)
    registry = PublicRouteRegistry()
    module.register_public_routes(registry)
    return registry


@pytest.mark.parametrize(
    "path",
    [
        "/p/launch-announcement",
        "/p/nested/slug",
        "/sitemap.xml",
        "/robots.txt",
        "/media/pagebuilder/abc123.png",
    ],
)
def test_reader_surface_is_anonymous(path):
    assert _registry().matches("GET", path), f"{path} would 302 to login"


@pytest.mark.parametrize("path", ["/p/launch-announcement", "/media/pagebuilder/abc123.png"])
def test_head_is_allowed_too(path):
    """Conditional GETs and link checkers issue HEAD."""
    assert _registry().matches("HEAD", path)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_only_read_verbs_are_exempt(method):
    assert not _registry().matches(method, "/p/launch-announcement")


@pytest.mark.parametrize(
    "path",
    [
        "/api/pagebuilder/pages",
        "/api/pagebuilder/uploads",
        # These share a first character with the default "/p" public prefix.
        # An unterminated prefix rule would hand the whole admin UI to anonymous
        # visitors, which is exactly the mistake _dir_prefix exists to prevent.
        "/pagebuilder/",
        "/pagebuilder/1/edit",
        "/pagebuilder/media",
    ],
)
def test_the_admin_surface_stays_gated(path):
    assert not _registry().matches("GET", path), f"{path} must require auth"


def test_a_sibling_of_the_media_prefix_stays_gated():
    assert not _registry().matches("GET", "/media/pagebuilder-private/secret.png")


def test_respects_a_custom_public_prefix():
    registry = _registry(public_route_prefix="/site")
    assert registry.matches("GET", "/site/about")
    assert not registry.matches("GET", "/p/about")


def test_sitemap_and_robots_follow_their_settings():
    off = _registry(sitemap_enabled=False, robots_enabled=False)
    assert not off.matches("GET", "/sitemap.xml")
    assert not off.matches("GET", "/robots.txt")
