"""Mounting, ordering, exemptions and rate limits of the public routers."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from simple_module_hosting._rate_limit import RateLimitMiddleware
from simple_module_hosting.public_access import is_public
from sm_events.core import boot, constants

from tests.support.app import build_public_app, public_http
from tests.support.public import INERTIA


def paths(app: FastAPI) -> set[str]:
    return {context.path for context in iter_route_contexts(app.routes)}


def handler(app: FastAPI, path: str, method: str = "GET") -> str | None:
    """The name of the endpoint that answers ``method path``: the first route, in the order
    they were added, whose path pattern and methods match."""
    for context in iter_route_contexts(app.routes):
        regex = getattr(context, "path_regex", None)
        if regex is None or regex.match(path) is None:
            continue
        if context.methods is None or method in context.methods:
            return context.endpoint.__name__  # type: ignore[union-attr]
    return None


async def test_routes_per_locale(public_locales_client):
    found = paths(public_locales_client.app)
    assert {
        "/events/",
        "/events/{slug}",
        "/de/events/",
        "/de/events/{slug}",
        "/events/sitemap.xml",
        "/events/api/occurrences",
        "/events/calendar.ics",
        "/events/c/{calendar}",
        "/events/c/{calendar}.ics",
        "/events/{slug}.ics",
        "/de/events/calendar.ics",
        "/de/events/{slug}.ics",
    } <= found
    assert "/de/events/sitemap.xml" not in found
    assert "/de/events/api/occurrences" not in found
    assert "/events/{rest:path}" not in found


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/events/", "index_page"),
        ("/events/sitemap.xml", "sitemap"),
        ("/events/api/occurrences", "public_occurrences"),
        ("/events/calendar.ics", "all_calendars_feed"),
        ("/events/c/team.ics", "calendar_feed"),
        ("/events/c/team", "calendar_page"),
        ("/events/team.ics", "event_ics"),
        ("/events/team", "event_page"),
        ("/de/events/calendar.ics", "all_calendars_feed"),
        ("/de/events/c/team", "calendar_page"),
        ("/de/events/team", "event_page"),
        # no sitemap or API under a second language: the catch-all answers (and 404s)
        ("/de/events/sitemap.xml", "event_page"),
        ("/de/events/api", "event_page"),
        ("/en/events/team", "redirect_to_unprefixed"),
        ("/en/events/c/team", "redirect_to_unprefixed"),
    ],
)
async def test_fixed_paths_before_catch_all(public_locales_client, path, expected):
    assert handler(public_locales_client.app, path) == expected


async def test_every_stub_answers_404_for_now(public_client):
    for path in (
        "/events/",
        "/events/c/x",
        "/events/x",
        "/events/x.ics",
        "/events/calendar.ics",
        "/events/c/x.ics",
        "/events/sitemap.xml",
        "/events/api/occurrences",
    ):
        for method in ("GET", "HEAD"):
            got = await public_client.request(method, path)
            assert got.status_code == 404, (method, path)
            assert got.headers["cache-control"] == "no-store", (method, path)
            assert "etag" not in got.headers


async def test_machine_routes_answer_the_json_envelope(public_client):
    got = await public_client.get("/events/calendar.ics")
    assert got.json() == {"detail": constants.NOT_FOUND_DETAIL, "code": "not_found"}


async def test_custom_prefix_from_settings():
    async with public_http(settings={"public_prefix": "/whats-on"}) as http:
        found = paths(http.app)
        assert "/whats-on/" in found and "/whats-on/{slug}" in found
        assert not any(p.startswith("/events") for p in found)
        assert (await http.get("/whats-on/x", headers=INERTIA)).status_code == 404
        assert (await http.get("/events/x")).json() == {"detail": "Not Found"}  # not mounted


@pytest.mark.parametrize("bad", ["/api/x", "/admin/events", "/", "/Events", "/de/events"])
async def test_an_unusable_prefix_serves_events(bad, caplog):
    with caplog.at_level(logging.ERROR, logger="sm_events.core.public_prefix"):
        async with public_http(
            settings={"public_prefix": bad, "content_locales": ("en", "de")}
        ) as http:
            assert "/events/{slug}" in paths(http.app)
    assert "is not usable, serving at /events" in caplog.text


async def test_a_prefix_another_module_already_serves_is_refused(caplog):
    def mounted_elsewhere(app: FastAPI) -> None:
        @app.get("/news/{slug}")
        async def news_article(slug: str):
            return slug

    with caplog.at_level(logging.ERROR, logger="sm_events.core.public_prefix"):
        async with public_http(
            settings={"public_prefix": "/news"}, before_wire=mounted_elsewhere
        ) as http:
            found = paths(http.app)
    assert "/events/{slug}" in found
    assert "is not usable" in caplog.text


async def test_wiring_twice_changes_nothing(public_locales_client):
    app = public_locales_client.app
    before = (
        len(app.routes),
        len(app.state.public_routes._routes),
        len(app.state.rate_limit_rules),
    )
    assert boot.wire_public(app) == "/events"
    after = (len(app.routes), len(app.state.public_routes._routes), len(app.state.rate_limit_rules))
    assert before == after


async def test_no_settings_no_wiring():
    assert boot.wire_public(FastAPI()) is None


@pytest.mark.parametrize(
    ("method", "path", "exempt"),
    [
        ("GET", "/events/", True),
        ("HEAD", "/events/", True),
        ("GET", "/events", True),
        ("HEAD", "/events", True),
        ("GET", "/events/x", True),
        ("GET", "/events/c/x.ics", True),
        ("GET", "/de/events/", True),
        ("GET", "/de/events", True),
        ("GET", "/de/events/x", True),
        ("GET", "/en/events/x", True),  # the default language's redundant prefix redirects
        ("GET", "/en/events", True),
        ("POST", "/events/x", False),
        ("POST", "/events/", False),
        ("PUT", "/events/x", False),
        ("DELETE", "/de/events/x", False),
        ("OPTIONS", "/events/x", False),
        ("GET", "/eventsfoo", False),
        ("GET", "/de/eventsfoo", False),
        ("GET", "/admin/events/", False),
        ("GET", "/api/events/calendars", False),
    ],
)
async def test_exemptions_pinned(public_locales_client, method, path, exempt):
    assert is_public(public_locales_client.app, method, path) is exempt


async def test_exemption_without_an_alias_for_one_language(public_client):
    assert is_public(public_client.app, "GET", "/events/x")
    assert not is_public(public_client.app, "GET", "/en/events/x")


async def test_rate_limit_rules_live(public_locales_client):
    rules = public_locales_client.app.state.rate_limit_rules

    def rate(method: str, path: str) -> str | None:
        rule = rules.match(method, path)
        return None if rule is None else rule.rate

    feed, api = constants.FEED_RATE, constants.PUBLIC_API_RATE
    for path in (
        "/events/calendar.ics",
        "/events/c/team.ics",
        "/events/x.ics",
        "/events/sitemap.xml",
        "/de/events/calendar.ics",
        "/de/events/x.ics",
        "/de/events/c/team.ics",
    ):
        for method in ("GET", "HEAD"):
            assert rate(method, path) == feed, (method, path)
    assert rate("GET", "/events/api/occurrences") == api
    for path in (
        "/events/",
        "/events/x",
        "/events/c/team",
        "/events/a/b.ics",
        "/events/api/occurrences/x",
        "/de/events/sitemap.xml",
        "/de/events/api/occurrences",
        "/eventsx/calendar.ics",
        "/x/events/calendar.ics",
    ):
        assert rate("GET", path) is None, path
    for method in ("POST", "PUT", "DELETE", "OPTIONS"):
        assert rate(method, "/events/calendar.ics") is None, method
        assert rate(method, "/events/api/occurrences") is None, method
    assert all(
        r.key == "ip"
        for r in (
            rules.match("GET", "/events/calendar.ics"),
            rules.match("GET", "/events/api/occurrences"),
        )
    )


async def test_the_limiter_reads_the_live_registry():
    """The middleware looks the registry up per request, so rules added in ``on_startup``
    (after the stack was configured) apply: the 61st feed request in a minute is a 429."""
    app, state = await build_public_app()
    app.add_middleware(RateLimitMiddleware, public_rate=None)
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
        for _ in range(60):
            assert (await http.get("/events/calendar.ics")).status_code == 404
        limited = await http.get("/events/calendar.ics")
        assert limited.status_code == 429 and "retry-after" in limited.headers
        # Another budget: pages and the API are separate buckets.
        assert (await http.get("/events/x")).status_code == 404
        assert (await http.get("/events/api/occurrences")).status_code == 404
    await state.engine.dispose()


async def test_rules_are_not_added_without_a_registry():
    app, state = await build_public_app()
    app.state.rate_limit_rules = None
    boot.register_public_rate_limits(app, "/events", ("en",))  # nothing to add to
    assert app.state.rate_limit_rules is None
    await state.engine.dispose()


async def test_alias_redirect(public_locales_client):
    got = await public_locales_client.get("/en/events/x")
    assert got.status_code == 301 and got.headers["location"] == "/events/x"
    keep = await public_locales_client.get("/en/events/c/team?page=2")
    assert keep.headers["location"] == "/events/c/team?page=2"
    top = await public_locales_client.get("/en/events/")
    assert top.headers["location"] == "/events/"
    assert (await public_locales_client.head("/en/events/x")).status_code == 301


async def test_alias_is_absent_with_one_language(public_client):
    got = await public_client.get("/en/events/x")
    assert got.status_code == 404 and got.json() == {"detail": "Not Found"}
