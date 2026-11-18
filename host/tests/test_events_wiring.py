"""The host mounts events and its tables reach the migration metadata."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.routing import iter_route_contexts
from simple_module_db import build_module_metadata
from simple_module_hosting import Settings, create_app

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))

# What ``main.py`` imports before ``create_app``: the records module seals its collection
# registry in the first app any test builds.
import records_collections  # noqa: E402, F401

EVENTS_TABLES = {
    "events_calendar",
    "events_event",
    "events_event_text",
    "events_occurrence_override",
    "events_category",
    "events_revision",
    "events_redirect",
    "events_calendar_redirect",
}


def test_host_metadata_has_events_tables():
    tables = set(build_module_metadata().tables)
    assert {t for t in tables if t.startswith("events_")} == EVENTS_TABLES


def test_host_loads_the_module():
    app = create_app(Settings())
    names = {m.meta.name for m in app.state.sm.modules}
    assert "Events" in names


def test_views_and_menu_mounted():
    from fastapi.routing import iter_route_contexts

    app = create_app(Settings())
    paths = {ctx.path for ctx in iter_route_contexts(app.routes)}
    assert paths >= {
        "/admin/events/",
        "/admin/events/calendars",
        "/admin/events/categories",
        "/admin/events/list",
        "/admin/events/edit/new",
        "/admin/events/edit/{event_id}",
    }
    items = [i for i in app.state.sm.menu_registry.all_items if i.group == "Events"]
    assert {i.url for i in items} == {
        "/admin/events/",
        "/admin/events/list",
        "/admin/events/calendars",
        "/admin/events/categories",
    }
    assert min(items, key=lambda i: i.order).url == "/admin/events/"
    assert {i.url: i.permissions for i in items} == {
        "/admin/events/": ["events.view"],
        "/admin/events/list": ["events.view"],
        "/admin/events/calendars": ["events.view"],
        "/admin/events/categories": ["events.view", "events.manage"],
    }


def test_resource_type_and_middleware():
    from sm_events.core.tenancy.request_context import RequestContextMiddleware

    app = create_app(Settings())
    assert app.state.sm.resource_types.get("events.calendar") is not None
    assert RequestContextMiddleware in {m.cls for m in app.user_middleware}


# --- the public surface, in the real host ------------------------------------------------


@pytest.fixture
def booted_host(tmp_path, monkeypatch):
    """The host's own ``main:app`` against a migrated database of its own (what
    ``test_host_boots.booted_host`` does; not shared, so neither test imports the other)."""
    import importlib

    url = f"sqlite+aiosqlite:///{tmp_path / 'host.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "host/alembic.ini", "upgrade", "heads"],
        cwd=REPO,
        env={**os.environ, "SM_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    monkeypatch.setenv("SM_DATABASE_URL", url)
    sys.modules.pop("main", None)
    try:
        yield importlib.import_module("main").app
    finally:
        sys.modules.pop("main", None)


def test_public_routes_wired_by_startup(booted_host, monkeypatch):
    """``on_startup`` mounts the public routers, exempts them from auth for ``GET`` and
    ``HEAD`` only, adds the rate limits, and the 404 a visitor gets is pagebuilder's (it is
    mounted here), not the sign-in screen."""
    from httpx import ASGITransport, AsyncClient
    from simple_module_hosting.public_access import is_public

    app = booted_host

    async def setup_done(_app) -> bool:
        return True

    # A fresh database sends every request to the first-run wizard; this is about the
    # routes, so the install counts as set up.
    monkeypatch.setattr(app.state.sm.setup_registry, "is_setup_complete", setup_done)

    async def exercise() -> dict:
        async with app.router.lifespan_context(app):
            paths = {c.path for c in iter_route_contexts(app.routes)}
            rules = app.state.rate_limit_rules
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://localhost"
            ) as http:
                page = await http.get("/events/no-such-event")
                feed = await http.get("/events/calendar.ics")
                write = await http.post("/events/no-such-event")
            return {
                "paths": paths,
                "page": page,
                "feed": feed,
                "write": write,
                "get_public": is_public(app, "GET", "/events/x"),
                "post_public": is_public(app, "POST", "/events/x"),
                "feed_rate": getattr(rules.match("GET", "/events/calendar.ics"), "rate", None),
                "api_rate": getattr(rules.match("GET", "/events/api/occurrences"), "rate", None),
            }

    got = asyncio.run(exercise())
    assert {
        "/events/",
        "/events/{slug}",
        "/events/c/{calendar}",
        "/events/calendar.ics",
        "/events/sitemap.xml",
        "/events/api/occurrences",
    } <= got["paths"]
    assert got["get_public"] is True and got["post_public"] is False
    assert (got["feed_rate"], got["api_rate"]) == ("60/minute", "120/minute")
    assert got["page"].status_code == 404, got["page"].text[:300]
    assert got["page"].headers["cache-control"] == "no-store"
    assert "PageBuilder/PublicNotFound" in got["page"].text
    assert got["feed"].status_code == 404
    assert got["feed"].json() == {"detail": "Not found", "code": "not_found"}
    assert got["write"].status_code not in (200, 404)  # still behind the sign-in
