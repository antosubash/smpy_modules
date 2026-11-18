"""Every public route is in the leak harness's table."""

from __future__ import annotations

from fastapi.routing import iter_route_contexts

from tests.support.calendars import PublicFixture
from tests.web.public.leaks import REDIRECT_ONLY, ROUTE_SURFACES, surfaces


def public_get_routes(app, prefix: str) -> set[str]:
    return {
        context.path
        for context in iter_route_contexts(app.routes)
        if context.path
        and (context.path == prefix or context.path.startswith(f"{prefix}/"))
        and "GET" in (context.methods or ())
    }


async def test_every_get_route_under_the_prefix_has_a_surface(public_locales_client):
    """A new public route that is not added to ``ROUTE_SURFACES`` (and so to ``surfaces()``)
    fails here, so no route can ship without the leak tests walking it."""
    app = public_locales_client.app
    names = {s.name for s in surfaces(PublicFixture.__new__(PublicFixture), "en")}
    expected: dict[str, str] = {}
    for prefix, default in (("/events", True), ("/de/events", False)):
        for template, surface in ROUTE_SURFACES.items():
            path = template.format(prefix=prefix.lstrip("/"))
            if not default and surface in ("sitemap", "occurrences api", "private feed"):
                continue
            expected[path] = surface
    found = public_get_routes(app, "/events") | public_get_routes(app, "/de/events")
    aliases = public_get_routes(app, "/en/events")
    assert found == set(expected), found ^ set(expected)
    assert aliases == {"/en/events/{rest:path}"}  # the default language's redundant prefix
    assert set(expected.values()) <= names, set(expected.values()) - names
    assert REDIRECT_ONLY not in expected.values()


async def test_the_table_has_no_stale_surface(public_locales_client):
    names = {s.name for s in surfaces(PublicFixture.__new__(PublicFixture), "en")}
    used = set(ROUTE_SURFACES.values())
    # the 404's suggestions are served by every route's 404 and have no route of their own
    assert names - used == {"404 suggestions"}
