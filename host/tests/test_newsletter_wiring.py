"""The host mounts newsletter and its tables reach the migration metadata."""

from __future__ import annotations

from fastapi.routing import iter_route_contexts
from simple_module_db import build_module_metadata
from simple_module_hosting import Settings, create_app

NEWSLETTER_TABLES = {
    "newsletter_campaign",
    "newsletter_campaign_render",
    "newsletter_segment",
    "newsletter_send",
    "newsletter_send_attempt",
    "newsletter_link",
    "newsletter_click",
    "newsletter_suppression",
    "newsletter_suppression_lift",
    "newsletter_dispatch_lock",
}


def test_host_metadata_has_newsletter_tables():
    tables = set(build_module_metadata().tables)
    assert {t for t in tables if t.startswith("newsletter_")} == NEWSLETTER_TABLES


def test_host_loads_the_module():
    app = create_app(Settings())
    names = {m.meta.name for m in app.state.sm.modules}
    assert "Newsletter" in names


VIEW_PATHS = {
    "/admin/newsletter/",
    "/admin/newsletter/settings",
    "/admin/newsletter/campaigns/{campaign_id}",
}
MENU_URLS = {
    "/admin/newsletter/",
    "/admin/newsletter/segments",
    "/admin/newsletter/subscribers",
    "/admin/newsletter/suppressions",
    "/admin/newsletter/settings",
}


def test_views_and_menu_mounted():
    app = create_app(Settings())
    paths = {ctx.path for ctx in iter_route_contexts(app.routes)}
    assert paths >= VIEW_PATHS
    urls = {i.url for i in app.state.sm.menu_registry.all_items if i.group == "Newsletter"}
    assert urls == MENU_URLS


def test_unsubscribe_route_is_public():
    # The route is mounted at lifespan start (`on_startup`, which needs a migrated
    # database), so mount it the way `on_startup` does and drive the built stack:
    # an anonymous GET passes the host's auth and guards.
    from fastapi.testclient import TestClient
    from sm_newsletter.module import NewsletterModule

    app = create_app(Settings())
    NewsletterModule.mount_public_routes(app)
    response = TestClient(app).get("/newsletter/u/test", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_tracking_routes_are_public():
    # An anonymous GET passes the host's auth and guards: the pixel answers the
    # GIF and an unknown click token is the 404, not a 401 or a login redirect.
    from fastapi.testclient import TestClient
    from sm_newsletter.module import NewsletterModule

    app = create_app(Settings())
    NewsletterModule.mount_public_routes(app)
    client = TestClient(app)
    pixel = client.get("/newsletter/o/x.1.1.AAAA.gif", follow_redirects=False)
    assert pixel.status_code == 200
    assert pixel.headers["content-type"] == "image/gif"
    click = client.get("/newsletter/c/test/1", follow_redirects=False)
    assert click.status_code == 404


def test_people_screens_are_mounted():
    app = create_app(Settings())
    paths = {ctx.path for ctx in iter_route_contexts(app.routes)}
    assert {
        "/admin/newsletter/segments",
        "/admin/newsletter/subscribers",
        "/admin/newsletter/suppressions",
    } <= paths
    perms = {
        i.url: set(i.permissions)
        for i in app.state.sm.menu_registry.all_items
        if i.group == "Newsletter"
    }
    assert perms["/admin/newsletter/segments"] == {"newsletter.view"}
    assert perms["/admin/newsletter/subscribers"] == {"newsletter.view", "records.view"}
    assert perms["/admin/newsletter/suppressions"] == {"newsletter.manage"}
