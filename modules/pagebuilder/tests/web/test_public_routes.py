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

from types import SimpleNamespace

import pytest
from pagebuilder.core import boot, locales
from pagebuilder.core.settings import PagebuilderSettings
from simple_module_core.public_routes import PublicRouteRegistry


def _registry(*, registry=None, **overrides) -> PublicRouteRegistry:
    """The rules the module adds for a site configured with ``overrides``.

    Filled from ``boot.exempt_public_routes`` rather than the
    ``register_public_routes`` hook: which paths are public depends on
    settings the host hydrates from the database *after* that hook has run,
    so the module adds them at startup instead, into the registry the auth
    middleware reads live. A stub app is all that function needs — the
    registry hangs off ``app.state``.
    """
    if registry is None:
        registry = PublicRouteRegistry()
    app = SimpleNamespace(state=SimpleNamespace(public_routes=registry))
    settings = PagebuilderSettings(**overrides)
    locales.use(settings)
    boot.exempt_public_routes(app, settings)
    return registry


def test_no_registry_is_survivable():
    """A host with no auth middleware publishes no registry to add to."""
    boot.exempt_public_routes(
        SimpleNamespace(state=SimpleNamespace()), PagebuilderSettings()
    )


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


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_media_is_not_rate_limited(method):
    """A page's images must not spend the visitor's request budget (#442).

    The files come from a static mount, like the host's ``/static/``, which the
    limiter skips by itself. Pages keep the host's rate.
    """
    registry = _registry()
    media = registry.match(method, "/media/pagebuilder/abc123.png")
    assert media is not None and media.rate == "off"
    page = registry.match(method, "/p/launch-announcement")
    assert page is not None and page.rate is None


def test_a_custom_media_prefix_is_not_rate_limited_either():
    registry = _registry(media_url_prefix="/uploads/site")
    rule = registry.match("GET", "/uploads/site/default/abc123.png")
    assert rule is not None and rule.rate == "off"


def test_media_keeps_the_host_rate_when_its_prefix_contains_the_pages(caplog):
    """"off" on a prefix that holds the page route would unlimit the pages too."""
    with caplog.at_level("WARNING", logger="simple_module.pagebuilder"):
        registry = _registry(media_url_prefix="/p")
    for path in ("/p/launch-announcement", "/p/default/abc123.png"):
        rule = registry.match("GET", path)
        assert rule is not None and rule.rate is None
    assert "contains other public routes (/p/)" in caplog.text


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    ("kind", "pattern", "path"),
    [
        ("prefix", "/media/pagebuilder/dynamic/", "/media/pagebuilder/dynamic/item"),
        ("exact", "/media/pagebuilder/dynamic", "/media/pagebuilder/dynamic"),
    ],
)
def test_media_preserves_the_limit_of_a_public_route_inside_its_prefix(method, kind, pattern, path):
    registry = PublicRouteRegistry()
    registry.add(pattern, kind=kind, methods={method})
    _registry(registry=registry)
    rule = registry.match(method, path)
    assert rule is not None and rule.rate is None


@pytest.mark.parametrize(
    ("methods", "rate"), [({"POST"}, None), ({"GET", "HEAD"}, "30/minute")]
)
def test_rules_that_cannot_lose_their_rate_do_not_disable_media_exemption(methods, rate):
    registry = PublicRouteRegistry()
    registry.add_exact("/media/pagebuilder/dynamic", methods=methods, rate=rate)
    _registry(registry=registry)
    media = registry.match("GET", "/media/pagebuilder/default/abc123.png")
    assert media is not None and media.rate == "off"


@pytest.mark.parametrize(
    ("kind", "pattern"),
    [("prefix", "/media/"), ("suffix", "/tilejson"), ("regex", r"^/api/[^/]+/tiles$")],
)
def test_a_rule_that_is_not_inside_the_media_prefix_keeps_the_exemption(kind, pattern):
    """Another module's broad, suffix or regex rule must not switch the fix off:
    under the media prefix it can only match a path the media mount serves."""
    registry = PublicRouteRegistry()
    registry.add(pattern, kind=kind, methods={"GET"})
    _registry(registry=registry)
    media = registry.match("GET", "/media/pagebuilder/default/abc123.png")
    assert media is not None and media.rate == "off"


@pytest.mark.parametrize("media_prefix", ["/", "/p///", "/de", "/en"])
@pytest.mark.parametrize("default_locale", ["en", "de"])
def test_media_preserves_all_page_locale_limits(media_prefix, default_locale):
    registry = _registry(
        media_url_prefix=media_prefix,
        content_locales=("en", "de"),
        default_content_locale=default_locale,
    )
    for path in ("/p/about", "/de/p/about", "/en/p/about", "/sitemap.xml", "/robots.txt"):
        rule = registry.match("GET", path)
        assert rule is not None and rule.rate is None


@pytest.mark.parametrize("media_prefix", ["/px", "/sitemap.xml", "/robots.txt"])
def test_nonoverlapping_media_prefix_keeps_its_exemption(media_prefix):
    registry = _registry(media_url_prefix=media_prefix)
    media = registry.match("GET", f"{media_prefix}/default/abc123.png")
    assert media is not None and media.rate == "off"
    for path in ("/p/about", "/sitemap.xml", "/robots.txt"):
        rule = registry.match("GET", path)
        assert rule is not None and rule.rate is None


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
