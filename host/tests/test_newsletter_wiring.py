"""The host mounts newsletter and its tables reach the migration metadata."""

from __future__ import annotations

from fastapi.routing import iter_route_contexts
from simple_module_db import build_module_metadata
from simple_module_hosting import Settings, create_app

NEWSLETTER_TABLES = {
    "newsletter_campaign",
    "newsletter_segment",
    "newsletter_send",
    "newsletter_send_attempt",
    "newsletter_link",
    "newsletter_click",
    "newsletter_suppression",
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
MENU_URLS = {"/admin/newsletter/", "/admin/newsletter/settings"}


def test_views_and_menu_mounted():
    app = create_app(Settings())
    paths = {ctx.path for ctx in iter_route_contexts(app.routes)}
    assert paths >= VIEW_PATHS
    urls = {i.url for i in app.state.sm.menu_registry.all_items if i.group == "Newsletter"}
    assert urls == MENU_URLS
