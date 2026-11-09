"""The skeleton's registrations: permissions, the locale directory, startup."""

from __future__ import annotations

from simple_module_core.permissions import PermissionRegistry
from sm_newsletter.core import constants
from sm_newsletter.module import NewsletterModule

EXPECTED_PERMISSIONS = {
    "newsletter.view",
    "newsletter.edit",
    "newsletter.send",
    "newsletter.manage",
}


def test_module_registers_permissions():
    registry = PermissionRegistry()
    NewsletterModule().register_permissions(registry)
    assert set(registry.all_permissions) == EXPECTED_PERMISSIONS
    (group,) = registry.groups
    assert group.name == constants.PERM_GROUP == "Newsletter"
    assert group.label_key == "newsletter.permission_group"
    # Settings are governed by the framework's ``settings.edit``.
    assert "newsletter.settings" not in registry.all_permissions


def test_locale_dir_is_the_namespace():
    dirs = NewsletterModule().locale_dirs()
    assert "newsletter" in dirs
    names = {p.name for p in dirs["newsletter"].iterdir()}
    assert {"en.json", "de.json"} <= names


async def test_on_startup_configures_tenancy_and_installs_the_guard(monkeypatch):
    from types import SimpleNamespace

    from sm_newsletter.core import tenancy

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(tenancy, "configure", lambda app: calls.append(("configure", app)))
    monkeypatch.setattr(tenancy, "install_guard", lambda cls: calls.append(("guard", cls)))
    monkeypatch.setattr(
        NewsletterModule, "mount_public_routes", staticmethod(lambda a: calls.append(("mount", a)))
    )
    session_class = object()
    app = SimpleNamespace(
        state=SimpleNamespace(
            sm=SimpleNamespace(db=SimpleNamespace(sync_session_class=session_class))
        )
    )
    await NewsletterModule().on_startup(app)
    assert calls == [("configure", app), ("mount", app), ("guard", session_class)]

    calls.clear()
    bare = SimpleNamespace(state=SimpleNamespace())
    await NewsletterModule().on_startup(bare)
    assert calls == [("configure", bare), ("mount", bare)]


def test_unsubscribe_prefix_is_public_for_get_and_post_with_its_own_rates():
    """The anonymous rate is the rule's own, not the host's ``rate_limit_public``
    (120/minute by default): one-click POSTs arrive from providers' shared IPs."""
    from simple_module_core.public_routes import PublicRouteRegistry

    registry = PublicRouteRegistry()
    NewsletterModule().register_public_routes(registry)
    url = f"{constants.UNSUBSCRIBE_PREFIX}t.1.2.mac"
    assert registry.matches("GET", url) and registry.matches("POST", url)
    assert not registry.matches("PUT", url)
    assert registry.match("GET", url).rate == "60/minute"
    assert registry.match("POST", url).rate == "300/minute"
    assert registry.matches("GET", constants.BRAND_LOGO_PATH)
    assert not registry.matches("POST", constants.BRAND_LOGO_PATH)


def test_unsubscribe_rate_rules_per_method():
    from simple_module_core.rate_limit import RateLimitRegistry

    registry = RateLimitRegistry()
    NewsletterModule().register_rate_limits(registry)
    url = f"{constants.UNSUBSCRIBE_PREFIX}t.1.2.mac"
    get, post = registry.match("GET", url), registry.match("POST", url)
    assert (get.rate, get.key, get.methods) == ("60/minute", "ip", frozenset({"GET"}))
    assert (post.rate, post.key, post.methods) == ("300/minute", "ip", frozenset({"POST"}))
    assert registry.match("PUT", url) is None
    assert registry.match("GET", "/newsletter/brand/logo") is None


def test_tracking_prefixes_are_public_for_get_with_their_own_rates():
    """T11: the pixel's 600/minute and the click's 300/minute, not the host's
    ``rate_limit_public``; ``GET`` only."""
    from simple_module_core.public_routes import PublicRouteRegistry
    from simple_module_core.rate_limit import RateLimitRegistry

    public, rates = PublicRouteRegistry(), RateLimitRegistry()
    NewsletterModule().register_public_routes(public)
    NewsletterModule().register_rate_limits(rates)
    pixel, click = f"{constants.OPEN_PREFIX}x.gif", f"{constants.CLICK_PREFIX}x/1"
    for url, rate in ((pixel, "600/minute"), (click, "300/minute")):
        assert public.matches("GET", url) and not public.matches("POST", url)
        assert public.match("GET", url).rate == rate
        rule = rates.match("GET", url)
        assert (rule.rate, rule.key, rule.methods) == (rate, "ip", frozenset({"GET"}))
        assert rates.match("POST", url) is None


def test_mount_public_routes_mounts_each_router_once():
    from fastapi import FastAPI
    from fastapi.routing import iter_route_contexts

    app = FastAPI()
    NewsletterModule.mount_public_routes(app)
    NewsletterModule.mount_public_routes(app)  # a lifespan restart
    paths = [r.path for r in iter_route_contexts(app.routes)]
    assert paths.count(constants.BRAND_LOGO_PATH) == 1
    assert paths.count(f"{constants.UNSUBSCRIBE_PREFIX}{{token}}") == 2  # GET and POST
    assert paths.count(f"{constants.OPEN_PREFIX}{{token}}.gif") == 1
    assert paths.count(f"{constants.CLICK_PREFIX}{{token}}/{{position}}") == 1
