"""The public surface in the real host: ``main:app`` booted against a migrated database."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.routing import iter_route_contexts

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "host"))

# What ``main.py`` imports before ``create_app``: the records module seals its collection
# registry in the first app any test builds.
import records_collections  # noqa: E402, F401


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
                missing = await http.get("/events/no-such-event.ics")
                write = await http.post("/events/no-such-event")
                blocks = await http.get("/api/events/public/calendars")
                blocks_post = await http.post("/api/events/public/calendars")
                admin = await http.get("/api/events/calendars")
            return {
                "blocks": blocks,
                "blocks_post": blocks_post,
                "admin": admin,
                "paths": paths,
                "page": page,
                "feed": feed,
                "missing": missing,
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
    assert got["feed"].status_code == 200
    assert got["feed"].headers["content-type"] == "text/calendar; charset=utf-8"
    assert got["feed"].content.startswith(b"BEGIN:VCALENDAR\r\n")
    assert got["missing"].status_code == 404
    assert got["missing"].json() == {"detail": "Not found", "code": "not_found"}
    assert got["write"].status_code not in (200, 404)  # still behind the sign-in
    # The pagebuilder blocks' anonymous routes: readable without a session, read-only, and the
    # console API next to them is still behind the sign-in.
    assert got["blocks"].status_code == 200, got["blocks"].text[:300]
    assert got["blocks"].json()["calendars"] == []
    assert got["blocks_post"].status_code in (401, 403, 405)
    assert got["admin"].status_code in (401, 403)


def test_not_modified_carries_what_we_pin(booted_host, monkeypatch):
    """What a 304 from the public routes carries, so a framework change is noticed: the cache
    headers events sets, and whatever the framework's CSP layer does to a 304 (read off a real
    host, not assumed). A 304 that gained a ``Content-Security-Policy`` would be merged into the
    browser's cached copy, whose scripts carry the nonce of the policy they were served with."""
    from httpx import ASGITransport, AsyncClient

    app = booted_host

    async def setup_done(_app) -> bool:
        return True

    monkeypatch.setattr(app.state.sm.setup_registry, "is_setup_complete", setup_done)

    async def exercise() -> dict:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http,
        ):
            first = await http.get("/events/calendar.ics")
            second = await http.get(
                "/events/calendar.ics", headers={"If-None-Match": first.headers["etag"]}
            )
            sitemap = await http.get("/events/sitemap.xml")
            sitemap_304 = await http.get(
                "/events/sitemap.xml", headers={"If-None-Match": sitemap.headers["etag"]}
            )
        return {"first": first, "second": second, "sitemap": sitemap, "sitemap_304": sitemap_304}

    got = asyncio.run(exercise())
    for ok, not_modified in (
        (got["first"], got["second"]),
        (got["sitemap"], got["sitemap_304"]),
    ):
        assert ok.status_code == 200 and not_modified.status_code == 304
        assert not_modified.content == b""
        for name in ("etag", "cache-control", "vary"):
            assert not_modified.headers[name] == ok.headers[name], name
        # PINNED (see CSP_ON_200 / CSP_ON_304): what the framework's CSP layer does to each.
        assert ("content-security-policy" in not_modified.headers) == CSP_ON_304
        assert ("content-security-policy" in ok.headers) == CSP_ON_200


CSP_ON_200 = True
CSP_ON_304 = False
"""Measured on the real host (framework 0.0.44): its CSP layer adds the nonce policy to a 200 and
leaves a 304 without one, which is what a conditional response needs (a browser merges a 304's
headers into its cached copy, whose scripts carry the nonce of the policy it was served with;
news #322). Events sets no CSP header itself. If either value flips, the framework changed."""


def test_generated_urls_ignore_a_spoofed_host(booted_host, monkeypatch):
    """With ``public_base_url`` set, no canonical, hreflang, sitemap or feed URL carries a host the
    client chose (``Host``, ``X-Forwarded-Host``, ``X-Forwarded-Proto``). Without it they follow
    what the framework's forwarded-host allow-list accepts (nothing, here: the list is empty, so
    only ``Host`` counts) and the response varies on ``Host``."""
    from httpx import ASGITransport, AsyncClient

    app = booted_host

    async def setup_done(_app) -> bool:
        return True

    monkeypatch.setattr(app.state.sm.setup_registry, "is_setup_complete", setup_done)
    spoof = {"X-Forwarded-Host": "evil.test", "X-Forwarded-Proto": "http"}
    paths = ("/events/", "/events/calendar.ics", "/events/sitemap.xml")

    async def fetch_both() -> tuple[dict[str, object], dict[str, object]]:
        out: tuple[dict[str, object], dict[str, object]] = ({}, {})
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http,
        ):
            for slot, base in zip(out, ("https://events.example.org", ""), strict=True):
                monkeypatch.setattr(app.state.sm.settings, "public_base_url", base, raising=False)
                for path in paths:
                    slot[path] = await http.get(path, headers={"Host": "evil.test"} | spoof)
        return out

    configured, guessed = asyncio.run(fetch_both())
    for path, got in configured.items():
        assert got.status_code == 200, path
        assert "evil.test" not in got.text, path
        if path == "/events/":  # the others hold no URL until an event exists
            assert "https://events.example.org/events/" in got.text, path

    for path, got in guessed.items():
        assert got.status_code == 200, path
        if path == "/events/":
            assert "http://evil.test/events/" in got.text, path  # follows Host, as warned
        assert "host" in got.headers.get("vary", "").lower(), path
